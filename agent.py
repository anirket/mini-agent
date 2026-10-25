import os
import json
import anthropic
from anthropic import Anthropic
from config import MAX_TOKENS, MODEL, SYSTEM_PROMPT, MAX_STEPS, USD_INR_CONVERSION_RATE, BUDGET, HISTORY_CEILING, KEEP_LAST
from dotenv import load_dotenv
from tools import all_tools, read_file, fetch_url, calculate, calculate_input, fetch_url_input, read_file_input
from pydantic import ValidationError
from budget import count_fixed, count_total, compact

allowed_tools = [tool['name'] for tool in all_tools]


def show_budget(client, messages, step, fixed, cost) -> int:
    """Counts the request before sending it and prints where the tokens go. Returns the total."""
    total = count_total(client, messages)
    history = total - fixed['system'] - fixed['tools']
    print(f"step {step} | system {fixed['system']} | tools {fixed['tools']} | "
          f"history {history}/{HISTORY_CEILING} | total {total} | ₹{cost * USD_INR_CONVERSION_RATE:.2f} so far")
    return total

def execute_tool(name: str, input: dict) -> tuple:
    is_error = False
    print(f">>> Tool Called: {name} with input {input}")
    try:
        if name == 'calculate':
            args = calculate_input(**input)
            content = calculate(**args.model_dump())
        elif name == 'fetch_url':
            args = fetch_url_input(**input)
            content = fetch_url(**args.model_dump())
        elif name == 'read_file':
            args = read_file_input(**input)
            content = read_file(**args.model_dump())
        else:
            content = f'{name} is not a Valid Tool, Valid tools are {allowed_tools}'
            is_error = True
    except ValidationError as e:
        content = f"Error: Input params are not correct: {e}"
        is_error = True
    except Exception as e:
        content = f"Error: {type(e)}: {e}"
        is_error = True
    return (content, is_error)

def call_tool(tool_use):
    content, is_error = execute_tool(tool_use.name, tool_use.input)
    return {
        'type': 'tool_result',
        'tool_use_id': tool_use.id,
        'content': str(content),
        'is_error': is_error
    }


def finish (stop_reason, task, answer, steps, tokens, cost):
    result = {
        'stop_reason': stop_reason,
        'task': task,
        'answer': answer,
        'steps': steps,
        'tokens': tokens,
        'cost_inr': cost * USD_INR_CONVERSION_RATE
    }

    with open('run.jsonl', 'a') as f:
        f.write(json.dumps(result) + '\n')
    return result 



def call_llm(client: Anthropic, messages: list) -> dict:
    tokens = 0
    cost = 0
    result = ''
    task = messages[0]['content']   # saved, because a summary rewrites messages[0]
    for steps in range(MAX_STEPS):
        try:
            if steps == 0:
                fixed = count_fixed(client)   # system prompt + tools never change, so count them once
            estimate = show_budget(client, messages, steps + 1, fixed, cost)

            # History too big: keep the task + last KEEP_LAST messages, summarise the rest
            history = estimate - fixed['system'] - fixed['tools']
            if history > HISTORY_CEILING and len(messages) > KEEP_LAST + 1:
                messages, usage = compact(client, task, messages, KEEP_LAST)
                tokens += usage.input_tokens + usage.output_tokens
                cost += (usage.input_tokens * MODEL['cost']['in'] + usage.output_tokens * MODEL['cost']['out']) / 1_000_000
                print(f">>> summarised: history was {history} tokens")
                estimate = show_budget(client, messages, steps + 1, fixed, cost)

            response = client.messages.create(
                model=MODEL['id'],
                system=SYSTEM_PROMPT,
                max_tokens=MAX_TOKENS,
                messages=messages,
                tools=all_tools
            )
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:   # RateLimitError is an APIStatusError
            result = f"API error: {e}"
            return finish('api_error', task, result, steps + 1, tokens, cost)
        print(f"estimate {estimate} vs API said {response.usage.input_tokens}")
        messages.append({
            'role': 'assistant',
            'content': response.content
        })
        tokens += response.usage.input_tokens + response.usage.output_tokens

        # Cost per million tokens
        cost += (response.usage.input_tokens * MODEL['cost']['in'] + response.usage.output_tokens * MODEL['cost']['out']) / 1_000_000
        result = ""
        tool_choice = []
        for block in response.content:
            if block.type == 'text':
                result += block.text
            if block.type == 'tool_use':
                tool_choice.append(block)

        # Check cut-off and refusal first: both also have stop_reason != 'tool_use'
        if response.stop_reason == 'max_tokens':
            return finish('truncated', task, result, steps + 1, tokens, cost)

        if response.stop_reason == 'refusal':
            return finish('refusal', task, result, steps + 1, tokens, cost)

        if response.stop_reason != 'tool_use':
            return finish('done', task, result, steps + 1, tokens, cost)

        if tokens > BUDGET:
            return finish('budget_hit', task, result, steps + 1, tokens, cost)

        tool_results = [call_tool(tool) for tool in tool_choice]
        messages.append({
            'role': 'user',
            'content': tool_results
        })

    # 8. Hit the step limit: one last call with tools turned off, so the model must answer.
    #    Tell it why, or it writes as if it's about to call the next tool ("Next, Pune.").
    #    The last message is the tool results; a text block can go after them.
    messages[-1]["content"].append({
        "type": "text",
        "text": "You have reached the step limit and can't call any more tools. "
                "Answer now using only the results you already have, and say what is missing."
    })
    try:
        last_call = client.messages.create(
            model=MODEL['id'],
            system=SYSTEM_PROMPT,
            max_tokens=MAX_TOKENS,
            messages=messages,
            tools=all_tools,
            tool_choice={"type": "none"}
        )
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
        return finish('api_error', task, f"API error: {e}", MAX_STEPS + 1, tokens, cost)
    tokens += last_call.usage.input_tokens + last_call.usage.output_tokens
    cost += (last_call.usage.input_tokens * MODEL['cost']['in'] + last_call.usage.output_tokens * MODEL['cost']['out']) / 1_000_000
    messages.append({"role": "assistant", "content": last_call.content})
    answer = ""
    for block in last_call.content:
        if block.type == 'text':
            answer += block.text
    return finish('max_steps', task, answer, MAX_STEPS + 1, tokens, cost)


if __name__ == "__main__":
    load_dotenv()
    print("Welcome, How may I help you")
    while True:
        print()
        user_input = input(">> ")
        if user_input == 'exit':
            break
        print()
        messages = [{
            "role": "user",
            "content": user_input
        }]
        api_key = os.environ['ANTHROPIC_API_KEY']
        client = Anthropic(api_key=api_key, max_retries=4)
        print(call_llm(client, messages))