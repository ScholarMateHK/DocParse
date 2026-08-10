"""
API路由定义
符合需求文档5.1节的接口规范

V1版本功能：
- 13类标签体系（包含标题和摘要）
- 标题识别（可为空）
- 摘要识别与自动生成
- 可选的二次切分功能（chunk_size + overlap）
"""
import asyncio
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, Form, HTTPException

from ..models.schemas import (
    ParseResponse,
    HealthResponse,
    BusinessLine,
    ParseVersion,
    TaskStatus,
    TaskSubmitResponse,
    TaskStatusResponse,
    TaskResultResponse,
    ChunkMethod
)
from ..services.document_parser import DocumentParser
from ..services.task_manager import task_manager
from ..config import settings, V1_CLASSIFICATION_TAGS, V1_TAG_DESCRIPTIONS

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """健康检查接口"""
    return HealthResponse(
        status="healthy",
        version=settings.APP_VERSION,
        service=settings.APP_NAME
    )


@router.post("/api/v1/parse_document", response_model=ParseResponse)
async def parse_document(
    business_line: str = Form(
        default="semantic_check",
        description="来源业务线: semantic_check(语义查重), paper_writing(论文写作), edit_suggestion(编辑建议), ai_review(AI评审)"
    ),
    version: str = Form(
        default="v1",
        description="指定使用v1还是v2逻辑"
    ),
    process_mode: str = Form(
        default="separate",
        description="处理模式: separate(分离模式，分段和分类分开调用，默认), unified(统一模式，一次LLM调用完成分段+分类)"
    ),
    segment_mode: str = Form(
        default="rule",
        description="分段模式(仅separate模式有效): rule(规则分段，快速), semantic(语义分段，基于LLM)"
    ),
    chunk_size: Optional[int] = Form(
        default=None,
        description="二次切分的块大小(字符数)，若传入则对已打标签的语义段落进行二次切分"
    ),
    overlap: Optional[int] = Form(
        default=None,
        description="切分重叠区间(字符数)，仅在chunk_size传入时生效，用于保证上下文语义连贯"
    ),
    chunk_method: str = Form(
        default="sliding",
        description="切分方式: sliding(滑动窗口切分), semantic(语义切分，使用LLM)"
    ),
    text: str = Form(
        default="",
        description="纯文本输入 (可选，与file二选一或同时提供)"
    ),
    file: UploadFile = File(
        default=None,
        description="文件流 (可选，支持 .txt, .pdf, .doc, .docx)"
    )
):
    """
    解析学术文档 - 统一接口
    
    ## 接口说明
    
    根据需求文档5.1节规范，支持两种输入方式（可同时提供）：
    
    1. **纯文本输入** (text参数): 用户直接粘贴的字符串
    2. **文件上传** (file参数): 支持 .txt, .pdf, .doc, .docx 格式
    
    当同时提供text和file时，优先处理file。
    
    ## 业务线
    - `semantic_check`: 语义查重
    - `paper_writing`: 论文/申请书写作
    - `edit_suggestion`: 编辑建议
    - `ai_review`: AI评审
    
    ## 分类标签体系（13类）
    1. 标题
    2. 摘要
    3. 项目研究意义
    4. 国内外研究现状及发展动态分析
    5. 科学意义与应用前景
    6. 项目的研究内容
    7. 研究目标
    8. 拟解决的关键科学问题
    9. 研究方法
    10. 技术路线
    11. 关键技术
    12. 本项目的特色与创新之处
    13. 其他
    
    ## 二次切分功能
    
    若传入 `chunk_size` 参数，将对已打标签的语义段落进行二次切分：
    - `chunk_size`: 切分块大小（字符数）
    - `overlap`: 重叠区间（字符数），用于保证上下文连贯
    - `chunk_method`: 切分方式
      - `sliding`: 滑动窗口切分
      - `semantic`: 语义切分（使用LLM）
    
    ## 返回格式
    
    ```json
    {
      "status": "success",
      "doc_id": "uuid_123456",
      "title": "项目标题（可能为空）",
      "abstract": "摘要内容（若原文无摘要则自动生成）",
      "segments": [
        {
          "segment_id": 1,
          "content": "段落原文...",
          "tag": "研究目标",
          "confidence": 0.95,
          "chunks": [
            {
              "chunk_id": 1,
              "segment_id": 1,
              "content": "切分后的内容...",
              "tag": "研究目标",
              "start_pos": 0,
              "end_pos": 500
            }
          ]
        }
      ],
      "chunk_info": {
        "chunk_size": 500,
        "overlap": 50,
        "method": "sliding"
      }
    }
    ```
    """
    # 验证业务线
    try:
        business_line_enum = BusinessLine(business_line)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"无效的业务线: {business_line}. 支持: {[b.value for b in BusinessLine]}"
        )
    
    # 验证版本
    try:
        version_enum = ParseVersion(version)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"无效的版本: {version}. 支持: v1, v2"
        )
    
    # V2版本暂未实现
    if version_enum == ParseVersion.V2:
        raise HTTPException(
            status_code=501,
            detail="V2版本尚未实现，请使用v1"
        )
    
    # 验证处理模式
    if process_mode not in ("unified", "separate"):
        raise HTTPException(
            status_code=400,
            detail=f"无效的处理模式: {process_mode}. 支持: unified(统一模式), separate(分离模式)"
        )
    
    # 验证分段模式（仅在 separate 模式下有效）
    if segment_mode not in ("rule", "semantic"):
        raise HTTPException(
            status_code=400,
            detail=f"无效的分段模式: {segment_mode}. 支持: rule(规则分段), semantic(语义分段)"
        )
    
    # 验证切分方式
    if chunk_method not in ("sliding", "semantic"):
        raise HTTPException(
            status_code=400,
            detail=f"无效的切分方式: {chunk_method}. 支持: sliding(滑动窗口), semantic(语义切分)"
        )
    
    # 验证chunk参数
    if chunk_size is not None:
        if chunk_size < 50:
            raise HTTPException(
                status_code=400,
                detail="chunk_size 不能小于 50"
            )
        if overlap is not None and overlap < 0:
            raise HTTPException(
                status_code=400,
                detail="overlap 不能为负数"
            )
        if overlap is not None and overlap >= chunk_size:
            raise HTTPException(
                status_code=400,
                detail="overlap 必须小于 chunk_size"
            )
    
    # 必须提供text或file之一
    has_text = text and text.strip()
    has_file = file and file.filename
    if not has_text and not has_file:
        raise HTTPException(
            status_code=400,
            detail="必须提供text参数或上传file文件（至少提供其一）"
        )
    
    try:
        request_parser = DocumentParser(
            segment_mode=segment_mode,
            process_mode=process_mode,
        )

        if has_file:
            filename = file.filename
            if not any(filename.lower().endswith(ext) for ext in settings.ALLOWED_EXTENSIONS):
                raise HTTPException(
                    status_code=400,
                    detail=f"不支持的文件格式. 支持: {list(settings.ALLOWED_EXTENSIONS)}"
                )
            
            file_content = await file.read()
            
            if len(file_content) > settings.MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=400,
                    detail=f"文件过大. 最大支持: {settings.MAX_FILE_SIZE // (1024*1024)}MB"
                )
            
            response = await asyncio.to_thread(
                request_parser.parse,
                file_content=file_content,
                filename=filename,
                chunk_size=chunk_size,
                overlap=overlap,
                chunk_method=chunk_method,
            )
        elif has_text:
            response = await asyncio.to_thread(
                request_parser.parse,
                text=text.strip(),
                chunk_size=chunk_size,
                overlap=overlap,
                chunk_method=chunk_method,
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="请提供有效的text内容或上传file文件"
            )
        
        return response
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("解析错误: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"解析失败: {str(e)}")


@router.get("/api/v1/tags")
async def get_classification_tags():
    """
    获取所有分类标签
    
    返回V1版本支持的所有分类标签（13类，侧重项目申请书）
    """
    return {
        "version": "v1",
        "tags": V1_CLASSIFICATION_TAGS,
        "description": "V1版本标签体系（13类，侧重项目申请书，包含标题和摘要）",
        "tag_descriptions": V1_TAG_DESCRIPTIONS,
        "notes": {
            "标题": "标题可能为空，若文档中未找到标题则留空",
            "摘要": "若文档中未找到摘要，系统将自动调用LLM生成约500字的摘要"
        }
    }


@router.get("/api/v1/supported_formats")
async def get_supported_formats():
    """
    获取支持的文件格式
    
    PDF 和 Word 文件优先使用阿里云文档智能，调用不可用时回退本地提取。
    """
    return {
        "supported_formats": sorted(settings.ALLOWED_EXTENSIONS),
        "max_file_size_mb": settings.MAX_FILE_SIZE // (1024 * 1024),
        "document_parsing_strategy": (
            "优先使用阿里云文档智能处理复杂排版；未配置或调用失败时，"
            "回退到本地文本提取"
        ),
        "notes": {
            ".txt": "纯文本文件，支持UTF-8、GBK等多种编码，直接读取",
            ".pdf": "云端文档智能优先；本地使用 pypdf 回退",
            ".doc": "云端文档智能优先；本地可使用 antiword 或 catdoc 回退",
            ".docx": "云端文档智能优先；本地使用 python-docx 回退",
        },
        "cloud_service": {
            "name": "Alibaba Cloud Document Mind",
            "required_environment_variables": [
                "DOCMIND_ACCESS_KEY_ID",
                "DOCMIND_ACCESS_KEY_SECRET",
            ],
        },
        "local_fallbacks": {
            "pdf": "pypdf",
            "docx": "python-docx",
            "doc": "antiword 或 catdoc（可选系统工具）",
        },
    }


# ============== 异步任务接口 ==============

@router.post("/api/v1/parse_document/async", response_model=TaskSubmitResponse)
async def submit_parse_task(
    business_line: str = Form(
        default="semantic_check",
        description="来源业务线: semantic_check(语义查重), paper_writing(论文写作), edit_suggestion(编辑建议), ai_review(AI评审)"
    ),
    version: str = Form(
        default="v1",
        description="指定使用v1还是v2逻辑"
    ),
    process_mode: str = Form(
        default="separate",
        description="处理模式: separate(分离模式，分段和分类分开调用，默认), unified(统一模式，一次LLM调用完成分段+分类)"
    ),
    segment_mode: str = Form(
        default="rule",
        description="分段模式(仅separate模式有效): rule(规则分段，快速), semantic(语义分段，基于LLM)"
    ),
    chunk_size: Optional[int] = Form(
        default=None,
        description="二次切分的块大小(字符数)，若传入则对已打标签的语义段落进行二次切分"
    ),
    overlap: Optional[int] = Form(
        default=None,
        description="切分重叠区间(字符数)，仅在chunk_size传入时生效"
    ),
    chunk_method: str = Form(
        default="sliding",
        description="切分方式: sliding(滑动窗口切分), semantic(语义切分)"
    ),
    text: str = Form(
        default="",
        description="纯文本输入 (可选，与file二选一或同时提供)"
    ),
    file: UploadFile = File(
        default=None,
        description="文件流 (可选，支持 .txt, .pdf, .doc, .docx)"
    )
):
    """
    异步提交解析任务
    
    ## 接口说明
    
    与同步接口 `/api/v1/parse_document` 参数相同，但会立即返回任务ID，
    而不是等待解析完成。适用于大文件或需要OCR的文档处理。
    
    ## 使用流程
    
    1. 调用此接口提交任务，获取 `task_id`
    2. 调用 `GET /api/v1/tasks/status/{task_id}` 查询任务状态
    3. 当状态为 `completed` 时，调用 `GET /api/v1/tasks/result/{task_id}` 获取结果
    
    ## 返回格式
    
    ```json
    {
      "task_id": "uuid-xxx-xxx",
      "status": "pending",
      "message": "任务已提交",
      "created_at": "2026-01-12T10:30:00"
    }
    ```
    """
    # 验证业务线
    try:
        business_line_enum = BusinessLine(business_line)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"无效的业务线: {business_line}. 支持: {[b.value for b in BusinessLine]}"
        )
    
    # 验证版本
    try:
        version_enum = ParseVersion(version)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"无效的版本: {version}. 支持: v1, v2"
        )
    
    # V2版本暂未实现
    if version_enum == ParseVersion.V2:
        raise HTTPException(
            status_code=501,
            detail="V2版本尚未实现，请使用v1"
        )
    
    # 验证处理模式
    if process_mode not in ("unified", "separate"):
        raise HTTPException(
            status_code=400,
            detail=f"无效的处理模式: {process_mode}. 支持: unified(统一模式), separate(分离模式)"
        )
    
    # 验证分段模式
    if segment_mode not in ("rule", "semantic"):
        raise HTTPException(
            status_code=400,
            detail=f"无效的分段模式: {segment_mode}. 支持: rule(规则分段), semantic(语义分段)"
        )
    
    # 验证切分方式
    if chunk_method not in ("sliding", "semantic"):
        raise HTTPException(
            status_code=400,
            detail=f"无效的切分方式: {chunk_method}. 支持: sliding(滑动窗口), semantic(语义切分)"
        )
    
    # 验证chunk参数
    if chunk_size is not None:
        if chunk_size < 50:
            raise HTTPException(
                status_code=400,
                detail="chunk_size 不能小于 50"
            )
        if overlap is not None and overlap < 0:
            raise HTTPException(
                status_code=400,
                detail="overlap 不能为负数"
            )
        if overlap is not None and overlap >= chunk_size:
            raise HTTPException(
                status_code=400,
                detail="overlap 必须小于 chunk_size"
            )
    
    # 必须提供text或file之一
    has_text = text and text.strip()
    has_file = file and file.filename
    if not has_text and not has_file:
        raise HTTPException(
            status_code=400,
            detail="必须提供text参数或上传file文件（至少提供其一）"
        )
    
    try:
        file_content = None
        filename = None
        
        # 处理文件上传
        if file and file.filename:
            filename = file.filename
            if not any(filename.lower().endswith(ext) for ext in settings.ALLOWED_EXTENSIONS):
                raise HTTPException(
                    status_code=400,
                    detail=f"不支持的文件格式. 支持: {list(settings.ALLOWED_EXTENSIONS)}"
                )
            
            file_content = await file.read()
            
            if len(file_content) > settings.MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=400,
                    detail=f"文件过大. 最大支持: {settings.MAX_FILE_SIZE // (1024*1024)}MB"
                )
        
        # 提交任务
        task = task_manager.submit_task(
            text=text.strip() if has_text and not file_content else None,
            file_content=file_content,
            filename=filename,
            process_mode=process_mode,
            segment_mode=segment_mode,
            chunk_size=chunk_size,
            overlap=overlap,
            chunk_method=chunk_method
        )
        
        return TaskSubmitResponse(
            task_id=task.task_id,
            status=task.status,
            message="任务已提交，请通过任务ID查询结果",
            created_at=task.created_at
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"任务提交失败: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"任务提交失败: {str(e)}")


@router.get("/api/v1/tasks/status/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """
    查询任务状态
    
    ## 任务状态说明
    
    - `pending`: 任务等待处理
    - `processing`: 任务正在处理中
    - `completed`: 任务处理完成
    - `failed`: 任务处理失败
    
    ## 返回格式
    
    ```json
    {
      "task_id": "uuid-xxx-xxx",
      "status": "processing",
      "progress": 50.0,
      "created_at": "2026-01-12T10:30:00",
      "started_at": "2026-01-12T10:30:01",
      "completed_at": null,
      "last_activity": "2026-01-12T10:31:00",
      "error_message": null
    }
    ```
    """
    task_status = task_manager.get_task_status(task_id)
    
    if not task_status:
        raise HTTPException(
            status_code=404,
            detail=f"任务不存在: {task_id}"
        )
    
    return TaskStatusResponse(**task_status)


@router.get("/api/v1/tasks/result/{task_id}", response_model=TaskResultResponse)
async def get_task_result(task_id: str):
    """
    获取任务结果
    
    ## 说明
    
    只有当任务状态为 `completed` 或 `failed` 时，才会返回结果。
    如果任务仍在处理中，result 字段为 null。
    
    ## 返回格式
    
    ```json
    {
      "task_id": "uuid-xxx-xxx",
      "status": "completed",
      "result": {
        "status": "success",
        "doc_id": "uuid-yyy-yyy",
        "segments": [...]
      },
      "created_at": "2026-01-12T10:30:00",
      "completed_at": "2026-01-12T10:30:15",
      "error_message": null
    }
    ```
    """
    task_result = task_manager.get_task_result(task_id)
    
    if not task_result:
        raise HTTPException(
            status_code=404,
            detail=f"任务不存在: {task_id}"
        )
    
    return TaskResultResponse(**task_result)


@router.get("/api/v1/tasks")
async def list_tasks(limit: int = 20):
    """
    列出最近的任务
    
    ## 参数
    
    - `limit`: 返回数量限制，默认20，最大100
    
    ## 返回格式
    
    ```json
    {
      "tasks": [
        {
          "task_id": "uuid-xxx",
          "status": "completed",
          "progress": 100.0,
          "created_at": "2026-01-12T10:30:00",
          "completed_at": "2026-01-12T10:30:15"
        }
      ],
      "total": 5
    }
    ```
    """
    limit = min(max(1, limit), 100)
    tasks = task_manager.list_tasks(limit=limit)
    
    return {
        "tasks": tasks,
        "total": len(tasks)
    }
