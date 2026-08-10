# 学术语料解析模块 API 文档

## 基础信息

- **服务地址**: `http://121.43.245.185/docparse/`
- **协议**: HTTP/1.1
- **请求方式**: 支持同步HTTP请求和异步任务模式
- **支持格式**: 纯文本、TXT (.txt)、PDF (.pdf)、Word (.doc/.docx)
- **最大文件大小**: 50MB
- **请求超时**: 300秒
- **编码**: UTF-8

---

## 分类标签体系（13类）

| 序号 | 标签名称 | 说明 |
|------|----------|------|
| 1 | 标题 | 文档或项目的标题（可能为空） |
| 2 | 摘要 | 对全文内容的概括性描述（若原文无摘要则自动生成） |
| 3 | 项目研究意义 | 阐述研究的重要性、价值和必要性 |
| 4 | 国内外研究现状及发展动态分析 | 综述相关领域的研究进展和发展趋势 |
| 5 | 科学意义与应用前景 | 描述研究的科学价值和潜在应用 |
| 6 | 项目的研究内容 | 具体说明要研究什么内容 |
| 7 | 研究目标 | 明确的研究目标和预期成果 |
| 8 | 拟解决的关键科学问题 | 需要突破的核心科学难题 |
| 9 | 研究方法 | 采用的研究方法和手段 |
| 10 | 技术路线 | 研究的技术路径和实施步骤 |
| 11 | 关键技术 | 需要攻克的关键技术难点 |
| 12 | 本项目的特色与创新之处 | 项目的独特之处和创新点 |
| 13 | 其他 | 无法归类到以上类别的内容 |

**特殊说明：**
- **标题**：部分语料可能不存在标题，若未识别到标题则返回 `null`
- **摘要**：若原文中未找到摘要，系统将自动调用大模型生成约500字的摘要

---

## API接口列表

### 1. 文档解析接口（同步）

**接口地址:** `POST /api/v1/parse_document`

**请求类型:** 同步请求，需等待处理完成后返回结果

**Content-Type:** `multipart/form-data`

**请求参数:**

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| business_line | String | 否 | semantic_check | 业务线：semantic_check(语义查重)、paper_writing(论文写作)、edit_suggestion(编辑建议)、ai_review(AI评审) |
| version | String | 否 | v1 | 版本号：v1 |
| process_mode | String | 否 | separate | 处理模式：separate(分离模式，分段和分类分开调用)、unified(统一模式，一次LLM调用完成分段+分类) |
| segment_mode | String | 否 | rule | 分段模式(仅separate模式有效)：rule(规则分段，快速)、semantic(语义分段，基于LLM) |
| chunk_size | Integer | 否 | - | 二次切分的块大小(字符数)，若传入则对已打标签的语义段落进行二次切分，最小值50 |
| overlap | Integer | 否 | 0 | 切分重叠区间(字符数)，仅在chunk_size传入时生效，用于保证上下文语义连贯，必须小于chunk_size |
| chunk_method | String | 否 | sliding | 切分方式：sliding(滑动窗口切分)、semantic(语义切分，使用LLM) |
| text | String | 否* | - | 纯文本输入（与file二选一或同时提供） |
| file | File | 否* | - | 文档文件，支持.txt/.pdf/.doc/.docx格式 |

> *注：text和file参数至少提供其一

**响应格式:** `application/json`

**成功响应 (200):**
```json
{
    "status": "success",
    "doc_id": "uuid-123456-789",
    "title": "基于深度学习的智能信息处理系统研究",
    "abstract": "本项目针对复杂网络环境下的智能信息处理问题展开研究...(约500字)",
    "segments": [
        {
            "segment_id": 1,
            "content": "本项目研究意义重大，旨在解决...",
            "tag": "项目研究意义",
            "confidence": 0.95,
            "pageIdx": 1,
            "chunks": null
        },
        {
            "segment_id": 2,
            "content": "近年来，国内外学者在该领域取得了重要进展...",
            "tag": "国内外研究现状及发展动态分析",
            "confidence": 0.92,
            "pageIdx": 2,
            "chunks": null
        }
    ],
    "error_message": null,
    "chunk_info": null
}
```

**带二次切分的成功响应 (200):**

当传入 `chunk_size` 参数时，返回结果将包含二次切分信息：

