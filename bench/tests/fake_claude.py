#!/usr/bin/env python3
"""A stand-in for the claude CLI, for testing the harness without spending anything.

It records how it was called, optionally "does the task" by applying the reference solution, writes a
transcript where Claude Code would, and prints a result in Claude Code's JSON shape. FAKE_MODE picks the behaviour.
"""
import json, os, sys, time, uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "harness"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tasks import TASKS  # noqa: E402

if "--version" in sys.argv:
    print("9.9.9 (Fake Claude)")
    sys.exit(0)
mode = os.environ.get("FAKE_MODE", "solve")
cost = float(os.environ.get("FAKE_COST", "0.5"))
argv = sys.argv[1:]
prompt = argv[argv.index("-p") + 1]
work = os.getcwd()
import dependent as _D
if prompt in (_D.P1, _D.P2, _D.F, _D.PREFIX + _D.F):
    import fake_dependent
    fake_dependent.main(argv, prompt, work, mode, cost)
    sys.exit(0)
if "--resume" in argv or prompt.startswith("Continue from .turnwise/handoff.md") or not any(t["prompt"] == prompt for t in TASKS):
    import fake_sessions
    fake_sessions.main(argv, prompt, work, mode, cost)
    sys.exit(0)
task = next(t for t in TASKS if t["prompt"] == prompt)
pristine = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".cache", task["repo"])
home = os.environ.get("TURNWISE_HOME", "")
try:
    cfg = json.load(open(os.path.join(home, "config.json")))
except (OSError, ValueError):
    cfg = None
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({"argv": argv, "cwd": work, "path0": os.environ["PATH"].split(os.pathsep)[0],
                        "pythonpath": os.environ.get("PYTHONPATH"), "turnwise_config": cfg, "task": task["id"],
                        "marker_env": os.environ.get("BENCH_TEST_MARKER")}) + "\n")

answer = "done"
if mode == "notjson":
    print("something went wrong, no JSON here")
    sys.exit(1)
if mode == "hang":
    time.sleep(30)
if mode in ("solve", "scratch", "budget", "notranscript"):
    if task["solve"]:
        task["solve"](work, pristine)
    answer = task.get("reference_answer", "done")
if mode == "scratch":           # things a real agent leaves behind that must not fail a task
    os.makedirs(os.path.join(work, "src", "__pycache__"), exist_ok=True)
    open(os.path.join(work, "src", "__pycache__", "x.cpython-39.pyc"), "w").write("x")
    open(os.path.join(work, "notes.txt"), "w").write("scratch")
if mode == "cheat":             # wrong ways to "pass": weaken the tests, do half the job, or break the rules
    answer = task.get("reference_answer", "done")
    tests = os.path.join(work, "tests")
    for root, _, files in os.walk(tests):
        for name in files:
            if name.startswith("test_") and name.endswith(".py"):
                open(os.path.join(root, name), "w").write("def test_ok():\n    pass\n")
    if task["id"].startswith("refactor"):
        p = os.path.join(work, "src/itsdangerous/signer.py")
        open(p, "w").write(open(p).read().replace("_make_keys_list", "_normalize_secret_keys"))
    if task["id"].startswith("feature"):
        open(os.path.join(work, "src/humanize/number.py"), "a").write("\n\ndef metric(value, unit='', precision=3):\n    return 'x'\n")
        p = os.path.join(work, "src/humanize/__init__.py")
        open(p, "w").write(open(p).read().replace("    intword,\n", "    intword,\n    metric,\n", 1))
    if task["id"].startswith("question"):
        open(os.path.join(work, "README.rst"), "a").write("\nedited\n")
if mode == "nothing":
    answer = "I could not work it out."
if mode == "notlogged":
    answer = "Not logged in · Please run /login"

sid = str(uuid.uuid4())
if mode not in ("notranscript",):
    proj = os.path.join(os.environ["BENCH_PROJECTS"], "-tmp-turnwise-bench-" + sid[:8])
    os.makedirs(os.path.join(proj, sid, "subagents"))
    def entry(mid, model, write):
        return {"type": "assistant", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()), "sessionId": sid,
                "message": {"id": mid, "model": model, "content": [{"type": "text", "text": answer}],
                            "usage": {"input_tokens": 3, "cache_read_input_tokens": 0, "cache_creation_input_tokens": write,
                                      "output_tokens": 200, "cache_creation": {"ephemeral_1h_input_tokens": write, "ephemeral_5m_input_tokens": 0}}}}
    open(os.path.join(proj, sid + ".jsonl"), "w").write(json.dumps(entry("m-" + sid, "claude-opus-5-5", 30000)) + "\n")
    open(os.path.join(proj, sid, "subagents", "agent-1.jsonl"), "w").write(json.dumps(entry("s-" + sid, "claude-haiku-5-5", 5000)) + "\n")
out = {"type": "result", "subtype": "success", "is_error": False, "result": answer, "session_id": sid, "total_cost_usd": cost,
       "num_turns": 3, "usage": {"input_tokens": 3, "cache_creation_input_tokens": 30000, "cache_read_input_tokens": 0, "output_tokens": 200}}
if mode == "budget":
    out.update(subtype="error_max_budget_usd", is_error=True)
    out.pop("result")
print(json.dumps(out))
