# mini-agent: Plan

An agent loop built by hand, no framework, then rebuilt in Pydantic AI to compare the two.

**Done when:** `agent.py` is about 200 lines · the 20-task eval prints a table · `COMPARISON.md` has 5 points.

**Model:** develop and debug on `claude-haiku-5-5`. Run the final eval once on `claude-opus-5-5` (Day 5).

```python
MODEL = os.getenv("MODEL", "claude-haiku-5-5")   # one variable, from day 1
MAX_TOKENS = 4000                                 # not 16000: one runaway step on Opus = ₹28
PRICES = {"claude-haiku-5-5": (0.10, 0.50), "claude-opus-5-5": (4.00, 20.00)}  # $ per 1M tokens, (input, output)
```

**Rough cost:** one 5-step task ≈ ₹0.35 on Haiku, ≈ ₹14 on Opus. The whole week on Haiku is about ₹150. One Opus eval run (20 tasks × 1) is about ₹280.

```
mini-agent/
  agent.py          # the loop + failure handling
  tools.py          # 3 tools + schemas
  budget.py         # token counting, ceilings, summariser, ₹
  workspace/        # the only folder read_file may read
  tests/  evals/  framework/  COMPARISON.md  runs.jsonl
```

---

## Day 1 (24th): Setup + loop + 3 tools · ~5.5 hrs

**Done when:** 5 test prompts work, one of them needs 2 tools in a row, and every step prints a trace line.

### Phase 0: Setup · ~30 min
- `python -m venv .venv` → `pip install anthropic httpx python-dotenv pydantic`
- `.env` with `ANTHROPIC_API_KEY` (and optionally `MODEL=claude-haiku-5-5`)
- Make one call with a single `calculate` tool and check that `r.stop_reason == "tool_use"`
- Print `r.content` and `r.usage` to see what comes back

### Phase 1: Tools (`tools.py`) · ~1.5 hrs
- One registry `TOOLS = {name: {"fn": ..., "schema": ...}}`, so the loop never hard-codes tool names
- `calculate`: parse with `ast` and allow only numbers and `+ - * / ** % ()`. ⚠️ **Never `eval()`**
- `fetch_url`: `httpx` with `timeout=10`, http/https only, strip HTML to text, cut to 8,000 characters
- `read_file`: refuse anything outside `workspace/` (code below) and cap the size
- Write each tool description as if the model has never seen your code: what it returns, its limits, when to use it

```python
p = (WORKSPACE / path).resolve()
if not p.is_relative_to(WORKSPACE.resolve()):
    raise ValueError("path outside workspace")
```

### Phase 2: The loop (`agent.py`) · ~2 hrs
- `for step in range(MAX_STEPS)`, never `while True`
- Append `r.content` **exactly as received**, `thinking` blocks included
- Stop when `stop_reason == "end_turn"`
- Send **all** tool results back in **one** user message, each with the matching `tool_use_id`

```python
for step in range(MAX_STEPS):
    r = client.messages.create(model=MODEL, max_tokens=MAX_TOKENS, system=SYSTEM,
                               tools=tool_schemas(), messages=messages)
    messages.append({"role": "assistant", "content": r.content})
    if r.stop_reason == "end_turn":
        return final_text(r)
    results = [{"type": "tool_result", "tool_use_id": b.id,
                "content": TOOLS[b.name]["fn"](**b.input)}
               for b in r.content if b.type == "tool_use"]
    messages.append({"role": "user", "content": results})
```

### Phase 3: Trace + run log · ~45 min
- One line per step: `step 2 | calculate {'expression': '40+60'} → "100" | in=2010 out=60`
- At the end of a run, add one line to `runs.jsonl`: **model**, task, stop reason, steps, tokens, ₹
- Work out ₹ from `PRICES[MODEL]` × today's USD→INR rate
- Print a running ₹ total for the day. The cost per call looks tiny, so watch the total.

### Phase 4: 5 hand tests · ~30 min
- `(1234 * 56) / 7` → calculate
- "What's in notes.md?" → read_file
- "Title of https://example.com?" → fetch_url
- "Read prices.txt and total it" → read_file then calculate
- "Hello, who are you?" → no tool at all

---

