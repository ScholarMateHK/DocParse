"""
数据模型定义 - Pydantic Schemas
"""
from typing import Optional, List, Literal
from datetime import datetime
from pydantic import BaseModel, Field
from enum import Enum


class BusinessLine(str, Enum):
    """业务线枚举"""
    SEMANTIC_CHECK = "semantic_check"      # 语义查重
    PAPER_WRITING = "paper_writing"        # 论文/申请书写作
    EDIT_SUGGESTION = "edit_suggestion"    # 编辑建议
    AI_REVIEW = "ai_review"                # AI评审


class ParseVersion(str, Enum):
    """解析版本"""
    V1 = "v1"
    V2 = "v2"


class TaskStatus(str, Enum):
    """任务状态枚举"""
    PENDING = "pending"          # 等待处理
    PROCESSING = "processing"    # 处理中
    COMPLETED = "completed"      # 已完成
    FAILED = "failed"            # 失败


class ChunkMethod(str, Enum):
    """切分方式枚举"""
    SLIDING = "sliding"    # 滑动窗口切分
    SEMANTIC = "semantic"  # 语义切分（使用LLM）


class ParseRequest(BaseModel):
    """解析请求模型"""
    business_line: BusinessLine = Field(
        default=BusinessLine.SEMANTIC_CHECK,
        description="来源业务线"
    )
    version: ParseVersion = Field(
        default=ParseVersion.V1,
        description="指定使用v1还是v2逻辑"
    )
    text: Optional[str] = Field(
        default=None,
        description="纯文本输入 (可选)"
    )
    chunk_size: Optional[int] = Field(
        default=None,
        description="二次切分的块大小(字符数)，若传入则对已打标签的语义段落进行二次切分"
    )
    overlap: Optional[int] = Field(
        default=None,
        description="切分重叠区间(字符数)，仅在chunk_size传入时生效"
    )
    chunk_method: ChunkMethod = Field(
        default=ChunkMethod.SLIDING,
        description="切分方式: sliding(滑动窗口), semantic(语义切分)"
    )


class Chunk(BaseModel):
    """二次切分后的文本块"""
    chunk_id: int = Field(description="块ID")
    segment_id: int = Field(description="所属段落ID")
    content: str = Field(description="块内容")
    tag: str = Field(description="继承自段落的标签")
    start_pos: int = Field(description="在原段落中的起始位置")
    end_pos: int = Field(description="在原段落中的结束位置")


class Segment(BaseModel):
    """解析后的段落"""
    segment_id: int = Field(description="段落ID")
    content: str = Field(description="段落原文")
    tag: str = Field(description="预测标签")
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="置信度分数"
    )
    pageIdx: Optional[int] = Field(
        default=None,
        description="段落所在页码(仅文件上传且可获取页码时返回，从1开始)"
    )
    chunks: Optional[List[Chunk]] = Field(
        default=None,
        description="二次切分后的块列表(仅在传入chunk_size时返回)"
    )


class ParseResponse(BaseModel):
    """解析响应模型"""
    status: str = Field(default="success", description="处理状态")
    doc_id: str = Field(description="文档唯一标识")
    title: Optional[str] = Field(
        default=None,
        description="文档标题(可能为空)"
    )
    abstract: Optional[str] = Field(
        default=None,
        description="文档摘要(若原文无摘要则由LLM生成)"
    )
    segments: List[Segment] = Field(
        default_factory=list,
        description="解析后的段落列表"
    )
    error_message: Optional[str] = Field(
        default=None,
        description="错误信息(如有)"
    )
    chunk_info: Optional[dict] = Field(
        default=None,
        description="切分配置信息(仅在传入chunk_size时返回)"
    )


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str = "healthy"
    version: str = "1.0.0"
    service: str = "学术语料解析模块"


# ============== 异步任务相关模型 ==============

class TaskSubmitResponse(BaseModel):
    """任务提交响应"""
    task_id: str = Field(description="任务唯一标识")
    status: TaskStatus = Field(default=TaskStatus.PENDING, description="任务状态")
    message: str = Field(default="任务已提交", description="提示信息")
    created_at: datetime = Field(description="任务创建时间")


class TaskStatusResponse(BaseModel):
    """任务状态查询响应"""
    task_id: str = Field(description="任务唯一标识")
    status: TaskStatus = Field(description="任务状态")
    progress: Optional[float] = Field(default=None, description="处理进度 0-100")
    created_at: datetime = Field(description="任务创建时间")
    started_at: Optional[datetime] = Field(default=None, description="开始处理时间")
    completed_at: Optional[datetime] = Field(default=None, description="完成时间")
    last_activity: Optional[datetime] = Field(default=None, description="最近心跳时间")
    error_message: Optional[str] = Field(default=None, description="错误信息")


class TaskResultResponse(BaseModel):
    """任务结果响应"""
    task_id: str = Field(description="任务唯一标识")
    status: TaskStatus = Field(description="任务状态")
    result: Optional[ParseResponse] = Field(default=None, description="解析结果")
    created_at: datetime = Field(description="任务创建时间")
    completed_at: Optional[datetime] = Field(default=None, description="完成时间")
    error_message: Optional[str] = Field(default=None, description="错误信息")

