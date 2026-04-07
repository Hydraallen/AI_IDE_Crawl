# Web Crawl Comparison Tool

比较两次 web archive (WARC/WACZ) 抓取的内容变化。

## 快速使用

```bash
cd /Volumes/EDITH/Bots/F.R.I.D.A.Y./workspace/AI Coding Tools_Project/compare_script
source venv/bin/activate

python crawl_compare.py \
  --old ../crawls/collections/crawl-20260315 \
  --new ../crawls/collections/crawl-20260316 \
  --output ./reports
```

## 输出文件

- `summary_report.md` - 变化统计摘要
- `detailed_changes.md` - 详细的文本内容变化
- `comparison_data.json` - JSON 格式数据（便于进一步分析）

---

## 脚本逻辑详解

### 整体流程

```
┌─────────────────────┐
│ 1. 解析旧 Collection │
│    (WARC → URL数据)  │
└──────────┬──────────┘
           │
┌──────────▼──────────┐
│ 2. 解析新 Collection │
└──────────┬──────────┘
           │
┌──────────▼──────────┐
│ 3. 比较              │
│    - URL 列表对比    │
│    - 内容哈希对比    │
│    - 文本内容对比    │
└──────────┬──────────┘
           │
┌──────────▼──────────┐
│ 4. 过滤噪音          │
│    - Cloudflare 页面 │
│    - 格式变化        │
│    - 微小修改        │
└──────────┬──────────┘
           │
┌──────────▼──────────┐
│ 5. 生成报告          │
└─────────────────────┘
```

### 核心模块

#### 1. WARC 解析 (`parse_warc_collection`)

```
输入: collection/ 文件夹路径
     └── archive/
         ├── *.warc.gz
         └── ...

处理:
1. 遍历所有 .warc.gz 文件
2. 解压并迭代每个 WARC record
3. 提取:
   - URL (WARC-Target-URI)
   - 内容 (HTTP response body)
   - Content-Type
   - 内容哈希 (MD5)
4. 如果是 HTML:
   - 提取标题
   - 提取可读文本 (去除脚本、样式、导航等)
   - 计算文本哈希

输出: {url: {hash, size, content_type, title, text, text_hash, ...}}
```

#### 2. 文本提取 (`extract_readable_text`)

```
输入: HTML 内容
处理:
1. 解析 HTML (BeautifulSoup)
2. 移除非内容元素:
   - script, style, noscript
   - iframe, svg, canvas
   - nav, header, footer, aside
   - 常见 UI 类名 (.nav, .menu, .sidebar...)
3. 提取主内容区 (main > article > body)
4. 清理文本:
   - 去除过短行
   - 去除 UI 元素 ("Skip to content", "Menu"...)
5. 规范化空白字符

输出: (title, clean_text)
```

#### 3. 内容比较 (`compare_collections`)

```
输入: data1 (旧), data2 (新)

URL 层面:
- added = urls2 - urls1    (新增页面)
- removed = urls1 - urls2  (删除页面)
- common = urls1 ∩ urls2   (共同页面)

内容层面:
for url in common:
    if hash1 != hash2:
        → 页面内容变化

输出: {added, removed, changed, stats}
```

#### 4. 文本变化分析 (`analyze_text_changes`)

```
输入: data1 (旧), data2 (新)

for url in common:
    if text_hash 相同:
        跳过 (文本无变化)
    
    if 是 Cloudflare 验证页:
        跳过 (噪音)
    
    计算文本相似度 (difflib)
    
    if 相似度 > 98%:
        跳过 (只是格式变化)
    
    if 变化行数 < 3:
        跳过 (微小修改)
    
    记录为真实文本变化:
        - 相似度
        - 新增/删除的内容
        - 行数统计

输出: {text_changes, stats}
```

### 过滤策略

| 过滤类型 | 检测方法 | 原因 |
|---------|---------|------|
| Cloudflare 验证页 | 标题/URL 包含 "just a moment" 等 | 非实际内容 |
| 格式变化 | 文本相似度 > 98% | 只是 HTML 结构变化 |
| 微小修改 | 变化行数 < 3 | 可能是日期、计数器等 |
| 非 HTML | Content-Type 检查 | API 响应、图片等 |
| 短页面 | 文本长度 < 100 | 无意义内容 |

### 域名分类

```python
DOMAIN_PATTERNS = {
    'windsurf': ['windsurf.com', 'docs.windsurf.com'],
    'openclaw': ['openclaw.ai', 'docs.openclaw.ai'],
    'cursor': ['cursor.com', 'cursor.sh'],
    'claude': ['claude.com', 'anthropic.com'],
    'replit': ['replit.com'],
    # ...
}
```

### 内容类型分类

```python
def get_content_type_category(content_type, url):
    if 'analytics' in url or 'tracking' in url:
        return 'tracking'
    elif '/auth' in url or '/login' in url:
        return 'auth'
    elif '.js' in url or '.css' in url:
        return 'static_asset'
    elif 'youtube.com' in url:
        return 'video_embed'
    elif '/api/' in url:
        return 'api'
    else:
        return 'page'
```

---

## 配置参数

```python
# 最小文本长度（短于这个值的页面被忽略）
MIN_TEXT_LENGTH = 100

# 相似度阈值（高于此值视为格式变化）
SIMILARITY_THRESHOLD = 0.98

# 最小变化行数（少于这个视为微小修改）
MIN_CHANGED_LINES = 3
```

---

## 数据流示例

```
Collection 1 (crawl-20260315)
    │
    ▼ parse_warc_collection
{
  "https://docs.openclaw.ai/tools/firecrawl": {
    "hash": "abc123",
    "text": "Configure Firecrawl...",
    "text_hash": "def456"
  }
}

Collection 2 (crawl-20260316)
    │
    ▼ parse_warc_collection
{
  "https://docs.openclaw.ai/tools/firecrawl": {
    "hash": "xyz789",        ← hash 变了
    "text": "Configure Firecrawl search...",
    "text_hash": "ghi012"    ← text_hash 也变了
  }
}

    │
    ▼ analyze_text_changes
{
  "url": "https://docs.openclaw.ai/tools/firecrawl",
  "similarity": 0.68,        ← 68% 相似，有实质变化
  "added": ["Configure Firecrawl search", ...],
  "removed": ["Configure Firecrawl", ...]
}
```

---

## 扩展

### 添加新的域名分类

编辑 `DOMAIN_PATTERNS`:

```python
DOMAIN_PATTERNS['newsite'] = ['newsite.com', 'docs.newsite.com']
```

### 调整过滤严格程度

```python
# 更严格（只报告大变化）
SIMILARITY_THRESHOLD = 0.90
MIN_CHANGED_LINES = 10

# 更宽松（报告更多小变化）
SIMILARITY_THRESHOLD = 0.99
MIN_CHANGED_LINES = 1
```