## Day 2 (25th): Survive failures · ~5 hrs

**Done when:** every failure case has a test, and every run ends with a named stop reason.

Haiku helps here: it makes bad tool calls more often than Opus, so the bugs you're practising on come to you for free.

### Phase 1: `execute_tool` never crashes · ~1.5 hrs
- Every tool call goes through one function that returns `(text, is_error)` and never raises
- Unknown tool → return an error that lists the valid tools
- Wrong arguments → validate with pydantic → return the validation error
- The tool itself throws → `"Error: <type>: <message>"`
- Send it back with `"is_error": True`. The model reads the error and usually fixes its own call.
- ⚠️ Leave `strict: true` off for now. It would hide the bad-argument bugs you're practising on. Note it for `COMPARISON.md`.

### Phase 2: Stop conditions · ~2 hrs
- **Loop:** count `(name, json.dumps(input, sort_keys=True))`. On the 3rd identical call, send back "you already did this". On the 4th, stop with `stop="loop"`.
- **Token budget:** add up `r.usage` across steps; once over e.g. 60k, stop with `stop="budget"`
- **Step limit:** make one last call with `tool_choice={"type": "none"}` so the model has to answer → `stop="max_steps"`
- **`stop_reason == "max_tokens"`:** the reply was cut off, so don't run its tool calls → `stop="truncated"`
- **API errors:** the SDK already retries 429 and 5xx. Set `Anthropic(max_retries=4)`, catch `RateLimitError` → `APIStatusError` → `APIConnectionError`, stop with `stop="api_error"`.

### Phase 3: Provoke each failure with real runs · ~1 hr
- Add a `boom` tool that always raises and a `slow` tool that times out, then ask the agent to use them
- Step limit: run with `MAX_STEPS=2` on a task that needs 3 tools
- Budget: set the run budget to ~3k tokens
- Truncated: set `MAX_TOKENS=50`
- Bad arguments, unknown tools and loops: Haiku produces these on its own sometimes, so check `runs.jsonl` for them as you go
- Collect these runs in `tests/test_failures.py` and check that each one ends with the stop reason you expect

---

## Day 3 (26th): Context budget + 20 tasks + eval · ~8 hrs (longest day)

**Video:** Sarvin Style Coding (Memory, Streaming & Tokens), plus a rewatch of Carbon Layer ch 6, 14:12–16:58, which is compaction that keeps the start and end of the history.

**Done when:** a budget table prints before every call, one summary has fired, and `run_eval.py` runs all 20 tasks on your loop with Haiku.

### Phase 1: Count tokens (`budget.py`) · ~1 hr
- ⚠️ Not `tiktoken`, which is OpenAI's tokenizer. Use `client.messages.count_tokens(model=MODEL, ...)`.
- Count the system prompt and tool schemas **once** at startup; they never change
- Count each new message once, when you append it, and store the number
- Check yourself: your total should be close to `r.usage.input_tokens`

### Phase 2: Ceilings + summary · ~1.5 hrs
- Ceilings: system 1.5k · tools 1.5k · each tool result 2k · history 12k · total 20k. This also keeps every prompt well under Haiku's 100k price step.
- Cut an oversized tool result **when you first append it**, never later
- If history goes over its ceiling: summarise the middle with one LLM call, and keep the task plus the last 4 messages word for word
- ⚠️ The kept tail must **start with an assistant message**. A `tool_result` whose `tool_use` was summarised away gets rejected.
- ⚠️ Remove the `thinking` blocks from the kept messages. Old thinking blocks get rejected once the history before them has changed.

```python
messages = [
    {"role": "user", "content": f"{task}\n\n<progress_so_far>\n{summary}\n</progress_so_far>"},
    *strip_thinking(tail),
]
```

### Phase 3: Budget table + force a summary · ~30 min
- Before every call, print `section | used | ceiling`, plus "API said" and ₹ so far
- Lower the history ceiling to 3k, then give a task that reads 3 files and fetches 2 pages
- Check that the summary fired, there was no 400, and the final numbers are still right

