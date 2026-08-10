"""
文本切分器 - 对已打标签的语义段落进行二次切分
支持两种切分方式：
1. 滑动窗口切分（sliding）：按固定大小切分，使用overlap保证上下文连贯
2. 语义切分（semantic）：利用LLM按语义进行二次切分
"""
import re
import json
from typing import List, Optional, Literal
from dataclasses import dataclass
from openai import OpenAI

from ..config import settings, DEFAULT_CHUNK_SIZE, DEFAULT_CHUNK_OVERLAP


@dataclass
class ChunkResult:
    """切分结果"""
    chunk_id: int
    segment_id: int
    content: str
    tag: str
    start_pos: int
    end_pos: int


class TextChunker:
    """文本切分器"""
    
    def __init__(self, model: str = None):
        """
        初始化切分器
        
        Args:
            model: LLM模型名称（仅语义切分时使用）
        """
        self.model = model if model else settings.LLM_MODEL
        self._client = None  # 延迟加载
    
    @property
    def client(self):
        """延迟加载LLM客户端"""
        if self._client is None:
            from httpx import Timeout
            self._client = OpenAI(
                api_key=settings.require_llm_api_key(),
                base_url=settings.LLM_BASE_URL,
                timeout=Timeout(settings.LLM_TIMEOUT, connect=10.0),
                max_retries=settings.LLM_MAX_RETRIES,
            )
        return self._client
    
    def chunk_segment(
        self,
        content: str,
        segment_id: int,
        tag: str,
        chunk_size: int,
        overlap: int = 0,
        method: Literal["sliding", "semantic"] = "sliding"
    ) -> List[ChunkResult]:
        """
        对单个段落进行切分
        
        Args:
            content: 段落内容
            segment_id: 段落ID
            tag: 段落标签（切分后的chunk将继承此标签）
            chunk_size: 切分块大小（字符数）
            overlap: 重叠区间（字符数）
            method: 切分方式 - "sliding"(滑动窗口) 或 "semantic"(语义切分)
            
        Returns:
            List[ChunkResult]: 切分后的块列表
        """
        if not content or not content.strip():
            return []
        
        # 如果内容长度小于chunk_size，无需切分
        if len(content) <= chunk_size:
            return [ChunkResult(
                chunk_id=1,
                segment_id=segment_id,
                content=content,
                tag=tag,
                start_pos=0,
                end_pos=len(content)
            )]
        
        if method == "semantic":
            return self._semantic_chunk(content, segment_id, tag, chunk_size)
        else:
            return self._sliding_window_chunk(content, segment_id, tag, chunk_size, overlap)
    
    def _sliding_window_chunk(
        self,
        content: str,
        segment_id: int,
        tag: str,
        chunk_size: int,
        overlap: int
    ) -> List[ChunkResult]:
        """
        滑动窗口切分
        
        Args:
            content: 段落内容
            segment_id: 段落ID
            tag: 段落标签
            chunk_size: 切分块大小
            overlap: 重叠区间
            
        Returns:
            List[ChunkResult]: 切分后的块列表
        """
        chunks = []
        chunk_id = 1
        start = 0
        content_length = len(content)
        
        # 确保overlap不超过chunk_size的一半
        overlap = min(overlap, chunk_size // 2)
        
        # 步长 = chunk_size - overlap
        step = max(chunk_size - overlap, 1)
        
        while start < content_length:
            # 计算本次切分的结束位置
            end = min(start + chunk_size, content_length)
            
            # 尝试在句子边界处切分（优化切分效果）
            if end < content_length:
                # 向前查找句子结束符
                adjusted_end = self._find_sentence_boundary(content, start, end)
                if adjusted_end > start + chunk_size // 2:  # 确保切分块不会太小
                    end = adjusted_end
            
            chunk_content = content[start:end]
            
            chunks.append(ChunkResult(
                chunk_id=chunk_id,
                segment_id=segment_id,
                content=chunk_content.strip(),
                tag=tag,
                start_pos=start,
                end_pos=end
            ))
            
            chunk_id += 1
            
            # 如果已经到达末尾，退出循环
            if end >= content_length:
                break
            
            # 计算下一个起始位置（考虑重叠）
            start = end - overlap if overlap > 0 else end
        
        return chunks
    
    def _find_sentence_boundary(self, content: str, start: int, end: int) -> int:
        """
        在指定范围内查找句子边界
        
        Args:
            content: 完整内容
            start: 搜索起始位置
            end: 搜索结束位置
            
        Returns:
            int: 找到的句子边界位置，如果没找到则返回原end
        """
        # 句子结束符
        terminators = ('。', '！', '？', '；', '.', '!', '?', '\n')
        
        # 从end位置向前搜索最近的句子结束符
        search_start = max(start + (end - start) // 2, start)  # 至少保留一半的内容
        
        for i in range(end - 1, search_start - 1, -1):
            if content[i] in terminators:
                return i + 1
        
        return end
    
    def _semantic_chunk(
        self,
        content: str,
        segment_id: int,
        tag: str,
        chunk_size: int
    ) -> List[ChunkResult]:
        """
        语义切分 - 使用LLM进行智能切分
        
        Args:
            content: 段落内容
            segment_id: 段落ID
            tag: 段落标签
            chunk_size: 目标切分块大小（字符数）
            
        Returns:
            List[ChunkResult]: 切分后的块列表
        """
        # 估算需要切分成几块
        estimated_chunks = max(2, len(content) // chunk_size)
        
        prompt = self._build_semantic_chunk_prompt(content, chunk_size, estimated_chunks)
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self._get_semantic_chunk_system_prompt()},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=4000
            )
            
            result_text = response.choices[0].message.content.strip()
            return self._parse_semantic_chunk_result(result_text, content, segment_id, tag)
            
        except Exception as e:
            print(f"语义切分失败: {e}，回退到滑动窗口切分")
            # 失败时回退到滑动窗口切分
            return self._sliding_window_chunk(content, segment_id, tag, chunk_size, chunk_size // 10)
    
    def _get_semantic_chunk_system_prompt(self) -> str:
        """获取语义切分的系统提示词"""
        return """你是一个专业的文本处理专家。你的任务是将给定的文本按照语义进行切分，
确保每个切分块都是语义完整的单元，同时尽量接近目标长度。

切分原则：
1. 保持语义完整性：每个切分块应该是一个完整的语义单元
2. 不要在句子中间切分
3. 相关的内容尽量放在同一个块中
4. 尽量接近目标长度，但语义完整性优先

请按照JSON数组格式输出切分结果：
[
  {"id": 1, "content": "第一块内容..."},
  {"id": 2, "content": "第二块内容..."}
]

注意：
- 必须保留原文的所有内容，不要遗漏或修改
- 不要添加任何原文没有的内容
- 只输出JSON数组，不要输出其他内容"""

    def _build_semantic_chunk_prompt(
        self,
        content: str,
        chunk_size: int,
        estimated_chunks: int
    ) -> str:
        """构建语义切分的用户提示词"""
        return f"""请将以下文本按照语义切分成大约 {estimated_chunks} 个块，每个块的目标长度约为 {chunk_size} 字符：

---文本开始---
{content}
---文本结束---

请以JSON数组格式输出切分结果。"""

    def _parse_semantic_chunk_result(
        self,
        result_text: str,
        original_content: str,
        segment_id: int,
        tag: str
    ) -> List[ChunkResult]:
        """解析语义切分的LLM返回结果"""
        chunks = []
        
        try:
            # 提取JSON数组
            json_match = re.search(r'\[[\s\S]*\]', result_text)
            if json_match:
                parsed = json.loads(json_match.group())
                
                if isinstance(parsed, list):
                    current_pos = 0
                    for i, item in enumerate(parsed):
                        chunk_content = item.get('content', '').strip()
                        if not chunk_content:
                            continue
                        
                        # 在原文中查找这个块的位置
                        start_pos = original_content.find(chunk_content[:50], current_pos)
                        if start_pos == -1:
                            start_pos = current_pos
                        
                        end_pos = start_pos + len(chunk_content)
                        current_pos = end_pos
                        
                        chunks.append(ChunkResult(
                            chunk_id=i + 1,
                            segment_id=segment_id,
                            content=chunk_content,
                            tag=tag,
                            start_pos=start_pos,
                            end_pos=end_pos
                        ))
        
        except (json.JSONDecodeError, ValueError) as e:
            print(f"语义切分结果解析失败: {e}")
        
        # 如果解析失败或结果为空，返回原内容
        if not chunks:
            chunks.append(ChunkResult(
                chunk_id=1,
                segment_id=segment_id,
                content=original_content,
                tag=tag,
                start_pos=0,
                end_pos=len(original_content)
            ))
        
        return chunks
    
    def chunk_segments(
        self,
        segments: List[dict],
        chunk_size: int,
        overlap: int = 0,
        method: Literal["sliding", "semantic"] = "sliding"
    ) -> List[dict]:
        """
        对多个段落进行批量切分
        
        Args:
            segments: 段落列表，每个段落包含 segment_id, content, tag, confidence
            chunk_size: 切分块大小
            overlap: 重叠区间（仅滑动窗口模式有效）
            method: 切分方式
            
        Returns:
            List[dict]: 包含chunks的段落列表
        """
        results = []
        global_chunk_id = 1  # 全局chunk ID计数器
        
        for segment in segments:
            segment_id = segment.get('segment_id', 0)
            content = segment.get('content', '')
            tag = segment.get('tag', '其他')
            confidence = segment.get('confidence', 0.0)
            
            # 对段落进行切分
            chunk_results = self.chunk_segment(
                content=content,
                segment_id=segment_id,
                tag=tag,
                chunk_size=chunk_size,
                overlap=overlap,
                method=method
            )
            
            # 转换为字典格式
            chunks = []
            for chunk in chunk_results:
                chunks.append({
                    'chunk_id': global_chunk_id,
                    'segment_id': chunk.segment_id,
                    'content': chunk.content,
                    'tag': chunk.tag,
                    'start_pos': chunk.start_pos,
                    'end_pos': chunk.end_pos
                })
                global_chunk_id += 1
            
            # 构建结果
            result = {
                'segment_id': segment_id,
                'content': content,
                'tag': tag,
                'confidence': confidence,
                'chunks': chunks if len(chunks) > 1 or chunk_size else None
            }
            results.append(result)
        
        return results