```json
{
    "status": "success",
    "doc_id": "uuid-123456-789",
    "title": "基于深度学习的智能信息处理系统研究",
    "abstract": "本项目针对复杂网络环境下的智能信息处理问题展开研究...",
    "segments": [
        {
            "segment_id": 1,
            "content": "本项目研究意义重大，旨在解决人工智能领域的关键问题。随着技术的发展，该领域面临着越来越多的挑战...",
            "tag": "项目研究意义",
            "confidence": 0.95,
            "pageIdx": 1,
            "chunks": [
                {
                    "chunk_id": 1,
                    "segment_id": 1,
                    "content": "本项目研究意义重大，旨在解决人工智能领域的关键问题。",
                    "tag": "项目研究意义",
                    "start_pos": 0,
                    "end_pos": 35
                },
                {
                    "chunk_id": 2,
                    "segment_id": 1,
                    "content": "随着技术的发展，该领域面临着越来越多的挑战...",
                    "tag": "项目研究意义",
                    "start_pos": 30,
                    "end_pos": 65
                }
            ]
        }
    ],
    "error_message": null,
    "chunk_info": {
        "chunk_size": 500,
        "overlap": 50,
        "method": "sliding"
    }
}
```

**响应字段说明:**

| 字段名 | 类型 | 说明 |
|--------|------|------|
| status | String | 处理状态：success/error |
| doc_id | String | 文档唯一标识 |
| title | String/null | 文档标题（可能为空） |
| abstract | String/null | 文档摘要（若原文无摘要则由LLM生成约500字） |
| segments | Array | 解析后的段落列表 |
| segments[].segment_id | Integer | 段落ID |
| segments[].content | String | 段落原文 |
| segments[].tag | String | 预测标签 |
| segments[].confidence | Float | 置信度分数(0-1) |
| segments[].pageIdx | Integer/null | 段落所在页码，从1开始（仅文件上传且可获取页码时返回） |
| segments[].chunks | Array/null | 二次切分后的块列表（仅在传入chunk_size时返回） |
| chunks[].chunk_id | Integer | 全局块ID |
| chunks[].segment_id | Integer | 所属段落ID |
| chunks[].content | String | 块内容 |
| chunks[].tag | String | 继承自段落的标签 |
| chunks[].start_pos | Integer | 在原段落中的起始位置 |
| chunks[].end_pos | Integer | 在原段落中的结束位置 |
| error_message | String/null | 错误信息(如有) |
| chunk_info | Object/null | 切分配置信息（仅在传入chunk_size时返回） |

**错误响应:**
```json
{
    "detail": "错误描述信息"
}
```

---

### 2. 文档解析接口（异步）

**接口地址:** `POST /api/v1/parse_document/async`

**请求类型:** 异步请求，立即返回任务ID，后续通过任务ID查询结果

**Content-Type:** `multipart/form-data`

**请求参数:** 与同步接口相同

**成功响应 (200):**
```json
{
    "task_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "pending",
    "message": "任务已提交，请通过任务ID查询结果",
    "created_at": "2026-01-13T10:30:00"
}
```

---

### 3. 查询任务状态

**接口地址:** `GET /api/v1/tasks/status/{task_id}`

**请求类型:** 同步请求

**路径参数:**
| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| task_id | String | 是 | 任务唯一标识 |

**成功响应 (200):**
```json
{
    "task_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "processing",
    "progress": 50.0,
    "created_at": "2026-01-13T10:30:00",
    "started_at": "2026-01-13T10:30:01",
    "completed_at": null,
    "error_message": null
}
```

**任务状态说明:**
| 状态 | 说明 |
|------|------|
| pending | 任务等待处理 |
| processing | 任务正在处理中 |
| completed | 任务处理完成 |
| failed | 任务处理失败 |

---

### 4. 获取任务结果

**接口地址:** `GET /api/v1/tasks/result/{task_id}`

**请求类型:** 同步请求

**路径参数:**
| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| task_id | String | 是 | 任务唯一标识 |

**成功响应 (200):**
```json
{
    "task_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "completed",
    "result": {
        "status": "success",
        "doc_id": "uuid-yyy-yyy",
        "title": "基于深度学习的智能信息处理系统研究",
        "abstract": "本项目针对复杂网络环境下的智能信息处理问题展开研究...",
        "segments": [
            {
                "segment_id": 1,
                "content": "本项目研究意义重大...",
                "tag": "项目研究意义",
                "confidence": 0.95,
                "pageIdx": 1,
                "chunks": null
            }
        ],
        "chunk_info": null
    },
    "created_at": "2026-01-13T10:30:00",
    "completed_at": "2026-01-13T10:30:15",
    "error_message": null
}
```

---

### 5. 列出任务列表

**接口地址:** `GET /api/v1/tasks`

**请求类型:** 同步请求

