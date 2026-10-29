import os
os.environ.setdefault('PYDANTIC_AI_NO_BANNER', '1')   # hides the banner pydantic-ai prints on every run

from dotenv import load_dotenv
from pydantic_ai import Agent, UsageLimits, capture_run_messages
from pydantic_ai.exceptions import AgentRunError, UsageLimitExceeded, ToolFailed
from pydantic_ai.messages import ModelResponse, ToolCallPart
from config import SYSTEM_PROMPT, MAX_TOKENS, MAX_STEPS, BUDGET, MODEL, USD_INR_CONVERSION_RATE
from tools import all_tools, allowed_expression, calculate, fetch_url, read_file

load_dotenv()

agent = Agent(
    f"anthropic:{MODEL['id']}",
    system_prompt=SYSTEM_PROMPT,
    model_settings={'max_tokens': MAX_TOKENS},
    retries=2,          # bad arguments may go back to the model twice, then the run fails
    tool_timeout=15,    # backstop; fetch_url's own httpx timeout (10s) fires first
)


# Without the try/except, an exception in a tool crashes the whole run.
# ToolFailed sends the error to the model instead, like is_error in agent.py.
descriptions = {t['name']: t['description'] for t in all_tools}


@agent.tool_plain(name='calculate', description=descriptions['calculate'])
def calculate_tool(first_input: float, second_input: float, expression: allowed_expression) -> float:
    try:
        return calculate(first_input, second_input, expression)
    except Exception as e:
        raise ToolFailed(f"{type(e).__name__}: {e}")


@agent.tool_plain(name='fetch_url', description=descriptions['fetch_url'])
def fetch_url_tool(url: str) -> str:
    try:
        return fetch_url(url)
    except Exception as e:
        raise ToolFailed(f"{type(e).__name__}: {e}")


@agent.tool_plain(name='read_file', description=descriptions['read_file'])
def read_file_tool(file_name: str) -> str:
    try:
        return read_file(file_name)
    except Exception as e:
        raise ToolFailed(f"{type(e).__name__}: {e}")


def run(task, model=MODEL) -> dict:
    """Same shape as agent.py's finish(), so both go through one eval."""
    with capture_run_messages() as messages:   # kept even when the run raises, for steps/tokens/₹
        try:
            r = agent.run_sync(task, model=f"anthropic:{model['id']}",
                               usage_limits=UsageLimits(request_limit=MAX_STEPS, total_tokens_limit=BUDGET))
            answer = r.output
            stop = 'truncated' if r.response.finish_reason == 'length' else 'done'
        except UsageLimitExceeded as e:
            answer, stop = str(e), 'max_steps' if 'request_limit' in str(e) else 'budget_hit'
        except AgentRunError as e:   # a tool out of retries, an API error
            answer, stop = str(e), 'error'

    responses = [m for m in messages if isinstance(m, ModelResponse)]
    tokens_in = sum(m.usage.input_tokens for m in responses)
    tokens_out = sum(m.usage.output_tokens for m in responses)
    cost = (tokens_in * model['cost']['in'] + tokens_out * model['cost']['out']) / 1_000_000
    return {
        'stop_reason': stop,
        'task': task,
        'answer': answer,
        'steps': len(responses),
        'tokens': tokens_in + tokens_out,
        'cost_inr': cost * USD_INR_CONVERSION_RATE,
        'tools': [p.tool_name for m in responses for p in m.parts if isinstance(p, ToolCallPart)],
    }


if __name__ == "__main__":
    print(run("Read email.txt, then tell me what 1234 * 56 is using the calculate tool."))
