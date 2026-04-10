# crawl_agent Source Code Reading Guide

> A code walkthrough for LangChain beginners. Follow the reading order below to progressively understand each file's purpose and core concepts.

## Recommended Reading Order

```
config.py → cache.py → warc_loader.py → llm_client.py → prompts.py → tools.py → batch.py → agent.py → main.py → web/
   Config      Cache       Data Loading      LLM Client       Prompts      Tool Defs     Batch Mode    Agent Mode     Entry Point    Visualization
```

**Why this order?** The first three files are pure Python with no LangChain involvement. Starting from `llm_client.py`, you begin encountering LangChain, and the guide gradually introduces tools, prompts, agents, and other concepts until you see how everything fits together.

---

## Stop 1: config.py (Configuration Hub)

**LangChain Concepts: None**

This file does something straightforward -- it defines constants and utility functions. But it serves as the foundation for all other files.

```python
# Three key constants
COLLECTIONS_DIR: Path   # Where WARC files are located
REPORTS_DIR: Path       # Where reports are output
CACHE_DIR: Path         # Where cache is stored

# Two key functions
get_available_dates()     # Scans directories, returns ["20260315", "20260316", ...]
get_consecutive_pairs()   # Returns [("20260315","20260316"), ("20260316","20260317"), ...]
```

**Key Points:**
- Reads API keys and endpoint from an `env` file in the project root
- `date_to_display("20260315")` returns `"2026-03-15"` -- just a format conversion
- All paths use `pathlib.Path` instead of string concatenation

---

## Stop 2: cache.py (Caching Layer)

**LangChain Concepts: None**

Parsing WARC files takes 30-60 seconds each time. This file ensures each date is parsed only once.

```python
get_parsed_collection("20260315")
# First call:  Parse WARC → save to .cache/parsed/20260315.json → return data
# Second call: Read JSON directly → validate checksum → return data
```

**Core Logic:**

```
1. Compute SHA-256 checksum of WARC files (filename + size)
2. Check whether cache file exists and checksum matches
3. Match → read cache directly and return
4. No match → call parse_warc_collection() to parse → write cache → return
```

**Key Points:**
- Cache invalidation: if WARC files change (new files or size changes), the checksum no longer matches, triggering automatic re-parsing
- The actual parsing work is delegated to `compare_script/crawl_compare.py`; this file only handles caching strategy

---

## Stop 3: warc_loader.py (Data Loading Layer)

**LangChain Concepts: None**

This is the core data access interface. **Both `tools.py` and `batch.py` retrieve data through it** -- they never touch WARC files directly.

```python
# The most central function
compare_two_dates("20260315", "20260316")
# Returns:
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

**Key Points:**
- `get_collection_data(date_str)` calls `cache.py` to get all URL data for a given date
- `compare_two_dates(old, new)` calls `get_collection_data` twice, then compares
- The comparison logic lives in `compare_script/crawl_compare.py`; this is just a thin wrapper
- Uses `sys.path.insert` to import modules from the `compare_script` directory (not elegant but effective)

---

## Stop 4: llm_client.py (LLM Client)

**LangChain Concepts: ChatOpenAI**

From here on you start encountering LangChain. This is the only place in the entire project where an LLM instance is created.

```python
from langchain_openai import ChatOpenAI

def get_llm(temperature=0.1) -> ChatOpenAI:
    return ChatOpenAI(
        model="glm-5.1",                           # Model name
        base_url="https://open.bigmodel.cn/...",     # Non-OpenAI endpoint
        api_key=os.environ["GLM_API_KEY"],           # Read from environment variable
        temperature=0.1,                             # Low temperature = more deterministic output
        max_tokens=4096,                             # Maximum generation length
    )
