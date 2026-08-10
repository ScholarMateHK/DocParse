"""
任务管理器 - 异步任务处理（支持多进程部署）
支持提交任务、查询状态、获取结果

多进程兼容设计:
- 使用文件系统存储任务状态（而非内存）
- 使用文件锁确保跨进程安全
- 支持 Gunicorn 多 worker 部署

并发优化:
- 每个任务创建独立的 DocumentParser 实例，避免线程间状态竞争
- 任务执行带超时保护，防止线程被永久占用
- 后台巡检线程定期扫描并回收僵尸任务（解决 worker 回收后的孤儿任务问题）
"""
import uuid
import threading
import json
import os
import gc
import tempfile
import time
from datetime import datetime, timedelta
from typing import Dict, Optional, Any, List
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, asdict
from pathlib import Path

from filelock import FileLock, Timeout as FileLockTimeout

from ..models.schemas import TaskStatus
from ..config import settings


_configured_storage_dir = os.getenv("TASK_STORAGE_DIR", "").strip()
TASK_STORAGE_DIR = _configured_storage_dir or os.path.join(
    tempfile.gettempdir(), "docparse_tasks"
)


@dataclass
class Task:
    """任务数据类"""
    task_id: str
    status: str = "pending"
    progress: float = 0.0
    created_at: str = ""
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    last_activity: Optional[str] = None
    result: Optional[Dict] = None
    error_message: Optional[str] = None
    text: Optional[str] = None
    file_content_path: Optional[str] = None
    filename: Optional[str] = None
    process_mode: str = "unified"
    segment_mode: str = "rule"
    chunk_size: Optional[int] = None
    overlap: Optional[int] = None
    chunk_method: str = "sliding"

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "Task":
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered_data)

    def get_status_enum(self) -> TaskStatus:
        return TaskStatus(self.status)


class FileBasedTaskStorage:
    """基于文件系统的任务存储，支持多进程安全访问"""

    def __init__(self, storage_dir: str = TASK_STORAGE_DIR):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.file_content_dir = self.storage_dir / "file_contents"
        self.file_content_dir.mkdir(parents=True, exist_ok=True)
        print(f"任务存储目录: {self.storage_dir}")

    def _get_task_path(self, task_id: str) -> Path:
        return self.storage_dir / f"{task_id}.json"

    def _get_file_content_path(self, task_id: str) -> Path:
        return self.file_content_dir / f"{task_id}.bin"

    def _get_task_lock(self, task_id: str) -> FileLock:
        return FileLock(str(self.storage_dir / f".{task_id}.lock"))

    def _get_file_content_lock(self, task_id: str) -> FileLock:
        return FileLock(str(self.file_content_dir / f".{task_id}.lock"))

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        """在目标目录内写临时文件，再以 os.replace 原子替换。"""
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
        )
        try:
            with os.fdopen(descriptor, "wb") as temporary_file:
                temporary_file.write(content)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, path)
        finally:
            if os.path.exists(temporary_path):
                os.unlink(temporary_path)

    def _write_task_unlocked(self, task: Task) -> None:
        task_path = self._get_task_path(task.task_id)
        payload = json.dumps(
            task.to_dict(), ensure_ascii=False, indent=2
        ).encode("utf-8")
        self._atomic_write(task_path, payload)

    def _load_task_unlocked(self, task_id: str) -> Optional[Task]:
        task_path = self._get_task_path(task_id)
        if not task_path.exists():
            return None
        try:
            with open(task_path, "r", encoding="utf-8") as task_file:
                return Task.from_dict(json.load(task_file))
        except (json.JSONDecodeError, FileNotFoundError):
            return None

    def save_task(self, task: Task) -> None:
        with self._get_task_lock(task.task_id):
            self._write_task_unlocked(task)

    def load_task(self, task_id: str) -> Optional[Task]:
        with self._get_task_lock(task_id):
            return self._load_task_unlocked(task_id)

    def update_task(self, task_id: str, **updates) -> Optional[Task]:
        with self._get_task_lock(task_id):
            task = self._load_task_unlocked(task_id)
            if not task:
                return None
            if "last_activity" not in updates:
                updates["last_activity"] = datetime.now().isoformat()
            for key, value in updates.items():
                if hasattr(task, key):
                    setattr(task, key, value)
            self._write_task_unlocked(task)
            return task

    def delete_task(self, task_id: str) -> bool:
        task_path = self._get_task_path(task_id)
        file_content_path = self._get_file_content_path(task_id)
        deleted = False
        with self._get_task_lock(task_id):
            if task_path.exists():
                task_path.unlink()
                deleted = True
        with self._get_file_content_lock(task_id):
            if file_content_path.exists():
                file_content_path.unlink()
        return deleted

    def list_tasks(self, limit: int = 100) -> List[Task]:
        tasks = []
        for task_file in self.storage_dir.glob("*.json"):
            task_id = task_file.stem
            task = self.load_task(task_id)
            if task:
                tasks.append(task)
        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return tasks[:limit]

    def save_file_content(self, task_id: str, content: bytes) -> str:
        file_path = self._get_file_content_path(task_id)
        with self._get_file_content_lock(task_id):
            self._atomic_write(file_path, content)
        return str(file_path)

    def load_file_content(self, task_id: str) -> Optional[bytes]:
        file_path = self._get_file_content_path(task_id)
        with self._get_file_content_lock(task_id):
            if not file_path.exists():
                return None
            with open(file_path, "rb") as content_file:
                return content_file.read()

    def cleanup_old_tasks(self, max_age_hours: int = 24) -> int:
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        deleted_count = 0
        for task_file in self.storage_dir.glob("*.json"):
            task_id = task_file.stem
            task = self.load_task(task_id)
            if task:
                try:
                    created_at = datetime.fromisoformat(task.created_at)
                    if created_at < cutoff:
                        self.delete_task(task_id)
                        deleted_count += 1
                except (ValueError, TypeError):
                    pass
        if deleted_count > 0:
            print(f"清理了 {deleted_count} 个过期任务")
        return deleted_count


