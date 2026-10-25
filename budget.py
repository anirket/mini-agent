from config import MODEL, SYSTEM_PROMPT
from tools import all_tools
DUMMY = [{"role": "user", "content": "hi"}]   # count_tokens always needs at least one message


def count(client, **parts) -> int:
    return client.messages.count_tokens(model=MODEL['id'], **parts).input_tokens


def count_fixed(client) -> dict:
    base = count(client, messages=DUMMY)
    system = count(client, system=SYSTEM_PROMPT, messages=DUMMY)
    tools = count(client, tools=all_tools, messages=DUMMY)

    return {
        'system': system - base,
        'tools': tools - base
    }


def count_total(client, messages) -> int:
    """The whole request, exactly as messages.create will send it"""
    return count(client, system=SYSTEM_PROMPT, tools=all_tools, messages=messages)


def compact(client, task, messages: list, keep_last: int) -> tuple:
    split_index = len(messages) - keep_last
    # The kept part must start with an assistant message: then every tool_result in it has its
    # tool_use with it, and middle ends with a user message (the tool results) that `ask` can join.
    while split_index > 1 and messages[split_index]['role'] != 'assistant':
        split_index -= 1
    middle = messages[:split_index]   # includes messages[0], so an earlier summary is carried into the new one
    tail = messages[split_index:]
    ask = {'type': 'text', 'text': "Stop here. Don't call any tools. Summarise what has been done so far: "
                                   "facts found, numbers computed, files read, what is left to do. "
                                   "Keep exact numbers and file names."}
    last = {'role': 'user', 'content': middle[-1]['content'] + [ask]}   # new list, the original stays as it was
    response = client.messages.create(
        model=MODEL['id'],
        system=SYSTEM_PROMPT,
        tools=all_tools,
        tool_choice={'type': 'none'},
        max_tokens=1000,
        messages=middle[:-1] + [last],
    )
    summary = "".join(b.text for b in response.content if b.type == 'text')
    print(f">>> summary: {summary[:300]}")
    new_messages = [{'role': 'user', 
                     'content': f"{task}\n\n<progress_so_far>\n{summary}\n</progress_so_far>"}, 
                     *tail
                    ]
    return new_messages, response.usage
