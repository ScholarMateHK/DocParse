"""
配置文件 - Configuration Settings
"""
from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict


load_dotenv()


class Settings(BaseSettings):
    """应用配置"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    
    # API Settings
    APP_NAME: str = "学术语料解析模块"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8898
    ROOT_PATH: str = ""
    CORS_ORIGINS: str = "*"
    
    # LLM API Settings (阿里云)
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    LLM_MODEL: str = "qwen3.6-flash"  # 通义千问Flash - 快速响应版，适合高QPS场景
    
    # Processing Settings
    MAX_SEGMENT_LENGTH: int = 2000  # 单个段落最大字符数
    OCR_LANGUAGE: str = "chi_sim+eng"  # OCR语言设置
    
    # Segmentation Settings
    DEFAULT_SEGMENT_MODE: str = "rule"  # 默认分段模式: "rule" 或 "semantic"
    DEFAULT_PROCESS_MODE: str = "unified"  # 默认处理模式: "separate"(先分段再批量分类) 或 "unified"(一次完成)
    DEFAULT_BATCH_MODE: str = "batch"  # 默认分类模式: "batch"(批量分类) 或 "single"(逐个分类)
    SEMANTIC_SEGMENT_MAX_CHUNK: int = 6000  # 语义分段单次处理最大字符数
    SEMANTIC_SEGMENT_MAX_BATCH: int = 30  # 语义分段单批次最大句子数
    
    # File Upload Settings
    MAX_FILE_SIZE: int = 50 * 1024 * 1024  # 50MB
    ALLOWED_EXTENSIONS: set = {".txt", ".pdf", ".doc", ".docx"}
    
    # Task Manager Settings
    TASK_TIMEOUT: int = 3000  # 单个任务最大处理时间（秒），硬性上限
    TASK_EXECUTOR_WORKERS: int = 4  # 异步任务线程池大小（OCR 为 CPU 密集型，不宜过大）
    TASK_STUCK_TIMEOUT: int = 600  # 心跳超时（秒）：超过此时间无心跳更新则判定为僵尸任务
    TASK_MAX_AGE_HOURS: int = 24  # 任务文件最大保留时间（小时）
    TASK_WATCHDOG_INTERVAL: int = 60  # 僵尸任务巡检间隔（秒）
    
    # 阿里云文档智能（Document Mind）Settings
    DOCMIND_ACCESS_KEY_ID: str = ""
    DOCMIND_ACCESS_KEY_SECRET: str = ""
    DOCMIND_ENDPOINT: str = "docmind-api.cn-hangzhou.aliyuncs.com"
    DOCMIND_POLL_INTERVAL: int = 3   # 轮询任务状态间隔（秒）
    DOCMIND_TIMEOUT: int = 300       # 等待任务完成最大时间（秒）
    DOCMIND_MAX_CONCURRENT: int = 1  # 每个 worker 最大并发调用数（8 worker × 1 = 全局最多 8 并发）
    
    # LLM Reliability Settings
    LLM_TIMEOUT: int = 60  # LLM API 单次调用超时（秒）
    LLM_MAX_RETRIES: int = 2  # LLM API 失败重试次数

    def require_llm_api_key(self) -> str:
        """返回已配置的 LLM API Key，否则给出明确错误。"""
        api_key = self.LLM_API_KEY.strip()
        if not api_key:
            raise RuntimeError(
                "未配置 LLM_API_KEY，请通过环境变量或 .env 文件提供"
            )
        return api_key

    def require_docmind_credentials(self) -> tuple[str, str]:
        """返回阿里云文档智能凭据，否则给出明确错误。"""
        access_key_id = self.DOCMIND_ACCESS_KEY_ID.strip()
        access_key_secret = self.DOCMIND_ACCESS_KEY_SECRET.strip()
        if not access_key_id or not access_key_secret:
            raise RuntimeError(
                "未配置 DOCMIND_ACCESS_KEY_ID/DOCMIND_ACCESS_KEY_SECRET，"
                "请通过环境变量或 .env 文件提供"
            )
        return access_key_id, access_key_secret


settings = Settings()


# V1 分类标签体系 (13类 - 侧重项目申请书)
V1_CLASSIFICATION_TAGS = [
    "标题",
    "摘要",
    "项目研究意义",
    "国内外研究现状及发展动态分析",
    "科学意义与应用前景",
    "项目的研究内容",
    "研究目标",
    "拟解决的关键科学问题",
    "研究方法",
    "技术路线",
    "关键技术",
    "本项目的特色与创新之处",
    "其他"  # 可选的兜底类别
]

# 标签描述
V1_TAG_DESCRIPTIONS = {
    "标题": "文档或项目的标题",
    "摘要": "对全文内容的概括性描述（不超过500字）",
    "项目研究意义": "阐述研究的重要性、价值和必要性",
    "国内外研究现状及发展动态分析": "综述相关领域的研究进展和发展趋势",
    "科学意义与应用前景": "描述研究的科学价值和潜在应用",
    "项目的研究内容": "具体说明要研究什么内容",
    "研究目标": "明确的研究目标和预期成果",
    "拟解决的关键科学问题": "需要突破的核心科学难题",
    "研究方法": "采用的研究方法和手段",
    "技术路线": "研究的技术路径和实施步骤",
    "关键技术": "需要攻克的关键技术难点",
    "本项目的特色与创新之处": "项目的独特之处和创新点",
    "其他": "无法归类到以上类别的内容"
}

# Chunk 切分相关配置
DEFAULT_CHUNK_SIZE = 500  # 默认chunk大小（字符数）
DEFAULT_CHUNK_OVERLAP = 50  # 默认重叠区间（字符数）
CHUNK_METHOD_SLIDING = "sliding"  # 滑动窗口切分
CHUNK_METHOD_SEMANTIC = "semantic"  # 语义切分
