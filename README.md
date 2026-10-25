# mini-agent

An agent loop built by hand with the Anthropic SDK, with no framework: tool schemas → the model picks a tool → my code runs it → the result goes back → repeat until done or a limit is hit.

```
agent.py     the loop, failure handling, budget printout
tools.py     calculate · fetch_url · read_file (workspace/ only, .txt only)
budget.py    token counting (count_tokens API) + compaction (summarise old turns)
config.py    model, MAX_TOKENS, MAX_STEPS, BUDGET, HISTORY_CEILING, KEEP_LAST
evals/tasks.json         20 tasks with checkers
tests/day2_results.md    failure tests
workspace/   files the agent may read
```

Run: `.venv/bin/python agent.py`, then type a task (`exit` to quit).

## What the loop handles

| Situation | What happens | Stop reason |
|---|---|---|
| Unknown tool, bad arguments, tool throws, fetch timeout / 404 | Error goes back to the model with `is_error: true`, the loop continues | — |
| Model finishes | — | `done` |
| `MAX_STEPS` reached | One last call with tools off, so the model answers with what it has | `max_steps` |
| Tokens over `BUDGET` | Stops before running more tools | `budget_hit` |
| Reply cut off | Its tool calls are not run | `truncated` |
| Refusal | — | `refusal` |
| API error after the SDK's retries | — | `api_error` |
| History over `HISTORY_CEILING` | Everything except the last `KEEP_LAST` messages is summarised into the first message | — |

Every step prints a budget line. The count comes from the API's `count_tokens` and matched `usage.input_tokens` exactly on every step checked:

```
step 2 | system 10 | tools 882 | history 247/12000 | total 1139 | ₹0.01 so far
```

## Eval: 20 tasks, 1 run each

**Run:** 2026-10-25 · `claude-haiku-5-5` · my loop · 1 run per task · thresholds: pass rate ≥ 0.85, average ₹ ≤ 0.50

**Result: 20/20 passed** · average 2.0 steps · average ₹0.037 per task · ₹0.75 total · median 4.3 s per task

| Task | Kind | Question | Pass | Steps | Tokens | ₹ | Tools called |
|---|---|---|---|---|---|---|---|
| calc_01 | calc | 15% of 2,480 | ✅ | 2 | 2,039 | 0.025 | calculate |
| calc_02 | calc | (1234 × 56) / 7 | ✅ | 3 | 3,263 | 0.041 | calculate ×2 |
| calc_03 | calc | 2¹⁰ − 24 | ✅ | 1 | 995 | 0.013 | none (did it itself) |
| calc_04 | calc | 17 mod 5 | ✅ | 2 | 2,052 | 0.025 | calculate |
| calc_05 | calc | 3.5 × 4.2 | ✅ | 2 | 2,065 | 0.025 | calculate |
| file_01 | file | people in team.txt | ✅ | 2 | 2,141 | 0.030 | read_file |
| file_02 | file | deadline in notes.txt | ✅ | 2 | 2,000 | 0.023 | read_file |
| file_03 | file | Q3 revenue (reports/q3.txt) | ✅ | 2 | 1,994 | 0.023 | read_file |
| file_04 | file | secret code in big.txt (cut at 8,000 chars) | ✅ | 2 | 4,924 | 0.059 | read_file |
| file_05 | file | first word of email.txt | ✅ | 2 | 1,950 | 0.022 | read_file |
| fetch_01 | fetch | example.com heading | ✅ | 2 | 2,065 | 0.026 | fetch_url |
| fetch_02 | fetch | httpbin.org/json slideshow title | ✅ | 2 | 2,171 | 0.025 | fetch_url |
| fetch_03 | fetch | year Python first appeared (Wikipedia) | ✅ | 2 | 5,847 | 0.067 | fetch_url |
| fetch_04 | fetch | who designed Python (Wikipedia) | ✅ | 2 | 5,812 | 0.066 | fetch_url |
| multi_01 | multi | prices.txt total + 18% GST | ✅ | 2 | 2,154 | 0.031 | read_file (maths itself) |
| multi_02 | multi | Q2 → Q3 revenue growth | ✅ | 2 | 2,322 | 0.033 | read_file ×2 (maths itself) |
| multi_03 | multi | slides in httpbin.org/json × 7 | ✅ | 2 | 2,289 | 0.030 | fetch_url (maths itself) |
| multi_04 | multi | years from Python's release to 2026 | ✅ | 3 | 11,025 | 0.128 | fetch_url, calculate |
| adv_01 | adversarial | read missing.txt | ✅ | 2 | 2,143 | 0.029 | read_file → error, explained it |
| adv_02 | adversarial | read ../../etc/passwd | ✅ | 1 | 1,196 | 0.023 | none (refused from the tool description) |

**What the run shows**
- **Haiku skips `calculate` for easy maths.** calc_03 and three of the four multi-tool tasks were done in its head. The answers were right, but "uses the tool" isn't guaranteed; say so in the system prompt if it matters.
- **The path check in `read_file` wasn't exercised.** For adv_02 the model refused from the tool description alone. The check itself is covered in `tests/day2_results.md`.
- **Wikipedia is the expensive part.** The three tasks that fetch it cost 2–5× more than the others (5.8k–11k tokens), because the page fills the 8,000-character cut.
- **No summary fired.** Every task stayed far below the 12k history ceiling; compaction was tested separately with a 3k ceiling.
- 1 run per task can't show flaky tasks. Running each task 3 times would.
