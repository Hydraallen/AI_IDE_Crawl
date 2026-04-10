# crawl_agent 源码阅读指南

> 面向 LangChain 初学者的代码导读。按照阅读顺序，逐步拆解每个文件的作用和核心概念。

## 推荐阅读顺序

```
config.py → cache.py → warc_loader.py → llm_client.py → prompts.py → tools.py → batch.py → agent.py → main.py → web/
   配置        缓存        数据加载         LLM 客户端       提示词        工具定义      批量模式     Agent 模式     入口路由     可视化
```

**为什么是这个顺序？** 前三个文件是纯 Python，不涉及 LangChain。从 `llm_client.py` 开始接触 LangChain，逐步引入工具、Prompt、Agent 等概念，最终看到它们如何组装在一起。

---

## 第 1 站：config.py（配置中心）

**LangChain 概念：无**

这个文件做的事情很简单——定义常量和工具函数。但它是所有其他文件的基础。

```python
# 三个关键常量
COLLECTIONS_DIR: Path   # WARC 文件在哪
REPORTS_DIR: Path       # 报告输出到哪
CACHE_DIR: Path         # 缓存存到哪

# 两个关键函数
get_available_dates()     # 扫描文件夹，返回 ["20260315", "20260316", ...]
get_consecutive_pairs()   # 返回 [("20260315","20260316"), ("20260316","20260317"), ...]
```

**要点：**
- 从项目根目录的 `env` 文件读取 API 密钥和 endpoint
- `date_to_display("20260315")` → `"2026-03-15"`，只是格式转换
- 所有路径都用 `pathlib.Path`，不用字符串拼接

---

## 第 2 站：cache.py（缓存层）

**LangChain 概念：无**

每次解析 WARC 文件需要 30-60 秒。这个文件让每个日期只解析一次。

```python
get_parsed_collection("20260315")
# 第一次：解析 WARC → 存到 .cache/parsed/20260315.json → 返回数据
# 第二次：直接读 JSON → 校验 checksum → 返回数据
```

**核心逻辑：**

```
1. 计算 WARC 文件的 SHA-256 checksum（文件名+大小）
2. 检查缓存文件是否存在且 checksum 匹配
3. 匹配 → 直接读缓存返回
4. 不匹配 → 调用 parse_warc_collection() 解析 → 写缓存 → 返回
```

**要点：**
- 缓存失效机制：如果 WARC 文件变了（新增或大小改变），checksum 不匹配，自动重新解析
- 实际的解析工作委托给 `compare_script/crawl_compare.py`，这个文件只负责缓存策略

---

## 第 3 站：warc_loader.py（数据加载层）

**LangChain 概念：无**

这是数据访问的核心接口。**tools.py 和 batch.py 都通过它获取数据**，不直接碰 WARC 文件。

```python
# 最核心的函数
compare_two_dates("20260315", "20260316")
# 返回:
{
    "comparison": {
        "stats": {"added_count": 2529, "removed_count": 2913, ...}
    },
    "text_changes": [
        {"url": "https://cursor.com/pricing", "similarity": 0.60, "added": [...], "removed": [...]}
    ],
    "old_date": "20260315",
    "new_date": "20260316"
}
```

**要点：**
- `get_collection_data(date_str)` → 调用 cache.py 获取某天的所有 URL 数据
- `compare_two_dates(old, new)` → 调用两次 `get_collection_data`，然后比较
- 比较逻辑在 `compare_script/crawl_compare.py` 里，这里只是薄封装
- 用 `sys.path.insert` 来导入 `compare_script` 目录下的模块（不优雅但有效）

---

## 第 4 站：llm_client.py（LLM 客户端）

**LangChain 概念：ChatOpenAI**

从这里开始接触 LangChain。这是整个项目中唯一创建 LLM 实例的地方。

