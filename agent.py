import os
import json
from anthropic import Anthropic
from config import MAX_TOKENS, MODEL, SYSTEM_PROMPT, MAX_STEPS, USD_INR_CONVERSION_RATE
from dotenv import load_dotenv
from tools import all_tools, read_file, fetch_url, calculate, calculate_input, fetch_url_input, read_file_input
from pydantic import ValidationError

allowed_tools = [tool['name'] for tool in all_tools]

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
    for steps in range(MAX_STEPS):
        response = client.messages.create(
            model=MODEL['id'],
            system=SYSTEM_PROMPT,
            max_tokens=MAX_TOKENS,
            messages=messages,
            tools=all_tools
        )
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

        if response.stop_reason != 'tool_use':
            return finish('done', messages[0]['content'], result, steps + 1, tokens, cost)

        tool_results = [call_tool(tool) for tool in tool_choice]
        messages.append({
            'role': 'user',
            'content': tool_results
        })

    return finish('max_steps', messages[0]['content'], result, steps + 1, tokens, cost)


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
        client = Anthropic(api_key=api_key)
        print(call_llm(client, messages))