```

**Key Points:**
- `ChatOpenAI` is LangChain's wrapper around the OpenAI API. Since the Zhipu API is compatible with the OpenAI format, you only need to change `base_url` to use it
- `temperature=0.1`: analysis tasks don't need creativity; deterministic output is preferred
- `call_llm_with_retry()`: includes rate limiting and exponential backoff retry (2s -> 4s -> 8s)

**LangChain Knowledge Point:** LangChain's Chat Model interface is unified. `ChatOpenAI`, `ChatAnthropic`, and `ChatGoogle` all inherit from `BaseChatModel` and share the same `.invoke()` / `.batch()` methods. This means switching models only requires changing this one line.

---

## Stop 5: prompts.py (Prompt Templates)

**LangChain Concepts: Prompt Template**

Defines three sets of prompts for different scenarios:

### 1. SYSTEM_PROMPT (Role Definition)

```python
SYSTEM_PROMPT = """You are a web archive analyst specializing in AI coding tools.
You analyze daily web crawl snapshots of 9 AI coding tool websites...
"""
```

Tells the LLM "who you are," "what your task is," and "what the change classification criteria are."

### 2. ANALYSIS_PROMPT (Batch Analysis Template)

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

**Key Points:**
- `{system_prompt}`, `{stats}`, etc. are placeholders that get filled with real data via `.format()` in `batch.py`
- Specifies the output format: Executive Summary -> Statistics -> Domain Breakdown -> Significant Changes -> ...
- Each LLM call takes about 2000-4000 tokens of input (pre-processed summaries), not raw WARC data

### 3. INTERACTIVE_SYSTEM_PROMPT (Interactive Mode)

Built on top of SYSTEM_PROMPT with appended tool usage instructions, telling the LLM which tools are available.

---

## Stop 6: tools.py (Tool Definitions)

**LangChain Concepts: @tool Decorator, Pydantic Schema, BaseModel**

This is the core of the LangChain Agent -- it defines which functions the Agent can call.

### What is a Tool?

An Agent cannot directly manipulate data. It can only "think" and then "call tools." Each tool is a Python function with descriptive metadata that tells the Agent when to use it.

### How to Define a Tool?

```python
# Step 1: Define the parameter schema (Pydantic BaseModel)
class DatePairInput(BaseModel):
    old_date: str = Field(description="Earlier date in YYYYMMDD format")
    new_date: str = Field(description="Later date in YYYYMMDD format")

# Step 2: Register with the @tool decorator, specifying the parameter schema
@tool(args_schema=DatePairInput)
def compare_dates(old_date: str, new_date: str) -> str:
    """Compare crawl data between two dates and return a domain-grouped summary."""
    # Step 3: Function body -- call warc_loader to get data, format and return a string
    result = compare_two_dates(old_date, new_date)
    ...
    return summary  # Must return a string; the Agent understands results by reading text
```

**Key Points:**
- The `"""docstring"""` is crucial -- it is the tool description the Agent sees, which determines when it chooses this tool
- Parameters are defined using `Pydantic BaseModel`; LangChain automatically handles parameter validation and type conversion
- The return value must be a **string**, because the Agent understands results by reading text
- The 6 tools are ultimately collected into the `ALL_TOOLS` list:

```python
ALL_TOOLS = [
    compare_dates,       # Compare data between two dates
    get_page_changes,    # Detailed diff for a single page
    get_domain_changes,  # All changes for a given domain
    list_available_dates,# List all available dates
    analyze_trend,       # Time-series trend for a domain
    search_changes,      # Keyword search
]
```

**LangChain Knowledge Point:** `@tool` is the simplest way to create a tool. Under the hood it uses the `StructuredTool` class. You can also manually create a `StructuredTool(name=..., func=..., description=..., args_schema=...)`.

---

## Stop 7: batch.py (Batch Analysis Mode)

**LangChain Concepts: LLM Chain (Simplest Invocation Pattern)**

This file demonstrates the most basic LangChain usage: **construct a prompt -> call the LLM -> get the result**. No Agent, no tool selection.

### Core Flow

```python
def run_batch():
    llm = get_llm()                          # 1. Create LLM instance
    pairs = get_consecutive_pairs()           # 2. Get all date pairs

    for old_date, new_date in pairs:
        result = compare_two_dates(old, new)  # 3. Get comparison data

        prompt = ANALYSIS_PROMPT.format(      # 4. Fill the template
            system_prompt=SYSTEM_PROMPT,
            stats=_format_stats(result),
            domain_breakdown=_format_domain_breakdown(result),
            changes_data=_format_changes_data(result),
        )

        report = call_llm_with_retry(llm, prompt)  # 5. Call the LLM
        write_report(report)                       # 6. Write to file