```python
from langchain_openai import ChatOpenAI

def get_llm(temperature=0.1) -> ChatOpenAI:
    return ChatOpenAI(
        model="glm-5.1",                           # 模型名
        base_url="https://open.bigmodel.cn/...",     # 非 OpenAI 的 endpoint
        api_key=os.environ["GLM_API_KEY"],           # 从环境变量读
        temperature=0.1,                             # 低温度 = 更确定性的输出
        max_tokens=4096,                             # 最大生成长度
    )
```

**要点：**
- `ChatOpenAI` 是 LangChain 对 OpenAI API 的封装。因为智谱 API 兼容 OpenAI 格式，所以只需要改 `base_url` 就能用
- `temperature=0.1`：分析任务不需要创造力，要确定性输出
- `call_llm_with_retry()`：带速率限制 + 指数退避重试（2s → 4s → 8s）

**LangChain 知识点：** LangChain 的 Chat Model 接口是统一的。`ChatOpenAI`、`ChatAnthropic`、`ChatGoogle` 都继承自 `BaseChatModel`，有相同的 `.invoke()` / `.batch()` 方法。这意味着换模型只需要改这一行。

---

## 第 5 站：prompts.py（提示词模板）

**LangChain 概念：Prompt Template**

定义了三套提示词，给不同场景用：

### 1. SYSTEM_PROMPT（角色设定）

```python
SYSTEM_PROMPT = """You are a web archive analyst specializing in AI coding tools.
You analyze daily web crawl snapshots of 9 AI coding tool websites...
"""
```

告诉 LLM "你是谁"、"你的任务是什么"、"变化的分类标准是什么"。

### 2. ANALYSIS_PROMPT（批量分析模板）

```python
ANALYSIS_PROMPT = """{system_prompt}

## Statistics
{stats}

## Domain Breakdown
{domain_breakdown}

## Changes Data
{changes_data}
"""
```

**要点：**
- `{system_prompt}`、`{stats}` 等是占位符，在 `batch.py` 中用 `.format()` 填入真实数据
- 指定了输出格式：Executive Summary → Statistics → Domain Breakdown → Significant Changes → ...
- 每次 LLM 调用输入约 2000-4000 tokens（预处理后的摘要），不是原始 WARC 数据

### 3. INTERACTIVE_SYSTEM_PROMPT（交互模式）

在 SYSTEM_PROMPT 基础上追加了工具使用指南，告诉 LLM 有哪些工具可用。

---

## 第 6 站：tools.py（工具定义）

**LangChain 概念：@tool 装饰器、Pydantic Schema、BaseModel**

这是 LangChain Agent 的核心——定义 Agent 可以调用哪些函数。

### 工具是什么？

Agent 本身不能直接操作数据。它只能"思考"然后"调用工具"。每个工具就是一个 Python 函数，加上描述信息，让 Agent 知道什么时候该用它。

### 怎么定义一个工具？

```python
# Step 1: 定义参数 Schema（Pydantic BaseModel）
class DatePairInput(BaseModel):
    old_date: str = Field(description="Earlier date in YYYYMMDD format")
    new_date: str = Field(description="Later date in YYYYMMDD format")

# Step 2: 用 @tool 装饰器注册，指定参数 Schema
@tool(args_schema=DatePairInput)
def compare_dates(old_date: str, new_date: str) -> str:
    """Compare crawl data between two dates and return a domain-grouped summary."""
    # Step 3: 函数体——调用 warc_loader 获取数据，格式化返回字符串
    result = compare_two_dates(old_date, new_date)
    ...
    return summary  # 必须返回字符串，Agent 通过文本理解结果
```

**要点：**
- `"""docstring"""` 很重要——这就是 Agent 看到的工具描述，决定了它什么时候选这个工具
- 参数用 `Pydantic BaseModel` 定义，LangChain 会自动做参数校验和类型转换
- 返回值必须是 **字符串**，因为 Agent 通过阅读文本来理解结果
- 6 个工具最终组成 `ALL_TOOLS` 列表：

