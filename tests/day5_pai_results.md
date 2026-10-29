# Day 5: Pydantic AI and the Day 2 failure cases

**Run:** 2026-10-29 · pydantic-ai 2.63.0 · `claude-sonnet-5-5` · same `MAX_TOKENS`, `MAX_STEPS`, `BUDGET` as `agent.py` · `retries=2`, `tool_timeout=15`

**Biggest finding:** a plain exception inside a tool **crashes the whole run**. Bad arguments and unknown tools are handled by the framework, but anything the tool itself raises (divide by zero, missing file, 404) has to be turned into `ToolFailed` by your code. In `pai.py` each tool has a try/except that raises `ToolFailed`, which does the same job as `execute_tool` in `agent.py`.

## Tool errors

The tool calls were scripted with `FunctionModel`, so no API cost. Each row shows what the model was sent back.

| Case | Without the try/except | With the try/except (`ToolFailed`) | `agent.py` |
|---|---|---|---|
| Unknown tool | ✅ framework: `Unknown tool name: 'delete_everything'. Available tools: 'calculate', 'fetch_url', 'read_file'` | same | your own message |
| Misspelt argument | ✅ framework: pydantic validation error (`first_input` missing, `first_inpt` not allowed) | same | your pydantic check |
| Operator not allowed | ✅ framework: `Input should be '+', '-', '*', '/', '**' or '%'` | same | your pydantic check |
| Divide by zero | ❌ **run crashes** `ZeroDivisionError` | ✅ `ZeroDivisionError: division by zero` | ✅ |
| Path escape | ❌ **run crashes** `ValueError` | ✅ `ValueError: path outside workspace` | ✅ |
| Missing file | ❌ **run crashes** `FileNotFoundError` | ✅ `FileNotFoundError: ... missing.txt` | ✅ |
| Fetch 404 | ❌ **run crashes** `HTTPStatusError` | ✅ `HTTPStatusError: Client error '404 Not Found' ...` | ✅ |
| Tool takes too long | ✅ framework: `tool_timeout` cut a 20 s tool off at 3.0 s and sent `Timed out after 3 seconds.` | same | only `fetch_url` has a timeout (httpx, 10 s) |
| Bad arguments on every try | ❌ **run crashes** after 2 retries: `UnexpectedModelBehavior: Tool 'calculate' exceeded max retries count of 2` | same | no limit: each bad call uses a step until `MAX_STEPS` |

The 404 and timeout rows used httpbin.org/delay/15, but httpbin now answers 400 for delays that long, so that URL tested an HTTP error, not a timeout. The timeout row above used a tool that sleeps instead.

## Stop reasons (real runs on Sonnet, through `pai.run()`)

| Case | Setting changed | Got | Steps | Tokens | ₹ | What the answer was |
|---|---|---|---|---|---|---|
| Happy path: 1234 × 56 | none | `done` | 2 | 1,772 | 0.44 | `1234 × 56 = **69,104**` |
| Missing file in a real run | none | `done` | 2 | 1,893 | 0.54 | explained the `FileNotFoundError`; nothing made up |
| Step limit | `max_steps=2` | `max_steps` | 2 | 1,916 | 0.53 | **no answer**, just the error: `The next request would exceed the request_limit of 2` |
| Budget | `budget=1500` | `budget_hit` | 2 | 1,916 | 0.53 | the error: `Exceeded the total_tokens_limit of 1500 (total_tokens=1916)` |
| Cut-off reply | `max_tokens=50` | `truncated` | 1 | 832 | 0.21 | the cut-off text, returned as a **normal answer** |

## Compared with `agent.py`

| | `agent.py` | Pydantic AI |
|---|---|---|
| Bad arguments, unknown tool | your code | built in |
| Tool raises | your code (`execute_tool`) | **your code** (`ToolFailed` wrapper), otherwise the run crashes |
| Tool timeout | `fetch_url` only | built in for every tool (`tool_timeout`) |
| Limit on bad retries | none | built in (`retries`), but it ends the run with an exception |
| Step limit | forced last answer with what it has | raises `UsageLimitExceeded`, **no answer** |
| Budget | checked after each call, stops before more tools | raises `UsageLimitExceeded` (also checked after the call: 1,916 against 1,500) |
| Cut-off reply | `truncated` | **not flagged**: the cut-off text comes back as `output`. `pai.run()` checks `finish_reason == 'length'` itself |
| Stop reasons | returned as values | exceptions; `pai.run()` turns them back into your stop reasons |
| Tokens for the same task | 2,034 (happy path, Day 2) | 1,772: its tool schemas are smaller than `model_json_schema()` with titles and descriptions |
