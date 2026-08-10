#!/usr/bin/env python3
"""
生产环境启动脚本 - 使用 Gunicorn + Uvicorn Workers
面向生产环境的多进程部署入口

使用方法:
    # 默认配置启动
    python run_production.py

    # 自定义 worker 数量
    python run_production.py --workers 8

    # 自定义端口
    python run_production.py --port 8898

    # 或直接使用 gunicorn 命令
    gunicorn app.main:app -c gunicorn.conf.py
"""
import argparse
import os
import subprocess
import sys
import multiprocessing

from dotenv import load_dotenv

load_dotenv()

from app.config import settings  # noqa: E402


def get_optimal_workers():
    """计算最优 worker 数量（OCR 为 CPU 密集型，限制上限）"""
    return min(multiprocessing.cpu_count(), 8)


def check_platform():
    """Gunicorn 依赖 POSIX，不支持在 Windows 上运行。"""
    if os.name == "nt":
        print("Gunicorn 不支持 Windows。开发环境请运行: python run.py")
        return False
    return True


def check_dependencies():
    """检查必要依赖"""
    try:
        import gunicorn
        import uvicorn
        import uvicorn_worker  # noqa: F401
        print(f"gunicorn 版本: {gunicorn.__version__}")
        print(f"uvicorn 版本: {uvicorn.__version__}")
        print("uvicorn-worker 已安装")
        return True
    except ImportError as e:
        print(f"缺少依赖: {e}")
        print("请运行: pip install -r requirements.txt")
        return False


def run_server(
    host=settings.APP_HOST,
    port=settings.APP_PORT,
    workers=None,
    log_level="info",
):
    """启动 Gunicorn 服务器"""

    if not check_platform() or not check_dependencies():
        return 1
    
    if workers is None:
        workers = get_optimal_workers()
    if workers < 1:
        print("Worker 数量必须大于或等于 1")
        return 1
    
    print("\n" + "=" * 60)
    print("启动 DocParse 生产环境服务")
    print("=" * 60)
    print(f"   地址: http://{host}:{port}")
    print(f"   Worker 数量: {workers}")
    print(f"   CPU 核数: {multiprocessing.cpu_count()}")
    print(f"   日志级别: {log_level}")
    print("=" * 60 + "\n")
    
    # 设置环境变量
    os.environ["GUNICORN_BIND"] = f"{host}:{port}"
    os.environ["GUNICORN_WORKERS"] = str(workers)
    os.environ["GUNICORN_LOG_LEVEL"] = log_level
    
    # 构建 gunicorn 命令
    cmd = [
        sys.executable, "-m", "gunicorn",
        "app.main:app",
        "-c", "gunicorn.conf.py"
    ]
    
    try:
        # 使用 subprocess 启动，以便更好地处理信号
        process = subprocess.run(cmd, cwd=os.path.dirname(os.path.abspath(__file__)))
        return process.returncode
    except KeyboardInterrupt:
        print("\n收到中断信号，正在关闭服务...")
        return 0


def main():
    parser = argparse.ArgumentParser(
        description="DocParse 生产环境启动脚本 (Gunicorn + Uvicorn Workers)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python run_production.py                    # 使用默认配置
  python run_production.py --workers 8        # 指定 8 个 worker
  python run_production.py --port 8898        # 使用 8898 端口
  python run_production.py -w 4 -p 9000       # 4 个 worker，端口 9000

性能建议:
  - OCR 为 CPU 密集型，worker 上限 min(CPU核数, 8)
  - 内存: 每个 worker 约占用 200-500MB
        """
    )
    
    parser.add_argument(
        "-H", "--host",
        default=settings.APP_HOST,
        help=f"绑定主机地址 (默认: {settings.APP_HOST})"
    )
    
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=settings.APP_PORT,
        help=f"绑定端口 (默认: {settings.APP_PORT})"
    )
    
    parser.add_argument(
        "-w", "--workers",
        type=int,
        default=None,
        help=f"Worker 进程数 (默认: min(CPU核数, 8) = {get_optimal_workers()})"
    )
    
    parser.add_argument(
        "-l", "--log-level",
        choices=["debug", "info", "warning", "error", "critical"],
        default="info",
        help="日志级别 (默认: info)"
    )
    
    parser.add_argument(
        "--check",
        action="store_true",
        help="仅检查依赖，不启动服务"
    )
    
    args = parser.parse_args()
    
    if args.check:
        checks_passed = check_platform() and check_dependencies()
        if checks_passed:
            print(f"\n推荐 Worker 数量: {get_optimal_workers()}")
            print("所有依赖检查通过")
        sys.exit(0 if checks_passed else 1)
    
    sys.exit(run_server(
        host=args.host,
        port=args.port,
        workers=args.workers,
        log_level=args.log_level
    ))


if __name__ == "__main__":
    main()

