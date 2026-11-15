"""Stand-in behaviour for the session test's prompts (used by fake_claude.py)."""
import glob, json, os, re, time, uuid

import sessions as S

PREFIX = "Continue from .turnwise/handoff.md, which describes the previous session. "


def entry(sid, mid, model, read, write, text):
    return {"type": "assistant", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()), "sessionId": sid,
            "message": {"id": mid, "model": model, "content": [{"type": "text", "text": text}],
                        "usage": {"input_tokens": 3, "cache_read_input_tokens": read, "cache_creation_input_tokens": write,
                                  "output_tokens": 200, "cache_creation": {"ephemeral_1h_input_tokens": 0, "ephemeral_5m_input_tokens": write}}}}


def main(argv, prompt, work, mode, cost):
    fresh = prompt.startswith(PREFIX)
    core = prompt[len(PREFIX):] if fresh else prompt
    s, job = next((s, j) for s in S.SESSIONS for j in ("build", "followup", "small") if s[j] == core)
    model = argv[argv.index("--model") + 1]
    resume = argv[argv.index("--resume") + 1] if "--resume" in argv else None
    pristine = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".cache", s["repo"])
    projects = os.environ["BENCH_PROJECTS"]
    old = glob.glob(os.path.join(projects, "*", f"{resume}.jsonl")) if resume else []
    before = sum(1 for _ in open(old[0])) if old else 0
    # What the run found when it started: used by the tests to prove everything is reset between runs.
    marker = os.path.join(work, "src/click/types.py") if s["id"] == "click" else os.path.join(work, "more_itertools/more.py")
    bug = ('"y", "on"' not in open(marker).read()) if s["id"] == "click" else ("num_lists = q + 1\n" in open(marker).read())
    with open(os.environ["FAKE_LOG"], "a") as f:
        f.write(json.dumps({"argv": argv, "session": s["id"], "job": job, "fresh": fresh, "model": model, "resume": resume,
                            "bug_present": bug, "funcs_exists": os.path.exists(os.path.join(work, "FUNCS.md")),
                            "notes_exists": os.path.exists(os.path.join(work, "NOTES.md")),
                            "handoff_exists": os.path.exists(os.path.join(work, ".turnwise", "handoff.md")),
                            "transcript_lines": before, "resume_found": bool(old)}) + "\n")
    if mode == "notlogged":
        print(json.dumps({"type": "result", "result": "Not logged in · Please run /login", "session_id": str(uuid.uuid4()), "total_cost_usd": 0}))
        return
    if job == "build":
        open(os.path.join(work, "NOTES.md"), "w").write("notes\n")
    elif job == "followup" and mode != "nothing":
        s["followup_solve"](work, pristine)
    elif job == "small" and mode != "nothing":
        open(os.path.join(work, "FUNCS.md"), "w").write(s["small_solve"])
    context = int(os.environ.get("FAKE_CONTEXT", "120000"))
    if resume and old:
        sid, path = resume, old[0]
        e = entry(sid, "m-" + uuid.uuid4().hex, model, 0 if model != "claude-opus-5-5" else context, context if model != "claude-opus-5-5" else 500, "done")
        open(path, "a").write(json.dumps(e) + "\n")
    else:
        sid = str(uuid.uuid4())
        proj = os.path.join(projects, re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(work)))   # as Claude Code names it
        os.makedirs(proj, exist_ok=True)
        write = context if job == "build" else 19000
        open(os.path.join(proj, sid + ".jsonl"), "w").write(
            json.dumps({"type": "user", "sessionId": sid, "message": {"role": "user", "content": prompt}}) + "\n"
            + json.dumps(entry(sid, "m-" + sid, model, 0, write, "done")) + "\n")
    earlier = sum(1 for l in open(old[0]) if '"assistant"' in l) - 1 if (resume and old) else 0   # requests before this run
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "done", "session_id": sid,
                      "total_cost_usd": cost * (1 + earlier), "num_turns": 3,
                      "usage": {"input_tokens": 3, "cache_creation_input_tokens": 1000, "cache_read_input_tokens": 2000, "output_tokens": 200}}))
