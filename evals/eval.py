"""Runs the 20 tasks in evals/tasks.json once each and scores them.

    .venv/bin/python evals/eval.py mine haiku     # my loop (agent.py)
    .venv/bin/python evals/eval.py pai haiku      # Pydantic AI (pai.py)
    .venv/bin/python evals/eval.py mine sonnet

Results (summary + every answer) go to evals/results/<impl>_<model>.json.
"""
import contextlib, io, json, os, re, statistics, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "evals", "results")
os.chdir(ROOT); sys.path.insert(0, ROOT)
from dotenv import load_dotenv; load_dotenv(f"{ROOT}/.env")
from anthropic import Anthropic
import agent, budget, pai

MODELS = {"haiku": {"id": "claude-haiku-5-5", "cost": {"in": 0.10, "out": 0.50}},
          "sonnet": {"id": "claude-sonnet-5-5", "cost": {"in": 2.00, "out": 10.00}}}
if len(sys.argv) != 3:
    sys.exit(__doc__)
impl, model_name = sys.argv[1], sys.argv[2]
model = MODELS[model_name]
agent.MODEL = budget.MODEL = model
client = Anthropic(max_retries=4)


def passes(answer, check):
    text = answer.lower()
    if check.get("absent") and check["absent"].lower() in text:
        return False
    if check["type"] == "number":
        nums = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", answer.replace(",", ""))]
        return any(abs(n - check["value"]) <= check.get("tol", 0.01) for n in nums)
    if check["type"] == "contains":
        return check["value"] in text
    return any(v in text for v in check["value"])


rows = []
for t in json.load(open(f"{ROOT}/evals/tasks.json")):
    buf = io.StringIO()
    start = time.time()
    with contextlib.redirect_stdout(buf):
        out = (agent.call_llm(client, [{"role": "user", "content": t["task"]}]) if impl == "mine"
               else pai.run(t["task"], model=model))
    tools = out.get("tools") or re.findall(r">>> Tool Called: (\w+)", buf.getvalue())
    rows.append({"id": t["id"], "pass": out["stop_reason"] == "done" and passes(out["answer"], t["check"]),
                 "stop": out["stop_reason"], "steps": out["steps"], "tokens": out["tokens"],
                 "inr": out["cost_inr"], "seconds": round(time.time() - start, 1), "tools": tools,
                 "answer": out["answer"]})

summary = {"impl": impl, "model": model["id"], "passed": sum(r["pass"] for r in rows), "of": len(rows),
           "avg_steps": round(statistics.mean(r["steps"] for r in rows), 2),
           "avg_tokens": round(statistics.mean(r["tokens"] for r in rows)),
           "avg_inr": round(statistics.mean(r["inr"] for r in rows), 4),
           "total_inr": round(sum(r["inr"] for r in rows), 2),
           "median_seconds": statistics.median(r["seconds"] for r in rows),
           "calculate_calls": sum(r["tools"].count("calculate") for r in rows)}
json.dump({"summary": summary, "rows": rows}, open(f"{OUT}/{impl}_{model_name}.json", "w"), indent=2)
print(json.dumps(summary))
for r in rows:
    print(f"{r['id']:9} {'PASS' if r['pass'] else 'FAIL'} stop={r['stop']:10} steps={r['steps']} "
          f"tokens={r['tokens']:6} ₹{r['inr']:.3f} {r['seconds']}s tools={r['tools']}")
