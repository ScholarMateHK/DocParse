"""
语义分段器 - 基于 LLM 的真正语义分段
使用大语言模型理解文本内容，进行语义级别的段落划分

遵循语义聚合原则：
- 规则 A (冒号换行聚合)：冒号后的换行内容合并入同一段
- 规则 B (列表项汇聚)：整组列表项聚合为一个语义分段
- 规则 C (跨页逻辑补偿)：未结束的句子与下一行拼接
"""
import json
import re
from typing import List, Optional, Tuple
from openai import OpenAI

from ..config import settings


class SemanticSegmenter:
    """基于LLM的语义分段器"""
    
    # 单次处理的最大字符数（避免超出 token 限制）
    MAX_CHUNK_SIZE = 6000
    # 预分段的最大句子数（用于批量处理）
    MAX_SENTENCES_PER_BATCH = 30
    
    def __init__(self):
        """初始化LLM客户端"""
        from httpx import Timeout
        self.client = OpenAI(
            api_key=settings.require_llm_api_key(),
            base_url=settings.LLM_BASE_URL,
            timeout=Timeout(settings.LLM_TIMEOUT, connect=10.0),
            max_retries=settings.LLM_MAX_RETRIES,
        )
        self.model = settings.LLM_MODEL
    
    def segment(self, text: str) -> List[str]:
        """
        对文本进行语义分段
        
        Args:
            text: 待分段的完整文本
            
        Returns:
            List[str]: 语义分段后的段落列表
        """
        if not text or not text.strip():
            return []
        
        text = text.strip()
        
        # 先应用语义聚合规则（冒号聚合、列表聚合、跨页补偿）
        text = self._apply_semantic_aggregation_rules(text)
        
        # 如果文本很短，直接返回
        if len(text) < 200:
            return [text]
        
        # 预分段：先按自然边界切分成句子/小段（保护聚合后的结构）
        pre_segments = self._pre_segment(text)
        
        # 如果预分段数量很少，直接让 LLM 处理
        if len(pre_segments) <= self.MAX_SENTENCES_PER_BATCH:
            return self._llm_segment(pre_segments)
        
        # 分批处理长文本
        return self._batch_segment(pre_segments)
    
    # ==================== 语义聚合规则 ====================
    
    def _apply_semantic_aggregation_rules(self, text: str) -> str:
        """
        应用所有语义聚合规则
        """
        lines = text.split('\n')
        
        # 规则 C: 跨页逻辑补偿（先处理，确保句子完整）
        lines = self._apply_cross_page_compensation(lines)
        
        # 规则 A: 冒号换行聚合
        lines = self._apply_colon_aggregation(lines)
        
        # 规则 B: 列表项汇聚
        lines = self._apply_list_aggregation(lines)
        
        return '\n'.join(lines)
    
    def _is_list_item(self, line: str) -> bool:
        """检查是否是列表项"""
        line = line.strip()
        if not line:
            return False
        
        # 数字+点号：1. 2. 3. 或 1、2、3、
        if re.match(r'^\d+[\.、]\s*', line):
            return True
        # 括号数字：(1) (2) 或 （1）（2）
        if re.match(r'^[\(（]\d+[\)）]\s*', line):
            return True
        # 圆圈数字：① ② ③
        if re.match(r'^[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]\s*', line):
            return True
        # 中文序号：第一条、第二条
        if re.match(r'^第[一二三四五六七八九十百]+[条款项节章部分]?\s*', line):
            return True
        # 字母序号：a. b. c. 或 A. B. C.
        if re.match(r'^[a-zA-Z][\.、\)）]\s*', line):
            return True
        # 中文数字序号：一、二、三、
        if re.match(r'^[一二三四五六七八九十]+[、\.]\s*', line):
            return True
        # 破折号或bullet：- • ·
        if re.match(r'^[-•·]\s+', line):
            return True
        
        return False
    
    def _get_list_type(self, line: str) -> str:
        """获取列表项的类型标识"""
        line = line.strip()
        if re.match(r'^\d+[\.、]\s*', line):
            return 'num_dot'
        if re.match(r'^[\(（]\d+[\)）]\s*', line):
            return 'paren_num'
        if re.match(r'^[①②③④⑤⑥⑦⑧⑨⑩]\s*', line):
            return 'circle'
        if re.match(r'^第[一二三四五六七八九十百]+', line):
            return 'di_tiao'
        if re.match(r'^[一二三四五六七八九十]+[、\.]\s*', line):
            return 'cn_num'
        if re.match(r'^[a-zA-Z][\.、\)）]\s*', line):
            return 'letter'
        return 'other'
    
    def _is_new_paragraph_start(self, line: str) -> bool:
        """判断是否是新段落的开始"""
        line = line.strip()
        if not line:
            return False
        if self._is_list_item(line):
            return False
        # 中文标题特征
        if re.match(r'^[一二三四五六七八九十]+[、\.]\s*\S', line):
            return True
        if re.match(r'^第[一二三四五六七八九十百]+[章节部分条款]\s*', line):
            return True
        if re.match(r'^\d+\.\d+\s+', line):
            return True
        return False
    
    def _apply_colon_aggregation(self, lines: List[str]) -> List[str]:
        """规则 A: 冒号换行聚合"""
        if not lines:
            return lines
        
        result = []
        i = 0
        
        while i < len(lines):
            current_line = lines[i]
            
            if current_line.rstrip().endswith(('：', ':')):
                aggregated = [current_line]
                i += 1
                
                while i < len(lines):
                    next_line = lines[i]
                    if not next_line.strip():
                        break
                    if self._is_new_paragraph_start(next_line) and not self._is_list_item(next_line):
                        break
                    aggregated.append(next_line)
                    i += 1
                
                result.append('\n'.join(aggregated))
            else:
                result.append(current_line)
                i += 1
        
        return result
    
    def _apply_list_aggregation(self, lines: List[str]) -> List[str]:
        """规则 B: 列表项汇聚"""
        if not lines:
            return lines
        
        result = []
        i = 0
        
        while i < len(lines):
            line = lines[i]
            
            if self._is_list_item(line):
                list_type = self._get_list_type(line)
                list_items = [line]
                i += 1
                
                while i < len(lines):
                    next_line = lines[i]
                    
                    if not next_line.strip():
                        # 检查后续是否还有同类列表项
                        lookahead = i + 1
                        while lookahead < len(lines) and not lines[lookahead].strip():
                            lookahead += 1
                        
                        if lookahead < len(lines) and self._is_list_item(lines[lookahead]):
                            if self._get_list_type(lines[lookahead]) == list_type:
                                list_items.append(next_line)
                                i += 1
                                continue
                        break
                    
                    if self._is_list_item(next_line):
                        list_items.append(next_line)
                        i += 1
                    elif not self._is_new_paragraph_start(next_line):
                        # 列表项的续行
                        list_items.append(next_line)
                        i += 1
                    else:
                        break
                
                result.append('\n'.join(list_items))
            else:
                result.append(line)
                i += 1
        
        return result
    
    def _apply_cross_page_compensation(self, lines: List[str]) -> List[str]:
        """规则 C: 跨页逻辑补偿"""
        if not lines:
            return lines
        
        sentence_terminators = ('。', '！', '？', '；', '.', '!', '?', '…', '"', '"', '）', ')')
        page_markers = re.compile(r'^[-—]\s*\d+\s*[-—]$|^\d+$|^第\s*\d+\s*页$|^Page\s*\d+$', re.IGNORECASE)
        
        result = []
        i = 0
        
        while i < len(lines):
            current_line = lines[i]
            
            # 跳过页码标记
            if page_markers.match(current_line.strip()):
                i += 1
                continue
            
            current_stripped = current_line.rstrip()
            
            if current_stripped and not current_stripped.endswith(sentence_terminators):
                combined = [current_line]
                i += 1
                
                while i < len(lines):
                    next_line = lines[i]
                    
                    if page_markers.match(next_line.strip()):
                        i += 1
                        continue
                    
                    if not next_line.strip():
                        break
                    
                    if self._is_new_paragraph_start(next_line) or self._is_list_item(next_line):
                        break
                    
                    combined.append(next_line)
                    i += 1
                    
                    if next_line.rstrip().endswith(sentence_terminators):
                        break
                
                result.append(' '.join(line.strip() for line in combined))
            else:
                result.append(current_line)
                i += 1
        
        return result
    
    def _pre_segment(self, text: str) -> List[str]:
        """
        预分段：将文本切分成句子级别的小段
        保留原始结构信息，便于后续 LLM 分析
        """
        segments = []
        
        # 先按段落分割
        paragraphs = re.split(r'\n\s*\n', text)
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            
            # 按句子分割（保留标点）
            sentences = re.split(r'([。！？；\n])', para)
            
            current = ""
            for i in range(0, len(sentences), 2):
                sentence = sentences[i].strip()
                if not sentence:
                    continue
                # 加上标点符号
                if i + 1 < len(sentences):
                    sentence += sentences[i + 1]
                
                # 合并较短的句子，避免过于碎片化
                if len(current) + len(sentence) < 150:
                    current += sentence
                else:
                    if current:
                        segments.append(current.strip())
                    current = sentence
            
            if current.strip():
                segments.append(current.strip())
        
        return segments
    
    def _llm_segment(self, pre_segments: List[str]) -> List[str]:
        """
        使用 LLM 进行语义分段
        
        Args:
            pre_segments: 预分段后的句子列表
            
        Returns:
            List[str]: 语义分段后的段落列表
        """
        if not pre_segments:
            return []
        
        # 构建带编号的句子列表
        numbered_text = self._build_numbered_text(pre_segments)
        
        prompt = self._build_segmentation_prompt(numbered_text, len(pre_segments))
        
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
                temperature=0.1,
                max_tokens=2000
            )
            
            result_text = response.choices[0].message.content.strip()
            segments = self._parse_segmentation_result(result_text, pre_segments)
            
            return segments if segments else pre_segments
            
        except Exception as e:
            print(f"LLM语义分段失败: {e}")
            # 失败时返回简单合并的结果
            return self._fallback_merge(pre_segments)
    
    def _batch_segment(self, pre_segments: List[str]) -> List[str]:
        """
        分批处理长文本
        
        将预分段列表分成多个批次，分别让 LLM 处理，最后合并结果
        """
        all_segments = []
        
        # 按批次处理
        for i in range(0, len(pre_segments), self.MAX_SENTENCES_PER_BATCH):
            batch = pre_segments[i:i + self.MAX_SENTENCES_PER_BATCH]
            batch_segments = self._llm_segment(batch)
            all_segments.extend(batch_segments)
        
        # 处理批次边界的段落合并
        return self._merge_batch_boundaries(all_segments)
    
    def _merge_batch_boundaries(self, segments: List[str]) -> List[str]:
        """
        处理批次边界，合并可能被错误分开的段落
        """
        if len(segments) <= 1:
            return segments
        
        merged = [segments[0]]
        
        for i in range(1, len(segments)):
            current = segments[i]
            previous = merged[-1]
            
            # 如果前一段结尾和当前段开头看起来是连续的，尝试合并
            if self._should_merge_at_boundary(previous, current):
                merged[-1] = previous + "\n" + current
            else:
                merged.append(current)
        
        return merged
    
    def _should_merge_at_boundary(self, prev: str, curr: str) -> bool:
        """
        判断两个段落是否应该在边界处合并
        """
        # 如果前一段没有以完整句子结尾
        if not re.search(r'[。！？；\.\!\?]$', prev.strip()):
            return True
        
        # 如果当前段以小写字母或连接词开头
        curr_start = curr.strip()[:10] if curr.strip() else ""
        if re.match(r'^[a-z]', curr_start):
            return True
        if re.match(r'^(而且|并且|因此|所以|但是|然而|此外|另外|同时)', curr_start):
            return True
        
        # 如果两段都很短，可能是被错误分开的
        if len(prev) < 100 and len(curr) < 100:
            return True
        
        return False
    
    def _fallback_merge(self, pre_segments: List[str], min_length: int = 200) -> List[str]:
        """
        备用合并策略：当 LLM 调用失败时使用
        """
        if not pre_segments:
            return []
        
        merged = []
        current = ""
        
        for seg in pre_segments:
            if len(current) + len(seg) < min_length:
                current = (current + "\n" + seg).strip() if current else seg
            else:
                if current:
                    merged.append(current)
                current = seg
        
        if current:
            merged.append(current)
        
        return merged if merged else pre_segments
    
    def _build_numbered_text(self, segments: List[str]) -> str:
        """构建带编号的文本"""
        lines = []
        for i, seg in enumerate(segments, 1):
            lines.append(f"[{i}] {seg}")
        return "\n".join(lines)
    
    def _get_system_prompt(self) -> str:
        """获取系统提示词"""
        return """你是一个专业的文档分析专家，擅长理解文本的语义结构和逻辑关系。

你的任务是对给定的文本进行语义分段。语义分段的目标是将文本划分成语义完整、主题一致的段落。

【核心分段原则】

1. **冒号聚合原则**：以冒号（：或:）结尾的句子，其后的内容通常是对该句的补充说明或展开，应合并为同一段落。

2. **列表完整性原则**：识别到列表项（如 1. 2. 3.、(1)(2)(3)、①②③、第一条/第二条 等）时，必须将整组列表项聚合在同一段落中，禁止在列表中途切断。

3. **句子完整性原则**：如果一个句子没有以终止符（句号、感叹号、问号等）结尾，应与后续内容合并，确保语意完整。

4. **主题一致性原则**：同一主题的内容应归入同一段落，当话题明显转换时开始新段落。

5. **段落长度控制**：段落长度适中，避免过短（少于100字）或过长（超过2000字），但列表内容可以适当放宽长度限制。

你需要分析输入的编号句子，决定哪些句子应该合并成同一个段落。

请严格按照JSON格式输出分段方案：
{"segments": [[1,2,3], [4,5], [6,7,8,9], ...]}

其中每个子数组表示一个段落，包含该段落应包含的句子编号。
确保：
- 所有编号都被使用且只使用一次
- 编号在每个段落内按顺序排列
- 只输出JSON，不要输出其他内容"""
    
    def _build_segmentation_prompt(self, numbered_text: str, total_count: int) -> str:
        """构建分段提示词"""
        return f"""请对以下{total_count}个句子进行语义分段，将语义相关的句子合并为段落：

{numbered_text}

请以JSON格式输出分段方案，指明哪些句子应该合并为同一段落。"""
    
    def _parse_segmentation_result(
        self, 
        result_text: str, 
        pre_segments: List[str]
    ) -> List[str]:
        """
        解析 LLM 返回的分段结果
        
        Args:
            result_text: LLM 返回的文本
            pre_segments: 原始预分段列表
            
        Returns:
            List[str]: 合并后的段落列表
        """
        try:
            # 尝试提取 JSON
            json_match = re.search(r'\{[^{}]*"segments"[^{}]*\[[\s\S]*?\]\s*\}', result_text)
            if not json_match:
                # 尝试更宽松的匹配
                json_match = re.search(r'\{[\s\S]*\}', result_text)
            
            if not json_match:
                print(f"无法从LLM响应中提取JSON: {result_text[:200]}")
                return []
            
            result = json.loads(json_match.group())
            
            if "segments" not in result:
                print(f"LLM响应中没有segments字段: {result}")
                return []
            
            segment_groups = result["segments"]
            
            # 验证并构建段落
            segments = []
            used_indices = set()
            
            for group in segment_groups:
                if not isinstance(group, list):
                    continue
                
                # 收集该组的文本
                group_texts = []
                for idx in group:
                    # 转换为0-based索引
                    real_idx = idx - 1
                    if 0 <= real_idx < len(pre_segments) and real_idx not in used_indices:
                        group_texts.append(pre_segments[real_idx])
                        used_indices.add(real_idx)
                
                if group_texts:
                    segments.append("\n".join(group_texts))
            
            # 添加未被使用的句子
            for i, seg in enumerate(pre_segments):
                if i not in used_indices:
                    segments.append(seg)
            
            return segments
            
        except json.JSONDecodeError as e:
            print(f"JSON解析失败: {e}, 原文: {result_text[:200]}")
            return []
        except Exception as e:
            print(f"解析分段结果失败: {e}")
            return []


# 便捷函数
def semantic_segment(text: str) -> List[str]:
    """
    对文本进行语义分段的便捷函数
    
    Args:
        text: 待分段的文本
        
    Returns:
        List[str]: 分段后的段落列表
    """
    segmenter = SemanticSegmenter()
    return segmenter.segment(text)
