"""
LLM分类器 - 使用阿里云大语言模型API进行段落分类
V1版本：13类标签（侧重项目申请书，包含标题和摘要）

支持两种分类模式：
1. 逐个分类（默认）：每个段落单独调用一次LLM
2. 批量分类（推荐）：所有段落一次LLM调用完成，大幅减少延迟

并发优化：
- OpenAI 客户端配置 timeout，防止 API 无响应时线程被永久占用
- 失败自动重试（指数退避），提高大量并发时的稳定性
"""
import json
import re
import time
from typing import List, Dict, Tuple, Optional, Literal
from openai import OpenAI
from httpx import Timeout

from ..config import settings, V1_CLASSIFICATION_TAGS, V1_TAG_DESCRIPTIONS


BatchMode = Literal["single", "batch"]


def _create_llm_client() -> OpenAI:
    """创建带超时和重试配置的 OpenAI 客户端"""
    return OpenAI(
        api_key=settings.require_llm_api_key(),
        base_url=settings.LLM_BASE_URL,
        timeout=Timeout(settings.LLM_TIMEOUT, connect=10.0),
        max_retries=settings.LLM_MAX_RETRIES,
    )


class LLMClassifier:
    """基于LLM的段落分类器"""
    
    MAX_BATCH_SIZE = 15
    MAX_SEGMENT_LENGTH_BATCH = 500
    
    def __init__(self, model: str = None, batch_mode: BatchMode = None):
        self.client = _create_llm_client()
        self.model = model if model else settings.LLM_MODEL
        self.tags = V1_CLASSIFICATION_TAGS
        self.batch_mode = batch_mode if batch_mode else getattr(settings, 'DEFAULT_BATCH_MODE', 'batch')
    
    def classify_segment(self, segment: str) -> Tuple[str, float]:
        """
        对单个段落进行分类
        
        Args:
            segment: 待分类的段落文本
            
        Returns:
            Tuple[str, float]: (预测标签, 置信度)
        """
        if not segment.strip():
            return "其他", 0.0
        
        # 构建分类提示词
        prompt = self._build_classification_prompt(segment)
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": self._get_system_prompt()
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.1,  # 低温度以获得更确定的输出
                max_tokens=200
            )
            
            result_text = response.choices[0].message.content.strip()
            tag, confidence = self._parse_classification_result(result_text)
            
            return tag, confidence
            
        except Exception as e:
            print(f"LLM分类失败: {e}")
            return "其他", 0.0
    
    def classify_segments_batch(self, segments: List[str]) -> List[Tuple[str, float]]:
        """
        批量分类多个段落
        
        Args:
            segments: 段落列表
            
        Returns:
            List[Tuple[str, float]]: 每个段落的(标签, 置信度)列表
        """
        if not segments:
            return []
        
        # 根据模式选择分类方式
        if self.batch_mode == "batch":
            print(f"[INFO] 使用批量分类模式 (模型: {self.model})...")
            results = self._classify_batch_oneshot(segments)
        else:
            print(f"[INFO] 使用逐个分类模式 (模型: {self.model})...")
            results = self._classify_one_by_one(segments)
        
        # 应用一致性策略：修正孤立的异类标签
        results = self._apply_consistency_smoothing(segments, results)
        
        return results
    
    def _classify_one_by_one(self, segments: List[str]) -> List[Tuple[str, float]]:
        """逐个分类（每个段落单独调用LLM）"""
        results = []
        for i, segment in enumerate(segments):
            print(f"  正在分类第 {i+1}/{len(segments)} 个段落...")
            tag, confidence = self.classify_segment(segment)
            results.append((tag, confidence))
        return results
    
    def _classify_batch_oneshot(self, segments: List[str]) -> List[Tuple[str, float]]:
        """
        批量分类（一次LLM调用完成所有段落的分类）
        
        优势：
        - 大幅减少API调用次数（N次 -> 1次）
        - 显著降低总延迟
        - 降低API调用成本
        """
        # 如果段落数量超过限制，分批处理
        if len(segments) > self.MAX_BATCH_SIZE:
            print(f"  段落数({len(segments)})超过单批限制({self.MAX_BATCH_SIZE})，将分批处理...")
            all_results = []
            for i in range(0, len(segments), self.MAX_BATCH_SIZE):
                batch = segments[i:i + self.MAX_BATCH_SIZE]
                print(f"  处理批次 {i//self.MAX_BATCH_SIZE + 1}，包含 {len(batch)} 个段落...")
                batch_results = self._do_batch_classify(batch)
                all_results.extend(batch_results)
            return all_results
        else:
            return self._do_batch_classify(segments)
    
    def _do_batch_classify(self, segments: List[str]) -> List[Tuple[str, float]]:
        """执行单次批量分类请求"""
        # 构建批量分类的prompt
        prompt = self._build_batch_classification_prompt(segments)
        
        start_time = time.time()
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self._get_batch_system_prompt()},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=2000  # 批量输出需要更多token
            )
            
            latency = time.time() - start_time
            result_text = response.choices[0].message.content.strip()
            
            print(f"  ✓ 批量分类完成，耗时: {latency:.2f}s，共 {len(segments)} 个段落")
            
            # 解析批量结果
            results = self._parse_batch_classification_result(result_text, len(segments))
            
            return results
            
        except Exception as e:
            print(f"  ✗ 批量分类失败: {e}，回退到逐个分类...")
            # 回退到逐个分类
            return self._classify_one_by_one(segments)
    
    def _get_batch_system_prompt(self) -> str:
        """获取批量分类的系统提示词"""
        tags_str = '\n'.join([f"- {tag}" for tag in self.tags[:-1]])
        
        return f"""你是一个专业的学术文档分析专家，专门负责对科研项目申请书的段落进行分类。

你的任务是将给定的多个段落分别分类到以下类别之一：
{tags_str}

如果段落内容与以上所有类别都不相关，或者无法确定，则分类为"其他"。

分类标准说明：
1. 标题：文档或项目的标题（通常在文档开头，内容简短且概括性强）
2. 摘要：对全文内容的概括性描述（通常出现在标题之后，概述整个项目的主要内容）
3. 项目研究意义：阐述研究的重要性、价值和必要性
4. 国内外研究现状及发展动态分析：综述相关领域的研究进展和发展趋势
5. 科学意义与应用前景：描述研究的科学价值和潜在应用
6. 项目的研究内容：具体说明要研究什么内容
7. 研究目标：明确的研究目标和预期成果
8. 拟解决的关键科学问题：需要突破的核心科学难题
9. 研究方法：采用的研究方法和手段
10. 技术路线：研究的技术路径和实施步骤
11. 关键技术：需要攻克的关键技术难点
12. 本项目的特色与创新之处：项目的独特之处和创新点

【重要】请严格按照以下JSON数组格式输出所有段落的分类结果：
[
  {{"id": 1, "tag": "分类标签1", "confidence": 0.95}},
  {{"id": 2, "tag": "分类标签2", "confidence": 0.90}},
  ...
]

要求：
- 按顺序为每个段落输出分类结果
- id从1开始，与输入段落顺序对应
- confidence是置信度，范围0-1
- 必须输出完整的JSON数组，不要遗漏任何段落"""

    def _build_batch_classification_prompt(self, segments: List[str]) -> str:
        """构建批量分类的用户提示词"""
        # 构建段落列表
        segment_texts = []
        for i, segment in enumerate(segments):
            # 截断过长的段落
            if len(segment) > self.MAX_SEGMENT_LENGTH_BATCH:
                segment = segment[:self.MAX_SEGMENT_LENGTH_BATCH] + "..."
            segment_texts.append(f"【段落{i+1}】\n{segment}")
        
        all_segments = "\n\n".join(segment_texts)
        
        return f"""请对以下 {len(segments)} 个学术文档段落进行分类：

{all_segments}

请以JSON数组格式输出所有段落的分类结果。"""

    def _parse_batch_classification_result(
        self, 
        result_text: str, 
        expected_count: int
    ) -> List[Tuple[str, float]]:
        """解析批量分类的LLM返回结果"""
        results = []
        
        try:
            # 尝试提取JSON数组
            # 匹配 [...] 格式
            json_match = re.search(r'\[[\s\S]*\]', result_text)
            if json_match:
                json_str = json_match.group()
                parsed = json.loads(json_str)
                
                if isinstance(parsed, list):
                    for item in parsed:
                        tag = item.get('tag', '其他')
                        confidence = float(item.get('confidence', 0.5))
                        
                        # 验证标签
                        if tag not in self.tags:
                            tag = self._fuzzy_match_tag(tag)
                        
                        confidence = max(0.0, min(1.0, confidence))
                        results.append((tag, confidence))
        
        except (json.JSONDecodeError, ValueError) as e:
            print(f"  [WARN] 批量解析JSON失败: {e}")
        
        # 如果解析结果数量不匹配，尝试备用解析
        if len(results) != expected_count:
            print(f"  [WARN] 解析结果数量不匹配 (期望: {expected_count}, 实际: {len(results)})，尝试备用解析...")
            results = self._fallback_parse_batch(result_text, expected_count)
        
        # 如果还是不够，补充默认值
        while len(results) < expected_count:
            results.append(("其他", 0.5))
        
        return results[:expected_count]
    
    def _fallback_parse_batch(
        self, 
        result_text: str, 
        expected_count: int
    ) -> List[Tuple[str, float]]:
        """备用解析方法：逐行解析"""
        results = []
        
        # 尝试按行解析，查找每个段落的分类
        for i in range(1, expected_count + 1):
            # 查找类似 "段落1" 或 "id": 1 的模式
            patterns = [
                rf'段落{i}[：:]\s*(\S+)',
                rf'"id"\s*:\s*{i}[^}}]*"tag"\s*:\s*"([^"]+)"',
                rf'{i}\.\s*(\S+)',
            ]
            
            found = False
            for pattern in patterns:
                match = re.search(pattern, result_text)
                if match:
                    tag = match.group(1)
                    if tag in self.tags:
                        results.append((tag, 0.7))
                        found = True
                        break
                    else:
                        matched_tag = self._fuzzy_match_tag(tag)
                        if matched_tag != "其他":
                            results.append((matched_tag, 0.6))
                            found = True
                            break
            
            if not found:
                # 没找到，添加默认值
                results.append(("其他", 0.5))
        
        return results
    
    def _get_system_prompt(self) -> str:
        """获取系统提示词"""
        tags_str = '\n'.join([f"- {tag}" for tag in self.tags[:-1]])  # 不包含"其他"
        
        return f"""你是一个专业的学术文档分析专家，专门负责对科研项目申请书的段落进行分类。

你的任务是将给定的段落分类到以下类别之一：
{tags_str}

如果段落内容与以上所有类别都不相关，或者无法确定，则分类为"其他"。

分类标准说明：
1. 标题：文档或项目的标题（通常在文档开头，内容简短且概括性强）
2. 摘要：对全文内容的概括性描述（通常出现在标题之后，概述整个项目的主要内容）
3. 项目研究意义：阐述研究的重要性、价值和必要性
4. 国内外研究现状及发展动态分析：综述相关领域的研究进展和发展趋势
5. 科学意义与应用前景：描述研究的科学价值和潜在应用
6. 项目的研究内容：具体说明要研究什么内容
7. 研究目标：明确的研究目标和预期成果
8. 拟解决的关键科学问题：需要突破的核心科学难题
9. 研究方法：采用的研究方法和手段
10. 技术路线：研究的技术路径和实施步骤
11. 关键技术：需要攻克的关键技术难点
12. 本项目的特色与创新之处：项目的独特之处和创新点

请严格按照以下JSON格式输出：
{{"tag": "分类标签", "confidence": 0.95}}

其中confidence是你对分类结果的置信度，范围0-1。"""

    def _build_classification_prompt(self, segment: str) -> str:
        """构建分类提示词"""
        # 截断过长的文本
        max_length = 3000
        if len(segment) > max_length:
            segment = segment[:max_length] + "..."
        
        return f"""请对以下学术文档段落进行分类：

---
{segment}
---

请以JSON格式输出分类结果。"""

    def _parse_classification_result(self, result_text: str) -> Tuple[str, float]:
        """解析LLM返回的分类结果"""
        try:
            # 尝试提取JSON部分
            json_match = re.search(r'\{[^}]+\}', result_text)
            if json_match:
                json_str = json_match.group()
                result = json.loads(json_str)
                
                tag = result.get('tag', '其他')
                confidence = float(result.get('confidence', 0.5))
                
                # 验证标签是否有效
                if tag not in self.tags:
                    # 尝试模糊匹配
                    tag = self._fuzzy_match_tag(tag)
                
                # 确保置信度在有效范围内
                confidence = max(0.0, min(1.0, confidence))
                
                return tag, confidence
            
        except (json.JSONDecodeError, ValueError) as e:
            print(f"解析分类结果失败: {e}, 原文: {result_text}")
        
        # 如果解析失败，尝试直接从文本中提取标签
        for tag in self.tags:
            if tag in result_text:
                return tag, 0.7
        
        return "其他", 0.5
    
    def _fuzzy_match_tag(self, text: str) -> str:
        """模糊匹配标签"""
        text_lower = text.lower()
        
        # 定义关键词映射
        keyword_map = {
            "标题": ["标题", "题目", "title"],
            "摘要": ["摘要", "abstract", "概述", "简介"],
            "项目研究意义": ["意义", "重要性", "价值"],
            "国内外研究现状及发展动态分析": ["现状", "动态", "综述", "进展", "发展"],
            "科学意义与应用前景": ["前景", "应用", "科学意义"],
            "项目的研究内容": ["研究内容", "内容"],
            "研究目标": ["目标", "目的"],
            "拟解决的关键科学问题": ["科学问题", "问题", "关键问题"],
            "研究方法": ["方法", "手段"],
            "技术路线": ["路线", "步骤", "流程"],
            "关键技术": ["关键技术", "技术难点"],
            "本项目的特色与创新之处": ["特色", "创新", "独特"],
        }
        
        for tag, keywords in keyword_map.items():
            for keyword in keywords:
                if keyword in text_lower or keyword in text:
                    return tag
        
        return "其他"
    
    def generate_abstract(self, text: str, max_length: int = 500) -> str:
        """
        使用LLM生成摘要
        
        Args:
            text: 待生成摘要的文本
            max_length: 摘要最大长度（字符数）
            
        Returns:
            str: 生成的摘要
        """
        if not text or not text.strip():
            return ""
        
        # 截断过长的文本
        if len(text) > 10000:
            text = text[:10000] + "..."
        
        prompt = f"""请为以下学术文档生成一个不超过{max_length}字的摘要。
摘要应该概括文档的主要研究内容、目标、方法和预期成果。

---文档内容---
{text}
---文档结束---

请直接输出摘要内容，不要包含"摘要："等前缀。"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个专业的学术文档摘要生成专家。请根据给定的文档内容，生成一个简洁、准确、完整的摘要。"
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.3,
                max_tokens=800
            )
            
            abstract = response.choices[0].message.content.strip()
            
            # 确保摘要不超过最大长度
            if len(abstract) > max_length:
                # 在句子边界处截断
                abstract = self._truncate_at_sentence(abstract, max_length)
            
            return abstract
            
        except Exception as e:
            print(f"摘要生成失败: {e}")
            return ""
    
    def _truncate_at_sentence(self, text: str, max_length: int) -> str:
        """
        在句子边界处截断文本
        
        Args:
            text: 待截断的文本
            max_length: 最大长度
            
        Returns:
            str: 截断后的文本
        """
        if len(text) <= max_length:
            return text
        
        # 在max_length范围内查找最后一个句子结束符
        truncated = text[:max_length]
        
        # 句子结束符
        terminators = ['。', '！', '？', '；', '.', '!', '?']
        
        last_pos = -1
        for term in terminators:
            pos = truncated.rfind(term)
            if pos > last_pos:
                last_pos = pos
        
        if last_pos > max_length * 0.5:  # 确保至少保留一半的内容
            return truncated[:last_pos + 1]
        
        return truncated
    
    def _apply_consistency_smoothing(
        self,
        segments: List[str],
        results: List[Tuple[str, float]]
    ) -> List[Tuple[str, float]]:
        """
        应用一致性平滑策略
        当一个段落被分割成多个chunk时，确保标签一致
        使用滑动窗口多数投票来修正孤立的异类标签
        """
        if len(results) <= 2:
            return results
        
        smoothed_results = list(results)
        
        # 使用窗口大小为3的多数投票
        window_size = 3
        
        for i in range(1, len(results) - 1):
            current_tag = results[i][0]
            current_conf = results[i][1]
            
            # 如果当前置信度较低，考虑用周围的标签替换
            if current_conf < 0.7:
                # 获取窗口内的标签
                window_tags = [
                    results[j][0]
                    for j in range(max(0, i - 1), min(len(results), i + 2))
                ]
                
                # 统计标签频率
                tag_counts = {}
                for tag in window_tags:
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1
                
                # 如果当前标签是孤立的（周围都是同一个其他标签）
                if tag_counts.get(current_tag, 0) == 1 and len(tag_counts) == 2:
                    # 找到主要标签
                    for tag, count in tag_counts.items():
                        if tag != current_tag and count >= 2:
                            smoothed_results[i] = (tag, current_conf * 0.9)
                            break
        
        return smoothed_results