### Phase 4: 20 tasks (`evals/tasks.json`) · ~1.5 hrs
- Mix: 5 calculation · 5 file · 4 fetch · 4 multi-tool · 2 adversarial (missing file, `../../etc/passwd`)
- Each task has a checker: `number` (with a tolerance), `contains` or `contains_any`
- Fetch only **stable** pages (example.com, Wikipedia, httpbin.org/json)
- ⚠️ Work out the expected answers yourself, not with the model

```json
{"id": "multi_01", "task": "Read prices.txt, total it, add 18% GST.",
 "check": {"type": "number", "value": 147.5, "tol": 0.01}}
```

### Phase 5: `run_eval.py` + run it · ~2.5 hrs
- Write `THRESHOLDS` at the top **before** the first run (completion ≥ 0.85, average ₹ ≤ X)
- For each task, record `model · completed · steps · tokens · ₹ · stop`. Run each task 3 times; passing 2 of 3 counts as flaky, not passed.
- Flags: `--impl mine|pai` and `--model haiku|opus` (`pai` gets filled in on Day 4–5)
- Run `--impl mine --model haiku`: 20 tasks × 3, about ₹21
- Read the trace of every failed task. Sort each one into a bucket: tool bug · tool description · prompt · checker too strict
- Fix only the top 1–2 buckets, re-run, and save the before and after tables

If you run out of time, Phase 5's fixes (the last two points) move to Day 4.

---

## Day 4 (27th): Framework videos + start Pydantic AI · ~3 hrs

**Videos first** (~1 hr):
- Pydantic AI (NeuralNine): simple agent, message history, tool use, dependency injection, **timeouts and retries (32:10)**
- OpenAI Agents SDK (Tom Shaw): 0:00–8:16 and **guardrails, 17:29–33:15**

**Done when:** the Pydantic AI version answers your 5 hand tests from Day 1.

### Phase 1: Pydantic AI basics (`framework/pai_agent.py`) · ~2 hrs
- `pip install pydantic-ai`. Same 3 tools, same system prompt, same `MODEL` variable.
- Reuse the tool functions from `tools.py` and register each with `@agent.tool_plain`. The schema comes from the type hints and the docstring.
- Run your 5 hand tests from Day 1 and compare the answers with your loop's
- Print `result.usage()` after each run so you can compare tokens with your loop
- Check the exact names against the installed version's docs

```python
agent = Agent(f"anthropic:{MODEL}", system_prompt=SYSTEM)

@agent.tool_plain
def calculate(expression: str) -> str:
    """Evaluate an arithmetic expression like '(3 + 4) * 2'."""
    ...

result = agent.run_sync(task, usage_limits=UsageLimits(request_limit=10))
```

---

## Day 5 (28th): Finish Pydantic AI + Opus run + comparison · ~4.5 hrs

**Done when:** `COMPARISON.md` is written with the 3-column table and 5 points.

### Phase 1: Finish Pydantic AI · ~1 hr
- For bad input, raise `ModelRetry` inside a tool and the framework sends it back to the model
- Limit steps with `UsageLimits(request_limit=10)`
- Go through your Day 2 failure cases: which ones does the framework already handle, and which still need code from you?
- Summarising old turns: try Pydantic AI's `history_processors`, a function that changes the message list before each call. Compare it with your `budget.py`.
- Connect it to `run_eval.py --impl pai`

### Phase 2: Run Pydantic AI on Haiku · ~45 min
- `run_eval.py --impl pai --model haiku`, 20 tasks × 3 (~₹21)
- Compare its failures with your loop's: same tasks failing, or different ones?

### Phase 3: One Opus run · ~30 min
- `run_eval.py --impl mine --model opus`, **once**, with no repeats (~₹280)
- Run 3 tasks first and check the ₹ before running all 20
- ⚠️ Don't debug on Opus. If something breaks, go back to Haiku.

### Phase 4: `COMPARISON.md` · ~1.5 hrs
- Table: completion rate · average steps · average ₹ · median latency · lines of code
- Three columns: **my loop + Haiku · Pydantic AI + Haiku · my loop + Opus**
- **Framework:** what it gave you free (schemas, retries, limits), what you lost (budget table, summaries, your own trace), and which Day 2 failure cases it handled by itself
- **Model:** is Haiku good enough for this agent? Compare completion rate against ₹ per task.
- **Production pick, and why** (this is the interview answer)
