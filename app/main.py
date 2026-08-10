"""
学术语料解析模块 - FastAPI 主入口
Academic Document Parsing Module - Main Entry
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .api.routes import router


def _parse_cors_origins(value: str) -> list[str]:
    """将逗号分隔的 CORS_ORIGINS 转换为中间件需要的列表。"""
    origins = [origin.strip() for origin in value.split(",") if origin.strip()]
    return ["*"] if "*" in origins else origins


cors_origins = _parse_cors_origins(settings.CORS_ORIGINS)
allow_credentials = "*" not in cors_origins

app = FastAPI(
    title=settings.APP_NAME,
    description="""
## 学术语料检查通用解析模块 V1

为科研之友四条关键学术业务线提供统一的文档解析服务：
- 语义查重
- 论文/申请书写作
- 编辑建议
- AI评审

### 核心功能
- 支持多种文档格式（纯文本、TXT、PDF、DOC/DOCX）
- 基于LLM的高精度段落意图识别
- 13类标签分类体系（侧重科研项目申请书）

### 标签体系
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
    """,
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    root_path=settings.ROOT_PATH,
)

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(router)


@app.on_event("startup")
async def startup_event():
    """应用启动时的初始化"""
    print(f"{settings.APP_NAME} V{settings.APP_VERSION} 启动中...")
    print("API文档: /docs")
    print("ReDoc文档: /redoc")

    from .services.task_manager import task_manager
    task_manager.start_watchdog()
    cleaned = task_manager.cleanup_old_tasks()
    if cleaned:
        print(f"启动时清理了 {cleaned} 个过期任务文件")


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭时的清理"""
    print("服务正在关闭...")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=True,
    )
