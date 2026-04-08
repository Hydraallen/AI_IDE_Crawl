from langchain.agents import AgentExecutor, create_react_agent
from langchain_core.prompts import PromptTemplate

from crawl_agent.llm_client import get_llm
from crawl_agent.tools import ALL_TOOLS
from crawl_agent.prompts import INTERACTIVE_SYSTEM_PROMPT


REACT_TEMPLATE = """{system_prompt}

You have access to the following tools:

{tools}

Use the following format:

Question: the input question you must answer
Thought: you should always think about what to do
Action: the action to take, should be one of [{tool_names}]
Action Input: the input to the action as a JSON object matching the tool's schema
Observation: the result of the action
... (this Thought/Action/Action Input/Observation can repeat N times)
Thought: I now know the final answer
Final Answer: the final answer to the original input question

Begin!

Question: {input}
Thought: {agent_scratchpad}"""


def run_agent() -> None:
    """Start the interactive REPL agent."""
    llm = get_llm(temperature=0.2)

    prompt = PromptTemplate.from_template(REACT_TEMPLATE).partial(
        system_prompt=INTERACTIVE_SYSTEM_PROMPT
    )

    agent = create_react_agent(llm, ALL_TOOLS, prompt)

    agent_executor = AgentExecutor(
        agent=agent,
        tools=ALL_TOOLS,
        max_iterations=10,
        handle_parsing_errors=True,
        verbose=True,
    )

    print("Crawl Agent - Interactive Mode")
    print("Ask questions about web crawl changes. Type 'quit' to exit.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input or user_input.lower() in ("quit", "exit", "q"):
            print("Goodbye!")
            break

        try:
            response = agent_executor.invoke({"input": user_input})
            print(f"\nAgent: {response['output']}\n")
        except Exception as e:
            print(f"\nError: {e}\n")
