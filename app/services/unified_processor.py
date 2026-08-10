"""
统一处理器 - 合并分段与分类的 LLM 调用
一次 LLM 调用同时完成语义分段和标签分类，大幅提升效率

V1版本：13类标签（侧重项目申请书，包含标题和摘要）
"""
import json
import re
from typing import List, Tuple, Optional
from dataclasses import dataclass
from openai import OpenAI
from httpx import Timeout

from ..config import settings, V1_CLASSIFICATION_TAGS, V1_TAG_DESCRIPTIONS


@dataclass
class SegmentWithTag:
    """带标签的段落"""
    content: str
    tag: str
    confidence: float


class UnifiedProcessor:
    """
    统一处理器
    将语义分段和标签分类合并为一次 LLM 调用
    """
    
    MAX_CHUNK_SIZE = 8000
    
    def __init__(self, model: str = None):
        self.client = OpenAI(
            api_key=settings.require_llm_api_key(),
            base_url=settings.LLM_BASE_URL,
            timeout=Timeout(settings.LLM_TIMEOUT, connect=10.0),
            max_retries=settings.LLM_MAX_RETRIES,
        )
        self.model = model if model else settings.LLM_MODEL
        self.tags = V1_CLASSIFICATION_TAGS
    
    def process(self, text: str) -> List[SegmentWithTag]:
        """
        一次性完成分段和分类
        
        Args:
            text: 待处理的完整文本
            
        Returns:
            List[SegmentWithTag]: 带标签的段落列表
        """
        if not text or not text.strip():
            return []
        
        text = text.strip()
        
        # 先应用语义聚合规则
        text = self._apply_semantic_aggregation(text)
        
        # 如果文本很短，直接处理
        if len(text) < 300:
            return self._process_short_text(text)
        
        # 如果文本不太长，一次性处理
        if len(text) <= self.MAX_CHUNK_SIZE:
            return self._unified_llm_process(text)
        
        # 长文本分批处理
        return self._batch_process(text)
    
    def _process_short_text(self, text: str) -> List[SegmentWithTag]:
        """处理短文本"""
        # 短文本直接作为一个段落，单独分类
        tag, confidence = self._classify_single(text)
        return [SegmentWithTag(content=text, tag=tag, confidence=confidence)]
    
    def _classify_single(self, text: str) -> Tuple[str, float]:
        """对单个文本进行分类"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self._get_classification_only_prompt()},
                    {"role": "user", "content": f"请对以下文本进行分类：\n\n{text[:3000]}"}
                ],
                temperature=0.1,
                max_tokens=200
            )
            result = response.choices[0].message.content.strip()
            return self._parse_single_classification(result)
        except Exception as e:
            print(f"分类失败: {e}")
            return "其他", 0.5
    
    def _unified_llm_process(self, text: str) -> List[SegmentWithTag]:
        """
        统一 LLM 处理：一次调用完成分段和分类
        """
        prompt = self._build_unified_prompt(text)
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self._get_unified_system_prompt()},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=4000
            )
            
            result_text = response.choices[0].message.content.strip()
            return self._parse_unified_result(result_text, text)
            
        except Exception as e:
            print(f"统一处理失败: {e}")
            # 失败时使用备用方案
            return self._fallback_process(text)
    
    def _batch_process(self, text: str) -> List[SegmentWithTag]:
        """
        分批处理长文本
        """
        # 先进行粗分段
        chunks = self._split_into_chunks(text)
        
        all_results = []
        for chunk in chunks:
            chunk_results = self._unified_llm_process(chunk)
            all_results.extend(chunk_results)
        
        # 处理批次边界
        return self._merge_boundary_segments(all_results)
    
    def _split_into_chunks(self, text: str) -> List[str]:
        """将文本分成可处理的块"""
        chunks = []
        
        # 按双换行分段
        paragraphs = re.split(r'\n\s*\n', text)
        
        current_chunk = ""
        for para in paragraphs:
            if len(current_chunk) + len(para) > self.MAX_CHUNK_SIZE:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = para
            else:
                current_chunk = current_chunk + "\n\n" + para if current_chunk else para
        
        if current_chunk.strip():
            chunks.append(current_chunk.strip())
        
        return chunks if chunks else [text]
    
    def _merge_boundary_segments(self, segments: List[SegmentWithTag]) -> List[SegmentWithTag]:
        """合并边界处可能被错误分开的段落"""
        if len(segments) <= 1:
            return segments
        
        merged = [segments[0]]
        
        for i in range(1, len(segments)):
            current = segments[i]
            previous = merged[-1]
            
            # 如果前一段没有完整结尾且标签相同，合并
            if (not self._is_complete_sentence(previous.content) and 
                previous.tag == current.tag):
                merged[-1] = SegmentWithTag(
                    content=previous.content + "\n" + current.content,
                    tag=previous.tag,
                    confidence=min(previous.confidence, current.confidence)
                )
            else:
                merged.append(current)
        
        return merged
    
    def _is_complete_sentence(self, text: str) -> bool:
        """检查文本是否以完整句子结尾"""
        terminators = ('。', '！', '？', '；', '.', '!', '?', '…')
        return text.rstrip().endswith(terminators)
    
    def _fallback_process(self, text: str) -> List[SegmentWithTag]:
        """备用处理方案"""
        # 简单分段
        paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
        
        results = []
        for para in paragraphs:
            tag, confidence = self._classify_single(para)
            results.append(SegmentWithTag(content=para, tag=tag, confidence=confidence))
        
        return results
    
    def _get_unified_system_prompt(self) -> str:
        """获取统一处理的系统提示词"""
        tags_str = '\n'.join([f"- {tag}" for tag in self.tags[:-1]])
        
        return f"""你是一个专业的学术文档分析专家。你的任务是对学术文档进行【语义分段】和【标签分类】，一次性完成两个任务。

