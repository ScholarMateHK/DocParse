"""
OCR服务 - 基于阿里云文档智能（Document Mind）API

替代本地 tesseract OCR，将文档解析卸载到云端：
- 无需本地安装 tesseract / poppler / libreoffice
- 不占用服务器 CPU / 内存
- 支持 PDF、Word、PPT、Excel、图片等多种格式
- 自动处理复杂排版（双栏、表格、图片穿插等）
"""
import io
import time
import logging
import threading
from typing import Optional, List, Tuple, Dict

from ..config import settings

logger = logging.getLogger(__name__)

try:
    from alibabacloud_docmind_api20220711.client import Client as DocMindClient
    from alibabacloud_tea_openapi import models as open_api_models
    from alibabacloud_docmind_api20220711 import models as docmind_models
    from alibabacloud_tea_util import models as util_models
    HAS_DOCMIND = True
except ImportError:
    HAS_DOCMIND = False

_docmind_semaphore = threading.Semaphore(settings.DOCMIND_MAX_CONCURRENT)

_SKIP_LAYOUT_TYPES = frozenset({
    "head", "head_image", "foot", "foot_image",
    "head_pagenum", "foot_pagenum", "page",
})


class OCRService:
    """基于阿里云文档智能的文档解析服务"""

    def __init__(self, language: str = None):
        self.language = language or settings.OCR_LANGUAGE
        self._client: Optional["DocMindClient"] = None
        if not HAS_DOCMIND:
            logger.warning(
                "alibabacloud-docmind-api SDK 未安装，请运行: "
                "pip install alibabacloud_docmind_api20220711"
            )

    @property
    def client(self) -> "DocMindClient":
        """懒加载 DocMind 客户端"""
        if self._client is None:
            if not HAS_DOCMIND:
                raise RuntimeError(
                    "alibabacloud-docmind-api SDK 未安装，无法进行文档解析"
                )
            access_key_id, access_key_secret = (
                settings.require_docmind_credentials()
            )
            config = open_api_models.Config(
                access_key_id=access_key_id,
                access_key_secret=access_key_secret,
            )
            config.endpoint = settings.DOCMIND_ENDPOINT
            self._client = DocMindClient(config)
        return self._client

    # ------------------------------------------------------------------
    # 公开接口（保持与旧版兼容，供 input_handler 调用）
    # ------------------------------------------------------------------

    def parse_file(self, content: bytes, filename: str) -> str:
        """
        解析任意格式文件，返回提取的纯文本。
        Semaphore 控制每个 worker 内最大并发数，防止超出 API 并发限制。

        支持：pdf, doc, docx, ppt, pptx, xls, xlsx, jpg, png 等
        """
        if not HAS_DOCMIND:
            raise RuntimeError(
                "alibabacloud-docmind-api SDK 未安装，无法进行文档解析"
            )

        acquired = _docmind_semaphore.acquire(timeout=settings.DOCMIND_TIMEOUT)
        if not acquired:
            raise RuntimeError("文档解析并发排队超时，请稍后重试")

        try:
            task_id = self._submit_job(content, filename)
            self._wait_for_completion(task_id)
            text = self._collect_text(task_id)

            if not text or not text.strip():
                raise RuntimeError("文档解析未提取到有效文本")

            return text
        finally:
            _docmind_semaphore.release()

    def parse_file_with_pages(
        self, content: bytes, filename: str
    ) -> Tuple[str, List[str]]:
        """解析文件并返回 (全文文本, 每页文本列表)。

        per_page_texts[0] 对应第 1 页，per_page_texts[1] 对应第 2 页，以此类推。
        """
        if not HAS_DOCMIND:
            raise RuntimeError(
                "alibabacloud-docmind-api SDK 未安装，无法进行文档解析"
            )

        acquired = _docmind_semaphore.acquire(timeout=settings.DOCMIND_TIMEOUT)
        if not acquired:
            raise RuntimeError("文档解析并发排队超时，请稍后重试")

        try:
            task_id = self._submit_job(content, filename)
            self._wait_for_completion(task_id)
            return self._collect_text_with_pages(task_id)
        finally:
            _docmind_semaphore.release()

    def ocr_pdf(self, pdf_content: bytes) -> str:
        return self.parse_file(pdf_content, "document.pdf")

    def ocr_docx(self, docx_content: bytes) -> str:
        return self.parse_file(docx_content, "document.docx")

    def ocr_doc(self, doc_content: bytes) -> str:
        return self.parse_file(doc_content, "document.doc")

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def _submit_job(self, content: bytes, filename: str) -> str:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

        request = docmind_models.SubmitDocParserJobAdvanceRequest(
            file_url_object=io.BytesIO(content),
            file_name=filename,
            file_name_extension=ext,
            llm_enhancement=False,
        )
        runtime = util_models.RuntimeOptions()

        try:
            response = self.client.submit_doc_parser_job_advance(request, runtime)
        except Exception as e:
            logger.error("提交文档解析任务失败: %s", e)
            raise RuntimeError(f"文档解析任务提交失败: {e}")

        task_id = response.body.data.id
        logger.info("文档解析任务已提交: %s (file=%s)", task_id, filename)
        return task_id

    def _wait_for_completion(self, task_id: str) -> None:
        poll_interval = settings.DOCMIND_POLL_INTERVAL
        timeout = settings.DOCMIND_TIMEOUT
        elapsed = 0

        while elapsed < timeout:
            try:
                request = docmind_models.QueryDocParserStatusRequest(id=task_id)
                response = self.client.query_doc_parser_status(request)
                data = response.body.data
                if data is None:
                    raise RuntimeError(f"查询任务状态返回空: task_id={task_id}")

                status_map = data.to_map() if hasattr(data, "to_map") else data
                status = str(status_map.get("Status", "")).lower()

                if status == "success":
                    logger.info("文档解析完成: %s", task_id)
                    return
                if status in ("fail", "failed"):
                    raise RuntimeError(f"文档解析失败: task_id={task_id}")

                logger.debug("文档解析中 (%ds)... status=%s", elapsed, status)

            except RuntimeError:
                raise
            except Exception as e:
                logger.warning("查询任务状态异常: %s", e)

            time.sleep(poll_interval)
            elapsed += poll_interval

        raise RuntimeError(f"文档解析超时（{timeout}s）: task_id={task_id}")

    @staticmethod
    def _dedup_table_cells(text: str) -> str:
        """
        对 Markdown 表格中因合并单元格产生的连续重复列去重。

        DocMind 处理合并单元格时，会将同一内容重复填充到网格每列位置，
        例如一个横跨 7 列的 "清华大学" 会输出为：
            |清华大学|清华大学|清华大学|清华大学|清华大学|清华大学|清华大学|
        本方法将其归一为：
            | 清华大学 |
        同时移除纯分隔行（---|---|---）并归一化单元格内空白。
        """
        lines = text.split('\n')
        result = []
        for line in lines:
            stripped = line.strip()
            if not (stripped.startswith('|') and stripped.endswith('|')
                    and stripped.count('|') >= 3):
                result.append(line)
                continue

            inner = stripped.split('|')[1:-1]

            if all(set(c.strip()) <= {'-', ':'} for c in inner if c.strip()):
                continue

            deduped = [' '.join(inner[0].split())]
            for cell in inner[1:]:
                normed = ' '.join(cell.split())
                if normed != deduped[-1]:
                    deduped.append(normed)

            result.append('| ' + ' | '.join(deduped) + ' |')
        return '\n'.join(result)

    def _collect_text(self, task_id: str) -> str:
        """分页获取全部 layout 块，拼接为纯文本"""
        all_parts: list[str] = []
        layout_num = 0
        step_size = 200

        while True:
            try:
                request = docmind_models.GetDocParserResultRequest(
                    id=task_id,
                    layout_step_size=step_size,
                    layout_num=layout_num,
                )
                response = self.client.get_doc_parser_result(request)
                data = response.body.data
                if data is None:
                    break

                layouts = (
                    data.get("layouts", [])
                    if isinstance(data, dict)
                    else getattr(data, "layouts", None) or []
                )
                if not layouts:
                    break

                for layout in layouts:
                    ltype = (
                        layout.get("type", "")
                        if isinstance(layout, dict)
                        else getattr(layout, "type", "")
                    ) or ""
                    if ltype in _SKIP_LAYOUT_TYPES:
                        continue

                    text = (
                        layout.get("text", "")
                        if isinstance(layout, dict)
                        else getattr(layout, "text", "")
                    ) or ""
                    if text.strip():
                        all_parts.append(text.strip())

                if len(layouts) < step_size:
                    break
                layout_num += len(layouts)

            except Exception as e:
                logger.warning("获取解析结果异常 (offset=%d): %s", layout_num, e)
                break

        return self._dedup_table_cells("\n\n".join(all_parts))

    def _collect_text_with_pages(self, task_id: str) -> Tuple[str, List[str]]:
        """分页获取全部 layout 块，按页码分组返回 (全文, 每页文本列表)"""
        parts_by_page: Dict[int, List[str]] = {}
        all_parts: List[str] = []
        layout_num = 0
        step_size = 200

        while True:
            try:
                request = docmind_models.GetDocParserResultRequest(
                    id=task_id,
                    layout_step_size=step_size,
                    layout_num=layout_num,
                )
                response = self.client.get_doc_parser_result(request)
                data = response.body.data
                if data is None:
                    break

                layouts = (
                    data.get("layouts", [])
                    if isinstance(data, dict)
                    else getattr(data, "layouts", None) or []
                )
                if not layouts:
                    break

                for layout in layouts:
                    ltype = (
                        layout.get("type", "")
                        if isinstance(layout, dict)
                        else getattr(layout, "type", "")
                    ) or ""
                    if ltype in _SKIP_LAYOUT_TYPES:
                        continue

                    text = (
                        layout.get("text", "")
                        if isinstance(layout, dict)
                        else getattr(layout, "text", "")
                    ) or ""

                    if isinstance(layout, dict):
                        pn = layout.get("pageNum", layout.get("page_num", 0))
                    else:
                        pn = getattr(layout, "page_num", None)
                        if pn is None:
                            pn = getattr(layout, "pageNum", 0)
                    try:
                        pn = int(pn) if pn else 0
                    except (ValueError, TypeError):
                        pn = 0

                    if text.strip():
                        stripped = text.strip()
                        all_parts.append(stripped)
                        parts_by_page.setdefault(pn, []).append(stripped)

                if len(layouts) < step_size:
                    break
                layout_num += len(layouts)

            except Exception as e:
                logger.warning("获取解析结果异常 (offset=%d): %s", layout_num, e)
                break

        full_text = self._dedup_table_cells("\n\n".join(all_parts))

        per_page_texts: List[str] = []
        for pn in sorted(parts_by_page.keys()):
            page_text = "\n\n".join(parts_by_page[pn])
            per_page_texts.append(self._dedup_table_cells(page_text))

        return full_text, per_page_texts
