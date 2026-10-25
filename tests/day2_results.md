# Day 2: Failure tests

**Run:** 2026-10-25 · `claude-sonnet-5-5` · `MAX_TOKENS=6000` · `MAX_STEPS=8` · `BUDGET=60_000` (each case below says what it lowers)

**Result:** 13/13 passed · ₹2.90 for the 5 real runs

## Tool errors (no API call, `execute_tool` directly)

Each one should come back with `is_error=True` and a message the model can act on.

| Case | Input | Message sent to the model | is_error |
|---|---|---|---|
| Unknown tool | `delete_everything` | `delete_everything is not a Valid Tool, Valid tools are ['calculate', 'fetch_url', 'read_file']` | ✅ |
| Misspelt argument | `first_inpt=1` | `Error: Input params are not correct: 1 validation error for calculate_input` | ✅ |
| Operator not allowed | `expression='^'` | `Error: Input params are not correct: 1 validation error for calculate_input` | ✅ |
| Divide by zero | `1 / 0` | `Error: <class 'ZeroDivisionError'>: division by zero` | ✅ |
| Path escape | `../../etc/passwd` | `Error: <class 'ValueError'>: path outside workspace` | ✅ |
| Missing file | `missing.txt` | `Error: <class 'FileNotFoundError'>: [Errno 2] No such file or directory: ...` | ✅ |
| Fetch timeout | `httpbin.org/delay/15` (timeout is 10s) | `Error: <class 'httpx.ReadTimeout'>: The read operation timed out` | ✅ |
| Fetch 404 | `example.com/this-does-not-exist` | `Error: <class 'httpx.HTTPStatusError'>: Client error '404 Not Found' ...` | ✅ |

## Stop reasons (real runs on Sonnet)

| Case | Task | Setting changed | Expected | Got | Steps | Tokens | ₹ |
|---|---|---|---|---|---|---|---|
| Happy path | What is 1234 * 56? | none | `done` | `done` ✅ | 2 | 2,034 | 0.49 |
| Tool throws inside the loop | Read missing.txt and summarise it | none | `done` | `done` ✅ | 2 | 2,098 | 0.53 |
| Step limit | 2+3, ×4, −7, ÷3, one tool call each | `MAX_STEPS=2` | `max_steps` | `max_steps` ✅ | 3 | 3,595 | 1.05 |
| Budget | same 4-step sum | `BUDGET=1500` | `budget_hit` | `budget_hit` ✅ | 2 | 2,178 | 0.59 |
| Cut-off reply | Write a 500-word essay about agents | `MAX_TOKENS=50` | `truncated` | `truncated` ✅ | 1 | 963 | 0.23 |

## Answers worth reading

**Tool throws inside the loop.** The model read the error and explained it; it didn't make anything up:
> I couldn't read `missing.txt` because the file doesn't exist in the workspace folder, so there's nothing to summarise. You could check that the filename and its spelling are right, or tell me a different file name…

**Step limit.** The forced last answer, with tools turned off. Sonnet finished the sum in its head but said which steps the tool didn't check:
> I only finished the first two steps with the calculate tool before the step limit hit: 1. 2 + 3 = **5** 2. 5 × 4 = **20**. I didn't run the last two steps with the tool, so these two results are my own arithmetic: 3. 20 − 7 = 13 4. 13 ÷ 3 ≈ 4.333 … The tool didn't verify steps 3 and 4.

The same test on Haiku earlier stopped at 20 and said steps 3–4 were missing, without guessing. Worth a line in `COMPARISON.md`: the bigger model fills the gap itself, which may or may not be what you want.

**Budget.** The answer is empty because the run stopped before the next tool call, mid-task. That's expected: `budget_hit` means "unfinished".

## Notes
- The step limit logs 3 steps: 2 loop steps plus the forced final call.
- The budget is checked after each call, so a run can go slightly over it (2,178 against 1,500) before it stops.
- Bad arguments and unknown tools were tested directly, because Sonnet never makes these mistakes on its own here.
