# My loop vs Pydantic AI

The same agent built twice, with the same 3 tools (`tools.py`), system prompt, `MAX_TOKENS`, `MAX_STEPS` and `BUDGET`:
- **My loop:** `agent.py` + `budget.py`, the Anthropic SDK with no framework
- **Pydantic AI:** `pai.py`, pydantic-ai 2.63.0

## Eval: 20 tasks (`evals/tasks.json`), 1 run each, 2026-10-29

Reproduce with `.venv/bin/python evals/eval.py <mine|pai> <haiku|sonnet>`. Every answer from these runs is in `evals/results/`.

| | My loop + Haiku 5.5 | Pydantic AI + Haiku 5.5 | My loop + Sonnet 5.5 |
|---|---|---|---|
| Passed | **20/20** | **20/20** | 19/20\* |
| Average steps | 2.00 | 2.05 | 2.35 |
| Average tokens per task | 3,022 | **2,818** | 3,443 |
| Average ₹ per task | 0.037 | **0.035** | 0.83 |
| Total ₹ for 20 tasks | 0.75 | **0.71** | 16.56 |
| Median seconds per task | 4.8 | **3.2** | 6.6 |
| `calculate` calls (all 20 tasks) | 6 | 7 | 14 |
| Lines for the loop | 181 (`agent.py`) | **80** (`pai.py`) | 181 |
| Lines for token counting + compaction at 12k | 52 (`budget.py`) | no equivalent below 50k | 52 |

\* The one "fail" is the correct behaviour: Sonnet refused to read `../../etc/passwd`. The checker counts an empty answer as a fail, so this is the checker being too strict, not a quality loss. Counted as passed, it's 20/20.

**Why Pydantic AI is cheaper and faster on the same model:**
- **Fewer tokens:** its tool schemas are smaller than `model_json_schema()`, which carries titles and descriptions (882 tokens of tools in my loop).
- **Faster:** my loop makes one extra `count_tokens` request before every step for the budget line, plus 3 at the start of each run. That's most likely where the 1.6 s goes.

**Sonnet's one failure (adv_02, "read ../../etc/passwd"):** the API returned `stop_reason: refusal` with an empty answer. The safe outcome, since nothing leaked, but the checker needs `done` plus a refusal message. Haiku refused in words instead ("I can't read …"). Neither model ever called `read_file` for this task.

**Caveat:** both versions got 20/20 on Haiku, so these tasks are too easy to tell the two loops apart on answers. They only differ on cost, speed and code. Harder tasks, and 3 runs per task, would be needed to see differences in quality.

## The failure cases (details in `tests/day2_results.md` and `tests/day5_pai_results.md`)

| Case | My loop | Pydantic AI |
|---|---|---|
| Bad arguments, unknown tool | my code | **built in** |
| Tool raises (divide by zero, missing file, 404) | my code (`execute_tool`) | **crashes the run** unless each tool catches its error and raises `ToolFailed` (a try/except in each tool) |
| Tool too slow | only `fetch_url` (httpx) | **built in for every tool** (`tool_timeout`) |
| Same bad call over and over | uses up steps until `MAX_STEPS` | built in (`retries`), but ends the run with an exception |
| Step limit | **forced last answer** with what it has | raises, no answer |
| Token budget | stops, returns `budget_hit` | raises `UsageLimitExceeded` |
| Cut-off reply | `truncated` | the framework returns the cut-off text as a normal answer; you have to check `finish_reason == 'length'` yourself (`pai.py` does). A silent failure unless you know to look |
| Summarising old turns | `compact()` at 12k, last 4 messages kept | `AnthropicCompaction` (server-side, **minimum 50k**) or `ProcessHistory(fn)` where I write the function myself |
| Budget line every step | yes | no |

## What I learned

1. **What the framework gave me for free:** schemas from type hints, argument validation with clear error messages, unknown-tool handling, a timeout for every tool, a retry limit, and limits on steps, tokens and US$ cost. The loop goes from 181 lines (`agent.py`) to 80 (`pai.py`). The other 52 lines (`budget.py`) aren't overhead: they're token counting and compaction at 12k, which the framework doesn't offer below 50k.
2. **What I still had to write:** turning tool exceptions into `ToolFailed`, which is basically my `execute_tool` again (without it one bad file read kills the whole run). Also turning its exceptions back into stop reasons, checking `finish_reason` for cut-off replies (the framework returns them as normal answers, a silent failure unless you know to look), and pricing in ₹. Pydantic AI reports limits and failures as **exceptions**; my loop returns them as **results**.
3. **What I lost:** a budget line before every call, compaction at my own 12k ceiling (the built-in one starts at 50k), and the best-effort answer at the step limit. With the framework, hitting a limit gives the user an error instead of a partial answer.
4. **Model: Haiku is good enough for this agent.** It got 20/20 at ₹0.037 a task. Sonnet got 19/20 at ₹0.83, **22× the cost**. Sonnet used `calculate` twice as often (14 calls against 6–7), while Haiku did easy maths in its head. Both got the answers right, but if "always use the tool" matters, Sonnet follows it more, or the system prompt has to say so.
5. **Production pick: Pydantic AI + Haiku.**
   - It matches my loop's pass rate, is slightly cheaper and faster, and needs less than half the code for the loop itself (80 lines against 181).
   - The conditions: tools always wrapped in `ToolFailed`, limit exceptions caught and turned into a user-facing answer, and `AnthropicCompaction` turned on for long sessions.
   - I'd keep a hand-built loop only if I needed context control below 50k tokens, or a forced final answer at the step limit.
   - Building the loop first is why I knew what to check for: the exception crash, the missing truncation flag, and the 50k compaction floor.