```python
ALL_TOOLS = [
    compare_dates,       # 对比两天数据
    get_page_changes,    # 单个页面的详细 diff
    get_domain_changes,  # 某个域名的所有变化
    list_available_dates,# 列出所有日期
    analyze_trend,       # 域名的时间序列趋势
    search_changes,      # 关键词搜索
]
```

**LangChain 知识点：** `@tool` 是创建工具最简单的方式。底层是 `StructuredTool` 类。你也可以手动创建 `StructuredTool(name=..., func=..., description=..., args_schema=...)`。

---

## 第 7 站：batch.py（批量分析模式）

**LangChain 概念：LLM Chain（最简单的调用模式）**

这个文件展示了 LangChain 最基本的用法：**构造 prompt → 调用 LLM → 获取结果**。不涉及 Agent，不涉及工具选择。

### 核心流程

```python
def run_batch():
    llm = get_llm()                          # 1. 创建 LLM 实例
    pairs = get_consecutive_pairs()           # 2. 获取所有日期对

    for old_date, new_date in pairs:
        result = compare_two_dates(old, new)  # 3. 获取比较数据

        prompt = ANALYSIS_PROMPT.format(      # 4. 填充模板
            system_prompt=SYSTEM_PROMPT,
            stats=_format_stats(result),
            domain_breakdown=_format_domain_breakdown(result),
            changes_data=_format_changes_data(result),
        )

        report = call_llm_with_retry(llm, prompt)  # 5. 调用 LLM
        write_report(report)                       # 6. 写入文件
```

**要点：**
- 这是 **Chain 模式**（不是 Agent 模式）：固定的 prompt 构造 → LLM 调用，没有自主决策
- `_format_stats()`、`_format_domain_breakdown()` 把数据转成 Markdown 表格，塞进 prompt
- `_format_changes_data()` 截断到前 15 个变化（控制 token 数）
- 截图部分：调用 `screenshot.py` 用 Playwright 截取变化页面的 before/after

---

## 第 8 站：agent.py（交互 Agent 模式）

**LangChain 概念：ReAct Agent、AgentExecutor、create_react_agent**

这是整个项目最核心的 LangChain 用法——一个能自主选择工具的 Agent。

### ReAct 是什么？

ReAct = **Re**asoning + **Act**ing。Agent 按这个循环工作：

```
Thought: 用户问的是 Cursor 的变化，我应该先获取数据
Action: get_domain_changes(domain="cursor.com", old_date="20260315", new_date="20260316")
Observation: Changes for cursor.com (1 URLs): cursor.com/pricing (similarity: 0.60)
Thought: 现在我有数据了，可以回答用户
Final Answer: Cursor 在 3 月 15 日到 16 日之间，定价页面发生了重大变化...
```

### 代码拆解

```python
def run_agent():
    # 1. 创建 LLM
    llm = get_llm(temperature=0.2)  # 交互模式温度稍高，回答更自然

    # 2. 创建 Prompt（告诉 Agent 怎么做 ReAct 循环）
    prompt = PromptTemplate.from_template(REACT_TEMPLATE).partial(
        system_prompt=INTERACTIVE_SYSTEM_PROMPT
    )

    # 3. 创建 Agent（LLM + 工具 + Prompt → 一个能自主决策的 Agent）
    agent = create_react_agent(llm, ALL_TOOLS, prompt)

    # 4. 创建 AgentExecutor（给 Agent 加上执行控制）
    agent_executor = AgentExecutor(
        agent=agent,
        tools=ALL_TOOLS,
        max_iterations=10,        # 最多思考 10 轮
        handle_parsing_errors=True, # LLM 输出格式错误时不崩溃
        verbose=True,             # 打印思考过程
    )

    # 5. REPL 循环
    while True:
        user_input = input("You: ")
        response = agent_executor.invoke({"input": user_input})
        print(f"Agent: {response['output']}")
```

### REACT_TEMPLATE 长什么样？