```

**Key Points:**
- This is the **Chain pattern** (not Agent mode): fixed prompt construction -> LLM call, no autonomous decision-making
- `_format_stats()` and `_format_domain_breakdown()` convert data into Markdown tables and embed them into the prompt
- `_format_changes_data()` truncates to the first 15 changes (to control token count)
- Screenshot section: calls `screenshot.py` to use Playwright for capturing before/after screenshots of changed pages

---

## Stop 8: agent.py (Interactive Agent Mode)

**LangChain Concepts: ReAct Agent, AgentExecutor, create_react_agent**

This is the most essential LangChain usage in the entire project -- an Agent that can autonomously select tools.

### What is ReAct?

ReAct = **Re**asoning + **Act**ing. The Agent works in this loop:

```
Thought: The user is asking about Cursor's changes, I should get the data first
Action: get_domain_changes(domain="cursor.com", old_date="20260315", new_date="20260316")
Observation: Changes for cursor.com (1 URLs): cursor.com/pricing (similarity: 0.60)
Thought: Now I have the data, I can answer the user
Final Answer: Cursor had a major change on the pricing page between March 15 and 16...
```

### Code Breakdown

```python
def run_agent():
    # 1. Create the LLM
    llm = get_llm(temperature=0.2)  # Slightly higher temperature for interactive mode, more natural responses

    # 2. Create the Prompt (tell the Agent how to do the ReAct loop)
    prompt = PromptTemplate.from_template(REACT_TEMPLATE).partial(
        system_prompt=INTERACTIVE_SYSTEM_PROMPT
    )

    # 3. Create the Agent (LLM + tools + prompt -> an autonomous decision-making Agent)
    agent = create_react_agent(llm, ALL_TOOLS, prompt)

    # 4. Create the AgentExecutor (add execution control to the Agent)
    agent_executor = AgentExecutor(
        agent=agent,
        tools=ALL_TOOLS,
        max_iterations=10,        # Maximum 10 thinking rounds
        handle_parsing_errors=True, # Don't crash on LLM output format errors
        verbose=True,             # Print the thinking process
    )

    # 5. REPL loop
    while True:
        user_input = input("You: ")
        response = agent_executor.invoke({"input": user_input})
        print(f"Agent: {response['output']}")
```

### What Does REACT_TEMPLATE Look Like?

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

**Key Points:**
- `{tools}` is automatically replaced with the names and descriptions of all tools
- `{agent_scratchpad}` holds the Agent's previous thinking records (its "memory")
- `create_react_agent()` does the following: it teaches the LLM to output in this format, and LangChain handles parsing and execution
- `max_iterations=10`: prevents the Agent from entering an infinite loop

**LangChain Knowledge Points:**
- `create_react_agent` is one of LangChain's built-in Agent types
- Agent vs. Chain: a Chain has a fixed invocation path; an Agent autonomously decides which tools to call and how many times based on the input
- `AgentExecutor` is the Agent's runtime environment, managing tool calls, error handling, and iteration control

---

## Stop 9: main.py (CLI Entry Point)

**LangChain Concepts: None**

Pure CLI routing using `argparse` to dispatch to different modes:

```python
python crawl_agent/main.py batch      -> run_batch()
python crawl_agent/main.py agent      -> run_agent()
python crawl_agent/main.py visualize  -> run_server()
```

---

## Stop 10: web/ (Visualization Layer)

**LangChain Concepts: None**

This is the consumption layer with no LangChain involvement. It reads data produced by the previous steps and displays it on a web page.

```
web/
├── data_builder.py   # Calls warc_loader to get all data -> aggregates into JSON files
├── app.py            # Flask routes, serving API + static files
├── templates/
│   └── index.html    # Single-page app (Chart.js + Tailwind CSS)
└── static/
    ├── css/style.css
    └── data/         # Output from data_builder.py
```

**Data Flow:**
```
warc_loader.compare_two_dates()  ->  data_builder.build_all_data()
                                       -> overview.json    (aggregated statistics)
                                       -> timeline.json    (daily change count per domain)
                                       -> changes.json     (all text changes)
                                       -> stats.json       (per-pair statistics)
                                       -> dates.json       (date list)
                                       -> screenshots.json (screenshot index)

Flask app.py  ->  Reads these JSONs  ->  Serves them to the frontend via API routes
             ->  /api/report/     ->  Reads markdown reports -> converts to HTML
             ->  /api/screenshots/ ->  Serves PNG files
```

---

## LangChain Concepts Quick Reference

| File | LangChain Concept | Description |
|------|-------------------|-------------|
| llm_client.py | `ChatOpenAI` | LLM client wrapper |
| prompts.py | Prompt Template | Text templates with `{variable}` placeholders |
| tools.py | `@tool`, `BaseModel` | Wraps Python functions into Agent-callable tools |
| batch.py | LLM Chain | Fixed pipeline: construct prompt -> call LLM -> get result |
| agent.py | `create_react_agent`, `AgentExecutor` | Autonomous decision-making Agent, looping through thinking + acting |

## Debugging Tips

### 1. Inspect the Agent's Thinking Process

```bash
python crawl_agent/main.py agent
# verbose=True will print:
# > Entering new AgentExecutor chain...
# Thought: ...
# Action: compare_dates(...)
# Observation: ...
```

### 2. Test a Single Tool in Isolation

```python
from crawl_agent.tools import compare_dates, list_available_dates
print(list_available_dates.invoke({}))
print(compare_dates.invoke({"old_date": "20260315", "new_date": "20260316"}))
```

### 3. Call the LLM Directly (Bypassing the Agent)

```python
from crawl_agent.llm_client import get_llm
llm = get_llm()
response = llm.invoke("What are the main changes in Cursor's pricing?")
print(response.content)
```

### 4. Visual Debugging

```bash
python visualize.py --build-data
# View all comparison data visually in the browser
```