**查询参数:**
| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| limit | Integer | 否 | 20 | 返回数量限制，最大100 |

**成功响应 (200):**
```json
{
    "tasks": [
        {
            "task_id": "uuid-xxx",
            "status": "completed",
            "progress": 100.0,
            "created_at": "2026-01-13T10:30:00",
            "completed_at": "2026-01-13T10:30:15"
        }
    ],
    "total": 5
}
```

---

### 6. 健康检查接口

**接口地址:** `GET /health`

**请求类型:** 同步请求

**请求参数:** 无

**成功响应 (200):**
```json
{
    "status": "healthy",
    "version": "1.0.0",
    "service": "学术语料解析模块"
}
```

---

### 7. 获取分类标签列表

**接口地址:** `GET /api/v1/tags`

**请求类型:** 同步请求

**请求参数:** 无

**成功响应 (200):**
```json
{
    "version": "v1",
    "tags": [
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
        "其他"
    ],
    "description": "V1版本标签体系（13类，侧重项目申请书，包含标题和摘要）",
    "tag_descriptions": {
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
    },
    "notes": {
        "标题": "标题可能为空，若文档中未找到标题则留空",
        "摘要": "若文档中未找到摘要，系统将自动调用LLM生成约500字的摘要"
    }
}
```

---

### 8. 获取支持的文件格式

**接口地址:** `GET /api/v1/supported_formats`

**请求类型:** 同步请求

**请求参数:** 无

**成功响应 (200):**
```json
{
    "supported_formats": [".txt", ".pdf", ".doc", ".docx"],
    "max_file_size_mb": 50,
    "ocr_strategy": "强制OCR（PDF/Word文件统一使用OCR提取，保证双栏、图片穿插等复杂排版的稳定性）",
    "notes": {
        ".txt": "纯文本文件，支持UTF-8、GBK等多种编码，直接读取",
        ".pdf": "PDF文档，强制使用OCR提取",
        ".doc": "Word 97-2003文档，强制OCR",
        ".docx": "Word 2007+文档，强制OCR"
    }
}
```

---

## 二次切分功能说明

### 功能概述

二次切分功能允许对已打标签的语义段落进行进一步切分，适用于需要更细粒度文本块的场景（如向量化存储、语义检索等）。

### 触发条件

仅在请求参数中传入 `chunk_size` 时触发二次切分。

### 切分方式

| 方式 | 参数值 | 说明 |
|------|--------|------|
| 滑动窗口切分 | sliding | 按固定大小切分，使用overlap保证上下文语义连贯。优先在句子边界处切分。 |
| 语义切分 | semantic | 利用大语言模型按语义进行智能切分，切分长度由chunk_size决定。 |

### Tag继承规则

同一语义段落切分出的所有Chunk必须继承该段落的预测Tag，保证标签一致性。

### 参数约束

- `chunk_size` 最小值为 50
- `overlap` 必须小于 `chunk_size`
- `overlap` 不能为负数

---

## HTTP状态码说明

| 状态码 | 说明 |
|--------|------|
| 200 | 请求成功 |
| 400 | 请求参数错误（文件格式不支持、缺少必填参数、参数值无效等） |
| 404 | 资源不存在（任务ID不存在） |
| 500 | 服务器内部错误 |
| 501 | 功能未实现（如V2版本） |

---

## 请求特性说明

### 同步处理 vs 异步处理

| 模式 | 接口 | 适用场景 | 特点 |
|------|------|----------|------|
| 同步 | `/api/v1/parse_document` | 小文件、纯文本 | 直接返回结果，简单方便 |
| 异步 | `/api/v1/parse_document/async` | 大文件、需要OCR | 立即返回任务ID，轮询获取结果 |

### 处理模式说明

| 模式 | 参数值 | 说明 |
|------|--------|------|
| 分离模式 | separate | 分段和分类分开调用LLM，可配合segment_mode使用 |
| 统一模式 | unified | 一次LLM调用同时完成分段和分类，效率较高 |

### 分段模式说明（仅separate模式有效）

| 模式 | 参数值 | 说明 |
|------|--------|------|
| 规则分段 | rule | 基于换行符和标点符号进行分段，速度快 |
| 语义分段 | semantic | 基于LLM进行语义分段，效果好但较慢 |

### 文件限制
- 支持格式：纯文本、TXT (.txt)、PDF (.pdf)、Word (.doc/.docx)
- MIME类型验证：
  - TXT: `text/plain`
  - PDF: `application/pdf`
  - DOC: `application/msword`
  - DOCX: `application/vnd.openxmlformats-officedocument.wordprocessingml.document`

