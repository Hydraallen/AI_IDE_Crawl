import os
import time

from langchain_openai import ChatOpenAI

from crawl_agent.config import GLM_ENDPOINT, GLM_API_KEY, GLM_MODEL_NAME


def get_llm(temperature: float = 0.1) -> ChatOpenAI:
    """Create a ChatOpenAI instance configured for GLM-5.1."""
    return ChatOpenAI(
        model=GLM_MODEL_NAME,
        base_url=GLM_ENDPOINT,
        api_key=GLM_API_KEY,
        temperature=temperature,
        max_tokens=4096,
        request_timeout=60,
    )


_last_call_time: float = 0.0
_RATE_LIMIT_DELAY: float = 1.0


def call_llm_with_retry(llm: ChatOpenAI, prompt: str, max_retries: int = 3) -> str:
    """Call LLM with rate limiting and exponential backoff."""
    global _last_call_time

    elapsed = time.time() - _last_call_time
    if elapsed < _RATE_LIMIT_DELAY:
        time.sleep(_RATE_LIMIT_DELAY - elapsed)

    for attempt in range(max_retries):
        try:
            response = llm.invoke(prompt)
            _last_call_time = time.time()
            return response.content
        except Exception as e:
            wait = 2 ** (attempt + 1)
            print(f"  LLM error (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                print(f"  Retrying in {wait}s...")
                time.sleep(wait)
            else:
                print(f"  Failed after {max_retries} attempts, skipping.")
                raise
    return ""