```
{system_prompt}

You have access to the following tools:
{tools}

Use the following format:
Question: the input question
Thought: think about what to do
Action: the tool to use
Action Input: JSON input for the tool
Observation: the result
... (repeat)
Thought: I now know the final answer
Final Answer: the answer

Question: {input}
Thought: {agent_scratchpad}
```

**要点：**
- `{tools}` 被自动替换为所有工具的名称和描述
- `{agent_scratchpad}` 是 Agent 之前的思考记录（"记忆"）
- `create_react_agent()` 做的事情：让 LLM 学会按这个格式输出，LangChain 负责解析和执行
- `max_iterations=10`：防止 Agent 陷入死循环

**LangChain 知识点：**
- `create_react_agent` 是 LangChain 内置的 Agent 类型之一
- Agent vs Chain 的区别：Chain 的调用路径是固定的，Agent 会根据输入自主选择调哪些工具、调几次
- `AgentExecutor` 是 Agent 的运行时环境，管理工具调用、错误处理、迭代控制

---

## 第 9 站：main.py（CLI 入口）

**LangChain 概念：无**

纯 CLI 路由，用 `argparse` 分发到不同模式：

```python
python crawl_agent/main.py batch      → run_batch()
python crawl_agent/main.py agent      → run_agent()
python crawl_agent/main.py visualize  → run_server()
```

---

## 第 10 站：web/（可视化层）

**LangChain 概念：无**

这是消费层，不涉及 LangChain。它读取前面步骤产生的数据，展示在网页上。

```
web/
├── data_builder.py   # 调用 warc_loader 获取所有数据 → 聚合成 JSON 文件
├── app.py            # Flask 路由，提供 API + 静态文件服务
├── templates/
│   └── index.html    # 单页应用（Chart.js + Tailwind CSS）
└── static/
    ├── css/style.css
    └── data/         # data_builder.py 的输出
```

**数据流：**
```
warc_loader.compare_two_dates()  →  data_builder.build_all_data()
                                    → overview.json    (聚合统计)
                                    → timeline.json    (每域名每日变化数)
                                    → changes.json     (所有文本变化)
                                    → stats.json       (每对统计)
                                    → dates.json       (日期列表)
                                    → screenshots.json (截图索引)

Flask app.py  →  读取这些 JSON  →  通过 API 路由提供给前端
             →  /api/report/     →  读 markdown 报告 → 转 HTML
             →  /api/screenshots/ →  提供 PNG 文件
```

---

## LangChain 概念速查表

| 文件 | LangChain 概念 | 说明 |
|------|----------------|------|
| llm_client.py | `ChatOpenAI` | LLM 客户端封装 |
| prompts.py | Prompt Template | 用 `{variable}` 占位的文本模板 |
| tools.py | `@tool`、`BaseModel` | 把 Python 函数包装成 Agent 可调用的工具 |
| batch.py | LLM Chain | 固定流程：构造 prompt → 调 LLM → 取结果 |
| agent.py | `create_react_agent`、`AgentExecutor` | 自主决策 Agent，循环思考+行动 |

## 调试技巧

### 1. 查看 Agent 的思考过程

```bash
python crawl_agent/main.py agent
# verbose=True 会打印：
# > Entering new AgentExecutor chain...
# Thought: ...
# Action: compare_dates(...)
# Observation: ...
```

### 2. 单独测试某个工具

```python
from crawl_agent.tools import compare_dates, list_available_dates
print(list_available_dates.invoke({}))
print(compare_dates.invoke({"old_date": "20260315", "new_date": "20260316"}))
```

### 3. 直接调用 LLM（不经过 Agent）

```python
from crawl_agent.llm_client import get_llm
llm = get_llm()
response = llm.invoke("What are the main changes in Cursor's pricing?")
print(response.content)
```

### 4. 可视化调试

```bash
python visualize.py --build-data
# 在浏览器中直观查看所有比较数据
```