---

## 完整接口调用示例

### curl命令

```bash
# 1. 纯文本解析（同步）
curl -X POST "http://121.43.245.185/docparse/api/v1/parse_document" \
  -F "business_line=semantic_check" \
  -F "version=v1" \
  -F "text=本项目研究意义重大，旨在解决人工智能领域的关键问题..."

# 2. 文件上传解析（同步）
curl -X POST "http://121.43.245.185/docparse/api/v1/parse_document" \
  -F "business_line=ai_review" \
  -F "version=v1" \
  -F "file=@/path/to/document.pdf"

# 3. 带二次切分的解析（同步）
curl -X POST "http://121.43.245.185/docparse/api/v1/parse_document" \
  -F "business_line=semantic_check" \
  -F "version=v1" \
  -F "chunk_size=500" \
  -F "overlap=50" \
  -F "chunk_method=sliding" \
  -F "text=本项目研究意义重大，旨在解决人工智能领域的关键问题..."

# 4. 使用语义切分方式
curl -X POST "http://121.43.245.185/docparse/api/v1/parse_document" \
  -F "business_line=semantic_check" \
  -F "version=v1" \
  -F "chunk_size=500" \
  -F "chunk_method=semantic" \
  -F "file=@/path/to/document.pdf"

# 5. 异步提交任务（带二次切分）
curl -X POST "http://121.43.245.185/docparse/api/v1/parse_document/async" \
  -F "business_line=semantic_check" \
  -F "version=v1" \
  -F "chunk_size=500" \
  -F "overlap=50" \
  -F "file=@/path/to/large_document.pdf"

# 6. 查询任务状态
curl -X GET "http://121.43.245.185/docparse/api/v1/tasks/status/{task_id}"

# 7. 获取任务结果
curl -X GET "http://121.43.245.185/docparse/api/v1/tasks/result/{task_id}"

# 8. 健康检查
curl -X GET "http://121.43.245.185/docparse/health"

# 9. 获取标签列表
curl -X GET "http://121.43.245.185/docparse/api/v1/tags"

# 10. 获取支持的格式
curl -X GET "http://121.43.245.185/docparse/api/v1/supported_formats"
```

### Python调用示例