class TaskManager:
    """
    任务管理器（多进程安全 + 并发优化）

    关键设计:
    - 每个任务创建独立的 DocumentParser，消除线程间状态竞争
    - 使用 Future + timeout 保护，防止任务永久阻塞线程
    - 后台巡检线程定期扫描并回收僵尸任务
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        max_workers = int(os.getenv("TASK_EXECUTOR_WORKERS", str(settings.TASK_EXECUTOR_WORKERS)))
        self._storage = FileBasedTaskStorage()
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._task_lock = threading.Lock()
        self._active_futures: Dict[str, Future] = {}
        self._initialized = True

        recovered = self._recover_stuck_tasks()
        if recovered > 0:
            print(f"初始化时回收 {recovered} 个僵尸任务")

        print(f"TaskManager 初始化完成 (线程池: {max_workers}, 任务超时: {settings.TASK_TIMEOUT}s)")

    def _recover_stuck_tasks(self):
        """扫描并回收僵尸任务，基于心跳活跃度判断而非总运行时间

        processing 任务: 若 last_activity（或 started_at）距今超过 TASK_STUCK_TIMEOUT，
                         说明心跳已停止（worker 崩溃/进程回收），标记为失败。
        pending 任务:    若 created_at 距今超过 TASK_STUCK_TIMEOUT，说明未被调度，标记为失败。
        """
        recovered = 0
        stuck_timeout = settings.TASK_STUCK_TIMEOUT
        now = datetime.now()

        for task_file in self._storage.storage_dir.glob("*.json"):
            task_id = task_file.stem
            task = self._storage.load_task(task_id)
            if not task:
                continue

            if task.status == TaskStatus.PROCESSING.value:
                is_stuck = False
                try:
                    last_active = None
                    if task.last_activity:
                        last_active = datetime.fromisoformat(task.last_activity)
                    elif task.started_at:
                        last_active = datetime.fromisoformat(task.started_at)

                    if last_active and (now - last_active).total_seconds() > stuck_timeout:
                        is_stuck = True
                    elif not last_active:
                        is_stuck = True
                except (ValueError, TypeError):
                    is_stuck = True

                if is_stuck:
                    self._storage.update_task(
                        task_id,
                        status=TaskStatus.FAILED.value,
                        completed_at=now.isoformat(),
                        error_message=f"任务心跳超时（超过 {stuck_timeout}s 无活动），已被自动回收"
                    )
                    recovered += 1

            elif task.status == TaskStatus.PENDING.value:
                try:
                    created = datetime.fromisoformat(task.created_at)
                    if (now - created).total_seconds() > stuck_timeout:
                        self._storage.update_task(
                            task_id,
                            status=TaskStatus.FAILED.value,
                            completed_at=now.isoformat(),
                            error_message=f"任务长时间未被执行（超过 {stuck_timeout}s），已被自动回收"
                        )
                        recovered += 1
                except (ValueError, TypeError):
                    pass

        return recovered

    def start_watchdog(self):
        """启动僵尸任务巡检线程（每个 worker 进程调用一次）"""
        current_pid = os.getpid()
        if getattr(self, '_watchdog_pid', None) == current_pid:
            return

        recovered = self._recover_stuck_tasks()
        if recovered > 0:
            print(f"已回收 {recovered} 个僵尸任务")

        self._watchdog_pid = current_pid
        watchdog = threading.Thread(
            target=self._watchdog_loop,
            daemon=True,
            name=f"task-watchdog-{current_pid}"
        )
        watchdog.start()
        print(f"僵尸任务巡检已启动 (PID: {current_pid}, 间隔: {settings.TASK_WATCHDOG_INTERVAL}s)")

    def _watchdog_loop(self):
        """定期扫描并回收僵尸任务，使用文件锁避免多 worker 重复扫描"""
        interval = settings.TASK_WATCHDOG_INTERVAL
        lock_path = self._storage.storage_dir / ".watchdog.lock"
        cycle = 0

        while True:
            time.sleep(interval)
            cycle += 1
            try:
                with FileLock(str(lock_path), timeout=0):
                    recovered = self._recover_stuck_tasks()
                    if recovered > 0:
                        print(f"巡检回收 {recovered} 个僵尸任务 (PID: {os.getpid()})")
                    if cycle % 10 == 0:
                        self.cleanup_old_tasks()
            except FileLockTimeout:
                continue
            except Exception as e:
                print(f"巡检异常: {e}")

    def _create_parser(self, process_mode: str, segment_mode: str):
        """为每个任务创建独立的 DocumentParser 实例，避免线程竞争"""
        from .document_parser import DocumentParser
        parser = DocumentParser(segment_mode=segment_mode, process_mode=process_mode)
        return parser

    def submit_task(
        self,
        text: Optional[str] = None,
        file_content: Optional[bytes] = None,
        filename: Optional[str] = None,
        process_mode: str = "unified",
        segment_mode: str = "rule",
        chunk_size: Optional[int] = None,
        overlap: Optional[int] = None,
        chunk_method: str = "sliding"
    ) -> Task:
        task_id = str(uuid.uuid4())

        file_content_path = None
        if file_content:
            file_content_path = self._storage.save_file_content(task_id, file_content)

        task = Task(
            task_id=task_id,
            status=TaskStatus.PENDING.value,
            created_at=datetime.now().isoformat(),
            text=text,
            file_content_path=file_content_path,
            filename=filename,
            process_mode=process_mode,
            segment_mode=segment_mode,
            chunk_size=chunk_size,
            overlap=overlap,
            chunk_method=chunk_method
        )

        self._storage.save_task(task)

        future = self._executor.submit(self._process_task_with_timeout, task_id)
        with self._task_lock:
            self._active_futures[task_id] = future
        future.add_done_callback(lambda f: self._on_task_done(task_id, f))

        return task

    def _on_task_done(self, task_id: str, future: Future):
        """任务完成（含异常）时的回调，清理 future 引用"""
        with self._task_lock:
            self._active_futures.pop(task_id, None)

        exc = future.exception()
        if exc:
            print(f"任务 {task_id} 异常退出: {exc}")
            task = self._storage.load_task(task_id)
            if task and task.status == TaskStatus.PROCESSING.value:
                self._storage.update_task(
                    task_id,
                    status=TaskStatus.FAILED.value,
                    completed_at=datetime.now().isoformat(),
                    error_message=f"任务执行异常: {exc}"
                )

    def _process_task_with_timeout(self, task_id: str):
        """带超时保护 + 心跳的任务执行入口

        在等待任务完成期间，每隔 HEARTBEAT_INTERVAL 秒刷新一次 last_activity，
        使 watchdog 能区分"正常运行中的长任务"和"真正卡死的僵尸任务"。
        """
        timeout = settings.TASK_TIMEOUT
        heartbeat_interval = 30
        error_container = [None]
        done_event = threading.Event()

        def _worker():
            try:
                self._process_task(task_id)
            except Exception as e:
                error_container[0] = e
            finally:
                done_event.set()

        worker_thread = threading.Thread(target=_worker, daemon=True)
        worker_thread.start()

        start_time = time.time()
        while True:
            remaining = timeout - (time.time() - start_time)
            if remaining <= 0:
                print(f"任务 {task_id} 执行超时 ({timeout}s)，强制标记为失败")
                self._storage.update_task(
                    task_id,
                    status=TaskStatus.FAILED.value,
                    completed_at=datetime.now().isoformat(),
                    error_message=f"任务处理超时（超过 {timeout} 秒），请检查文件大小或格式"
                )
                return

            wait_time = min(heartbeat_interval, remaining)
            if done_event.wait(timeout=wait_time):
                break

            self._storage.update_task(task_id, last_activity=datetime.now().isoformat())

        if error_container[0]:
            raise error_container[0]

    def _process_task(self, task_id: str):
        """后台处理任务（每个任务使用独立的 parser 实例）"""
        task = self._storage.load_task(task_id)
        if not task:
            print(f"任务 {task_id} 不存在")
            return

        try:
            self._storage.update_task(
                task_id,
                status=TaskStatus.PROCESSING.value,
                started_at=datetime.now().isoformat(),
                progress=10.0
            )

            file_content = None
            if task.file_content_path:
                file_content = self._storage.load_file_content(task_id)

            parser = self._create_parser(task.process_mode, task.segment_mode)

            self._storage.update_task(task_id, progress=20.0)

            result = parser.parse(
                text=task.text,
                file_content=file_content,
                filename=task.filename,
                chunk_size=task.chunk_size,
                overlap=task.overlap,
                chunk_method=task.chunk_method
            )

            self._storage.update_task(task_id, progress=90.0)

            current = self._storage.load_task(task_id)
            if current and current.status == TaskStatus.FAILED.value:
                print(f"任务 {task_id} 已被标记为失败（超时/回收），跳过结果更新")
                return

            result_dict = None
            if result:
                segments_data = []
                for seg in (result.segments or []):
                    seg_dict = {
                        "segment_id": seg.segment_id,
                        "content": seg.content,
                        "tag": seg.tag,
                        "confidence": seg.confidence,
                        "pageIdx": seg.pageIdx,
                    }
                    if seg.chunks:
                        seg_dict["chunks"] = [
                            {
                                "chunk_id": chunk.chunk_id,
                                "segment_id": chunk.segment_id,
                                "content": chunk.content,
                                "tag": chunk.tag,
                                "start_pos": chunk.start_pos,
                                "end_pos": chunk.end_pos
                            }
                            for chunk in seg.chunks
                        ]
                    segments_data.append(seg_dict)

                result_dict = {
                    "status": result.status,
                    "doc_id": result.doc_id,
                    "title": result.title,
                    "abstract": result.abstract,
                    "segments": segments_data,
                    "error_message": result.error_message,
                    "chunk_info": result.chunk_info
                }

            update_data = {
                "status": TaskStatus.COMPLETED.value,
                "completed_at": datetime.now().isoformat(),
                "progress": 100.0,
                "result": result_dict
            }

            if result and result.status == "error":
                update_data["status"] = TaskStatus.FAILED.value
                update_data["error_message"] = result.error_message

            self._storage.update_task(task_id, **update_data)
            print(f"任务 {task_id} 处理完成")

        except Exception as e:
            print(f"任务 {task_id} 处理失败: {e}")
            import traceback
            traceback.print_exc()
            current = self._storage.load_task(task_id)
            if current and current.status != TaskStatus.FAILED.value:
                self._storage.update_task(
                    task_id,
                    status=TaskStatus.FAILED.value,
                    completed_at=datetime.now().isoformat(),
                    error_message=str(e)
                )
        finally:
            gc.collect()

    def get_task(self, task_id: str) -> Optional[Task]:
        return self._storage.load_task(task_id)

    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        task = self.get_task(task_id)
        if not task:
            return None
        return {
            "task_id": task.task_id,
            "status": task.status,
            "progress": task.progress,
            "created_at": task.created_at,
            "started_at": task.started_at,
            "completed_at": task.completed_at,
            "last_activity": task.last_activity,
            "error_message": task.error_message
        }

    def get_task_result(self, task_id: str) -> Optional[Dict[str, Any]]:
        task = self.get_task(task_id)
        if not task:
            return None
        return {
            "task_id": task.task_id,
            "status": task.status,
            "result": task.result,
            "created_at": task.created_at,
            "completed_at": task.completed_at,
            "error_message": task.error_message
        }

    def list_tasks(self, limit: int = 100) -> list:
        tasks = self._storage.list_tasks(limit)
        return [
            {
                "task_id": t.task_id,
                "status": t.status,
                "progress": t.progress,
                "created_at": t.created_at,
                "completed_at": t.completed_at
            }
            for t in tasks
        ]

    def cleanup_old_tasks(self, max_age_hours: int = None):
        if max_age_hours is None:
            max_age_hours = settings.TASK_MAX_AGE_HOURS
        return self._storage.cleanup_old_tasks(max_age_hours)


# 全局任务管理器实例
task_manager = TaskManager()