## 分类标签体系

{tags_str}
- 其他（无法归类到以上类别的内容）

## 分类标准

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

## 分段原则（语义聚合规则）

1. **冒号聚合**：以冒号结尾的句子，其后的补充说明必须合并为同一段落
2. **列表完整性**：整组列表项（1. 2. 3.、(1)(2)(3)、①②③等）必须聚合在同一段落
3. **句子完整性**：未结束的句子必须与后续内容合并
4. **主题一致性**：同一主题的内容归入同一段落
5. **段落长度**：每段控制在 100-2000 字（列表可适当放宽）

## 输出格式

严格按照以下 JSON 格式输出：
```json
{{
  "segments": [
    {{
      "content": "段落1的完整内容...",
      "tag": "分类标签",
      "confidence": 0.95
    }},
    {{
      "content": "段落2的完整内容...",
      "tag": "分类标签",
      "confidence": 0.90
    }}
  ]
}}
```

确保：
- 所有原文内容都被包含在某个段落中
- 不要遗漏任何内容
- 不要添加原文没有的内容
- confidence 范围 0-1，表示分类置信度
- 只输出 JSON，不要输出其他内容"""

    def _get_classification_only_prompt(self) -> str:
        """获取仅分类的系统提示词"""
        tags_str = '\n'.join([f"- {tag}" for tag in self.tags[:-1]])
        return f"""你是学术文档分析专家，请将文本分类到以下类别之一：
{tags_str}
- 其他

分类说明：
- 标题：文档或项目的标题（通常在文档开头，内容简短且概括性强）
- 摘要：对全文内容的概括性描述

输出格式：{{"tag": "分类标签", "confidence": 0.95}}"""

    def _build_unified_prompt(self, text: str) -> str:
        """构建统一处理的用户提示词"""
        # 截断过长文本
        if len(text) > self.MAX_CHUNK_SIZE:
            text = text[:self.MAX_CHUNK_SIZE] + "...[文本已截断]"
        
        return f"""请对以下学术文档进行语义分段和标签分类：

---文档开始---
{text}
---文档结束---