```python
import requests
import time

BASE_URL = "http://121.43.245.185/docparse"

# ========== 同步调用示例 ==========
def sync_parse_text(text: str, chunk_size: int = None, overlap: int = None) -> dict:
    """
    同步解析纯文本
    
    Args:
        text: 待解析的文本
        chunk_size: 二次切分块大小（可选）
        overlap: 重叠区间（可选）
    """
    data = {
        "business_line": "semantic_check",
        "version": "v1",
        "text": text
    }
    
    # 添加切分参数
    if chunk_size:
        data["chunk_size"] = chunk_size
        if overlap:
            data["overlap"] = overlap
        data["chunk_method"] = "sliding"  # 或 "semantic"
    
    response = requests.post(
        f"{BASE_URL}/api/v1/parse_document",
        data=data
    )
    return response.json()


def sync_parse_file(file_path: str, chunk_size: int = None) -> dict:
    """同步解析文件"""
    data = {
        "business_line": "ai_review",
        "version": "v1"
    }
    
    if chunk_size:
        data["chunk_size"] = chunk_size
        data["overlap"] = chunk_size // 10  # 10%重叠
        data["chunk_method"] = "sliding"
    
    with open(file_path, "rb") as f:
        response = requests.post(
            f"{BASE_URL}/api/v1/parse_document",
            data=data,
            files={"file": f}
        )
    return response.json()


# ========== 异步调用示例 ==========
def async_parse_file(file_path: str, chunk_size: int = None) -> dict:
    """异步解析大文件"""
    
    data = {
        "business_line": "semantic_check",
        "version": "v1"
    }
    
    if chunk_size:
        data["chunk_size"] = chunk_size
        data["overlap"] = 50
        data["chunk_method"] = "sliding"
    
    # 1. 提交任务
    with open(file_path, "rb") as f:
        response = requests.post(
            f"{BASE_URL}/api/v1/parse_document/async",
            data=data,
            files={"file": f}
        )
    
    task_id = response.json()["task_id"]
    print(f"任务已提交: {task_id}")
    
    # 2. 轮询等待完成
    while True:
        status_resp = requests.get(f"{BASE_URL}/api/v1/tasks/status/{task_id}")
        status_data = status_resp.json()
        status = status_data["status"]
        progress = status_data.get("progress", 0)
        
        print(f"任务状态: {status}, 进度: {progress}%")
        
        if status in ["completed", "failed"]:
            break
        
        time.sleep(2)  # 每2秒查询一次
    
    # 3. 获取结果
    result_resp = requests.get(f"{BASE_URL}/api/v1/tasks/result/{task_id}")
    return result_resp.json()


# ========== 结果处理示例 ==========
def process_result(result: dict):
    """处理解析结果"""
    if result.get("status") == "success" or (result.get("result") and result["result"]["status"] == "success"):
        # 处理同步结果或异步结果
        data = result if "segments" in result else result.get("result", {})
        
        # 显示标题
        title = data.get("title")
        if title:
            print(f"标题: {title}")
        else:
            print("标题: (无)")
        
        # 显示摘要
        abstract = data.get("abstract")
        if abstract:
            print(f"摘要: {abstract[:100]}...")
        
        # 显示段落
        print(f"\n共 {len(data.get('segments', []))} 个段落:")
        for seg in data.get("segments", []):
            page_info = f" | 页码: {seg['pageIdx']}" if seg.get("pageIdx") is not None else ""
            print(f"\n[{seg['tag']}] (置信度: {seg['confidence']}{page_info})")
            print(f"  内容: {seg['content'][:50]}...")
            
            # 如果有chunks，显示切分信息
            if seg.get("chunks"):
                print(f"  切分为 {len(seg['chunks'])} 个块:")
                for chunk in seg["chunks"]:
                    print(f"    Chunk {chunk['chunk_id']}: {chunk['content'][:30]}...")
        
        # 显示切分配置
        chunk_info = data.get("chunk_info")
        if chunk_info:
            print(f"\n切分配置: {chunk_info}")
    else:
        print(f"解析失败: {result.get('error_message') or result.get('detail')}")


# ========== 使用示例 ==========
if __name__ == "__main__":
    # 示例1: 基础文本解析
    result = sync_parse_text("本项目研究意义重大，旨在解决人工智能领域的关键问题...")
    process_result(result)
    
    # 示例2: 带二次切分的文本解析
    result = sync_parse_text(
        "本项目研究意义重大，旨在解决人工智能领域的关键问题...",
        chunk_size=500,
        overlap=50
    )
    process_result(result)
    
    # 示例3: 异步解析大文件
    result = async_parse_file("/path/to/large_document.pdf", chunk_size=500)
    process_result(result)
```

---

## 常见问题

**Q: 请求是同步还是异步的？**
A: 提供两种模式：`/api/v1/parse_document` 为同步模式，`/api/v1/parse_document/async` 为异步模式。大文件建议使用异步模式。

**Q: 处理大文件时会超时吗？**
A: 同步接口超时时间为120秒。对于大文件（>10MB），建议使用异步接口避免超时。

**Q: 支持并发请求吗？**
A: 支持。生产环境使用 Gunicorn 多进程部署，可支持 QPS 50+。Worker 数量越多，并发能力越强。

**Q: text 和 file 参数可以同时提供吗？**
A: 可以。当同时提供时，优先处理 file 文件内容。

**Q: 标题为什么可能为空？**
A: 部分学术文档（如报告正文、研究内容节选等）可能不包含标题信息。若系统未识别到标题，则返回 `null`。

**Q: 摘要是原文提取的还是生成的？**
A: 系统首先尝试从原文中识别摘要段落。若原文中不存在摘要，则自动调用大语言模型根据全文内容生成约500字的摘要。

**Q: 页码信息是怎么获取的？什么时候会返回？**
A: 当通过 `file` 参数上传 PDF、DOC、DOCX 文件时，系统会在文本提取阶段追踪每页的内容边界，分段完成后根据段落内容匹配所在页码。`pageIdx` 表示该段落所在的起始页码（从1开始）。以下情况 `pageIdx` 为 `null`：纯文本输入（`text` 参数）、TXT 文件（无页码概念）、或页码信息无法获取时。

**Q: 什么时候需要使用二次切分功能？**
A: 当您需要更细粒度的文本块时（如向量化存储、语义检索、RAG应用等），可以传入 `chunk_size` 参数进行二次切分。切分后的每个块都会继承原段落的标签。

**Q: 滑动窗口切分和语义切分有什么区别？**
A: 
- **滑动窗口切分（sliding）**：按固定大小切分，速度快，使用 overlap 参数保证上下文连贯，优先在句子边界处切分
- **语义切分（semantic）**：使用LLM按语义边界智能切分，效果更好但速度较慢

---

*API文档版本: v1.2.0*  
*更新时间: 2026-04-16*
