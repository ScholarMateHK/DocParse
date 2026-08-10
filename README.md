# DocParse

面向科研文档的 FastAPI 解析服务：从纯文本、TXT、PDF、DOC 和 DOCX 中提取内容，调用大语言模型完成分段、13 类标签分类、标题/摘要识别，并提供同步与异步 API。

> [!WARNING]
> 当前仓库尚未附带 `LICENSE`。在版权所有者明确选择许可证之前，本仓库不授予复制、修改或分发代码的权利。公开使用或贡献前，请先完成许可证决策。

## 功能

- 支持纯文本、`.txt`、`.pdf`、`.doc`、`.docx`，单文件上限 50 MB；
- 支持同步解析和基于任务 ID 的异步解析；
- 支持规则分段、语义分段，以及滑动窗口或语义二次切分；
- V1 提供 13 类标签：标题、摘要、项目研究意义、国内外研究现状及发展动态分析、科学意义与应用前景、项目的研究内容、研究目标、拟解决的关键科学问题、研究方法、技术路线、关键技术、本项目的特色与创新之处、其他；
- 提供 Swagger UI、ReDoc、健康检查、标签和文件格式元数据接口。

## 数据流与第三方服务

DocParse 不是完全离线的解析器：

1. PDF、DOC 和 DOCX 默认优先上传到阿里云文档智能（Document Mind）提取文本与页码；云端解析失败时，PDF/DOCX 会尝试通过 pypdf 或 python-docx 直接提取，旧版 DOC 还可能使用 `antiword`、`catdoc` 或有限的二进制文本回退。
2. 提取后的文本会发送到配置的 LLM 服务，用于分类、语义分段、语义切分和缺失摘要生成；具体调用取决于请求参数。
3. 异步请求会把原始文本或上传文件、任务状态和解析结果写入 `TASK_STORAGE_DIR`，默认最长保留 24 小时。

部署者必须自行评估第三方费用、供应商条款、网络可用性、数据敏感度和适用法规。不要用真实敏感文档进行公开演示。

## 环境要求

- Python 3.10 及以上；CI 使用 Python 3.11；
- 开发模式支持 Linux、macOS 和 Windows；Gunicorn 生产模式仅支持 Unix/Linux；
- 可访问所配置的 LLM 与阿里云 API；
- 使用 `.doc` 本地回退时，可选安装 `antiword` 或 `catdoc`。

异步任务文件锁使用跨平台 `filelock`。原生 Windows 请使用 `python run.py`；多进程生产部署建议使用 Linux。

## 安装

```bash
git clone <repository-url>
cd DocParse

python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

cp .env.example .env
```

PowerShell 可使用 `Copy-Item .env.example .env`。随后编辑 `.env`，至少填写实际使用的 LLM 和 Document Mind 凭据。不要提交 `.env`。

## 配置

完整、安全占位的配置见 [.env.example](.env.example)。常用配置如下：

| 变量 | 用途 | 示例/默认值 |
|---|---|---|
| `LLM_API_KEY` | LLM 密钥；分类相关功能需要 | 留空，必须由部署者提供 |
| `LLM_BASE_URL` | OpenAI 兼容接口地址 | DashScope 兼容接口 |
| `LLM_MODEL` | 分类和生成所用模型 | `qwen3.6-flash` |
| `DOCMIND_ACCESS_KEY_ID` / `DOCMIND_ACCESS_KEY_SECRET` | Document Mind 凭据 | 留空，文件云解析需要 |
| `ROOT_PATH` | 反向代理剥离的外部路径前缀 | 本地直连留空；代理场景可设 `/docparse` |
| `CORS_ORIGINS` | 允许的浏览器来源，逗号分隔 | 本地前端地址；生产环境不要使用 `*` |
| `TASK_STORAGE_DIR` | 异步任务和上传文件的本地目录 | 系统临时目录下的 `docparse_tasks` |
| `TASK_MAX_AGE_HOURS` | 任务文件最长保留时间 | `24` |
| `GUNICORN_BIND` | 生产监听地址 | `0.0.0.0:8898` |
| `GUNICORN_WORKERS` | Gunicorn worker 数 | `4` |

`ROOT_PATH` 是反向代理元数据，不是应用路由前缀。本地直连时请求仍使用 `/health`、`/api/v1/...`；只有代理将外部前缀剥离后，客户端才使用例如 `/docparse/api/v1/...`。

## 快速开始

开发模式默认监听 `0.0.0.0:8898`：

```bash
python run.py
```

检查服务：

```bash
curl http://localhost:8898/health
```

解析纯文本：

```bash
curl -X POST http://localhost:8898/api/v1/parse_document \
  -F "business_line=semantic_check" \
  -F "version=v1" \
  -F "text=本项目拟研究复杂科研文档的结构化解析方法。"
```

启动后可访问：

- Swagger UI：`http://localhost:8898/docs`
- ReDoc：`http://localhost:8898/redoc`
- 完整中文文档：[docs/API.zh-CN.md](docs/API.zh-CN.md)

## 主要接口

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/health` | 健康检查 |
| `POST` | `/api/v1/parse_document` | 同步解析 |
| `POST` | `/api/v1/parse_document/async` | 提交异步任务 |
| `GET` | `/api/v1/tasks/status/{task_id}` | 查询任务状态 |
| `GET` | `/api/v1/tasks/result/{task_id}` | 获取任务结果 |
| `GET` | `/api/v1/tasks` | 列出最近任务 |
| `GET` | `/api/v1/tags` | 获取标签元数据 |
| `GET` | `/api/v1/supported_formats` | 获取文件限制与格式元数据 |

V1 中 `business_line` 仅执行枚举校验，尚未改变解析策略。调用方不应依赖不同业务线产生不同结果。

## 测试

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m compileall -q app run.py run_production.py gunicorn.conf.py
# Unix/Linux 生产依赖检查
python run_production.py --check
python -m pytest
```

测试不会调用 LLM 或 Document Mind，也不需要真实密钥。

## 生产部署

```bash
python run_production.py --workers 4 --port 8898
```

当前服务不内置身份认证、授权、租户隔离或速率限制。生产环境应置于受控 API 网关或反向代理后，并至少配置 HTTPS、认证、请求体限制、速率/并发限制、明确的 CORS 来源、日志脱敏和隔离的任务存储。Gunicorn 默认 worker 超时为 120 秒；较大的文档应使用异步接口。

更多要求见 [SECURITY.md](SECURITY.md)。

## 项目结构

```text
DocParse/
├── app/                    # FastAPI 应用、模型和解析服务
├── docs/API.zh-CN.md       # 中文 API 文档
├── tests/                  # 无网络元数据测试
├── .github/workflows/      # GitHub Actions CI
├── .env.example            # 无密钥配置模板
├── gunicorn.conf.py        # 生产服务器配置
├── requirements.txt        # 运行依赖
├── requirements-dev.txt    # 测试依赖
├── run.py                  # 开发入口
└── run_production.py       # Gunicorn 启动入口
```

## 安全与贡献

- 安全问题请按 [SECURITY.md](SECURITY.md) 私下报告，不要在公开 Issue 中粘贴密钥或真实文档。
- 提交变更前请运行上述编译和测试命令。
- 许可证尚未确定；在此之前，请勿假定该项目属于开源软件。