请按照系统提示的 JSON 格式输出分段和分类结果。"""

    def _parse_unified_result(self, result_text: str, original_text: str) -> List[SegmentWithTag]:
        """解析统一处理的结果"""
        try:
            # 提取 JSON
            json_match = re.search(r'\{[\s\S]*"segments"[\s\S]*\}', result_text)
            if not json_match:
                print(f"无法提取JSON: {result_text[:200]}")
                return self._fallback_process(original_text)
            
            result = json.loads(json_match.group())
            
            if "segments" not in result:
                return self._fallback_process(original_text)
            
            segments = []
            for item in result["segments"]:
                content = item.get("content", "").strip()
                tag = item.get("tag", "其他")
                confidence = float(item.get("confidence", 0.5))
                
                if not content:
                    continue
                
                # 验证标签
                if tag not in self.tags:
                    tag = self._fuzzy_match_tag(tag)
                
                # 确保置信度在有效范围
                confidence = max(0.0, min(1.0, confidence))
                
                segments.append(SegmentWithTag(
                    content=content,
                    tag=tag,
                    confidence=confidence
                ))
            
            return segments if segments else self._fallback_process(original_text)
            
        except json.JSONDecodeError as e:
            print(f"JSON 解析失败: {e}")
            return self._fallback_process(original_text)
        except Exception as e:
            print(f"解析结果失败: {e}")
            return self._fallback_process(original_text)
    
    def _parse_single_classification(self, result_text: str) -> Tuple[str, float]:
        """解析单个分类结果"""
        try:
            json_match = re.search(r'\{[^}]+\}', result_text)
            if json_match:
                result = json.loads(json_match.group())
                tag = result.get('tag', '其他')
                confidence = float(result.get('confidence', 0.5))
                
                if tag not in self.tags:
                    tag = self._fuzzy_match_tag(tag)
                
                return tag, max(0.0, min(1.0, confidence))
        except:
            pass
        
        # 尝试从文本中匹配标签
        for tag in self.tags:
            if tag in result_text:
                return tag, 0.7
        
        return "其他", 0.5
    
    def _fuzzy_match_tag(self, text: str) -> str:
        """模糊匹配标签"""
        keyword_map = {
            "标题": ["标题", "题目", "title"],
            "摘要": ["摘要", "abstract", "概述", "简介"],
            "项目研究意义": ["意义", "重要性", "价值", "必要性"],
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
                if keyword in text:
                    return tag
        
        return "其他"
    
    # ==================== 语义聚合规则 ====================
    
    def _apply_semantic_aggregation(self, text: str) -> str:
        """应用语义聚合规则"""
        lines = text.split('\n')
        lines = self._apply_cross_page_compensation(lines)
        lines = self._apply_colon_aggregation(lines)
        lines = self._apply_list_aggregation(lines)
        return '\n'.join(lines)
    
    def _is_list_item(self, line: str) -> bool:
        """检查是否是列表项"""
        line = line.strip()
        if not line:
            return False
        patterns = [
            r'^\d+[\.、]\s*',           # 1. 2. 或 1、2、
            r'^[\(（]\d+[\)）]\s*',      # (1) (2)
            r'^[①②③④⑤⑥⑦⑧⑨⑩]\s*',      # ① ② ③
            r'^第[一二三四五六七八九十]+[条款项]\s*',  # 第一条
            r'^[a-zA-Z][\.、\)）]\s*',   # a. b.
            r'^[一二三四五六七八九十]+[、\.]\s*',  # 一、二、
            r'^[-•·]\s+',               # - • ·
        ]
        return any(re.match(p, line) for p in patterns)
    
    def _apply_colon_aggregation(self, lines: List[str]) -> List[str]:
        """规则A: 冒号换行聚合"""
        if not lines:
            return lines
        
        result = []
        i = 0
        while i < len(lines):
            current = lines[i]
            if current.rstrip().endswith(('：', ':')):
                aggregated = [current]
                i += 1
                while i < len(lines) and lines[i].strip() and not self._is_section_start(lines[i]):
                    aggregated.append(lines[i])
                    i += 1
                result.append('\n'.join(aggregated))
            else:
                result.append(current)
                i += 1
        return result
    
    def _apply_list_aggregation(self, lines: List[str]) -> List[str]:
        """规则B: 列表项汇聚"""
        if not lines:
            return lines
        
        result = []
        i = 0
        while i < len(lines):
            if self._is_list_item(lines[i]):
                list_items = [lines[i]]
                i += 1
                while i < len(lines):
                    if self._is_list_item(lines[i]) or (lines[i].strip() and not self._is_section_start(lines[i])):
                        list_items.append(lines[i])
                        i += 1
                    elif not lines[i].strip():
                        # 空行，检查后续是否还有列表项
                        if i + 1 < len(lines) and self._is_list_item(lines[i + 1]):
                            list_items.append(lines[i])
                            i += 1
                        else:
                            break
                    else:
                        break
                result.append('\n'.join(list_items))
            else:
                result.append(lines[i])
                i += 1
        return result
    
    def _apply_cross_page_compensation(self, lines: List[str]) -> List[str]:
        """规则C: 跨页逻辑补偿"""
        if not lines:
            return lines
        
        terminators = ('。', '！', '？', '；', '.', '!', '?', '…')
        page_pattern = re.compile(r'^[-—]\s*\d+\s*[-—]$|^\d+$|^第\s*\d+\s*页$', re.I)
        
        result = []
        i = 0
        while i < len(lines):
            current = lines[i]
            if page_pattern.match(current.strip()):
                i += 1
                continue
            
            if current.rstrip() and not current.rstrip().endswith(terminators):
                combined = [current]
                i += 1
                while i < len(lines):
                    next_line = lines[i]
                    if page_pattern.match(next_line.strip()):
                        i += 1
                        continue
                    if not next_line.strip() or self._is_section_start(next_line) or self._is_list_item(next_line):
                        break
                    combined.append(next_line)
                    i += 1
                    if next_line.rstrip().endswith(terminators):
                        break
                result.append(' '.join(l.strip() for l in combined))
            else:
                result.append(current)
                i += 1
        return result
    
    def _is_section_start(self, line: str) -> bool:
        """判断是否是章节开始"""
        line = line.strip()
        patterns = [
            r'^[一二三四五六七八九十]+[、\.]\s*\S',
            r'^第[一二三四五六七八九十百]+[章节部分]\s*',
            r'^\d+\.\d+\s+',
        ]
        return any(re.match(p, line) for p in patterns)
