"""
Gunicorn 配置文件 - 生产环境高性能部署
支持多 worker 进程，提升 QPS 到 50+
"""
import multiprocessing
import os

from dotenv import load_dotenv


load_dotenv()

# =============================================================================
# 服务器配置
# =============================================================================

# 绑定地址和端口
bind = os.getenv("GUNICORN_BIND", "0.0.0.0:8898")

# Worker 进程数
# OCR 为 CPU 密集型任务，过多 worker 会导致 CPU 争抢和内存暴涨
# 24 核服务器建议不超过 8 个 worker
workers = int(os.getenv("GUNICORN_WORKERS", min(multiprocessing.cpu_count(), 8)))

# Worker 类型 - 使用独立维护的 uvicorn-worker 包
worker_class = "uvicorn_worker.UvicornWorker"

# 每个 worker 的线程数（对于 UvicornWorker 不适用，但保留配置）
threads = 1

# =============================================================================
# 超时配置
# =============================================================================

# Worker 超时时间（秒）- OCR 处理可能需要较长时间
timeout = 120

# 优雅关闭超时
graceful_timeout = 30

# Keep-alive 连接超时
keepalive = 5

# =============================================================================
# 进程管理
# =============================================================================

# 最大请求数后重启 worker（防止内存泄漏）
max_requests = 1000

# 随机增加 0-max_requests_jitter 个请求后重启（避免同时重启）
max_requests_jitter = 100

# 预加载应用（减少启动时间，但不支持代码热重载）
preload_app = True

# =============================================================================
# 日志配置
# =============================================================================

# 日志级别
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")

# 访问日志格式
accesslog = "-"  # 输出到 stdout
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# 错误日志
errorlog = "-"  # 输出到 stderr

# =============================================================================
# 性能调优
# =============================================================================

# 积压连接数（等待队列长度）
backlog = 2048

# Worker 连接数限制
worker_connections = 1000

# =============================================================================
# 安全配置
# =============================================================================

# 限制请求行大小（防止恶意请求）
limit_request_line = 4094

# 限制请求头字段数
limit_request_fields = 100

# 限制请求头字段大小
limit_request_field_size = 8190

# =============================================================================
# 钩子函数
# =============================================================================

def on_starting(server):
    """服务器启动前"""
    print("Gunicorn 服务器启动中...")
    print(f"   绑定地址: {bind}")
    print(f"   Worker 数量: {workers}")
    print(f"   Worker 类型: {worker_class}")


def on_reload(server):
    """服务器重载时"""
    print("Gunicorn 服务器重载中...")


def worker_int(worker):
    """Worker 收到 SIGINT 信号"""
    print(f"Worker {worker.pid} 收到中断信号")


def worker_abort(worker):
    """Worker 收到 SIGABRT 信号"""
    print(f"Worker {worker.pid} 被终止")


def pre_fork(server, worker):
    """Worker fork 之前"""
    pass


def post_fork(server, worker):
    """Worker fork 之后"""
    print(f"Worker {worker.pid} 已启动")


def pre_exec(server):
    """新 master 进程 exec 之前"""
    print("Gunicorn master 进程准备执行...")


def when_ready(server):
    """服务器准备就绪"""
    print("=" * 60)
    print("Gunicorn 服务器已就绪！")
    print(f"   绑定地址: {bind}")
    print(f"   API 文档: /docs")
    print(f"   健康检查: /health")
    print("=" * 60)


def worker_exit(server, worker):
    """Worker 退出时"""
    print(f"Worker {worker.pid} 已退出")


def nworkers_changed(server, new_value, old_value):
    """Worker 数量变化"""
    print(f"Worker 数量变化: {old_value} -> {new_value}")


def on_exit(server):
    """服务器退出"""
    print("Gunicorn 服务器已关闭")




