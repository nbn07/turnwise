"""Stand-in behaviour for the dependent follow-up test's prompts (used by fake_claude.py)."""
import glob, json, os, re, time, uuid

import dependent as D


def entry(sid, text, tool=None):
    content = [{"type": "text", "text": text}] + ([tool] if tool else [])
    return {"type": "assistant", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()), "sessionId": sid,
            "message": {"id": "m-" + uuid.uuid4().hex, "model": "claude-opus-5-5", "content": content,
                        "usage": {"input_tokens": 3, "cache_read_input_tokens": 15000, "cache_creation_input_tokens": 5000,
                                  "output_tokens": 200, "cache_creation": {"ephemeral_1h_input_tokens": 0, "ephemeral_5m_input_tokens": 5000}}}}


def main(argv, prompt, work, mode, cost):
    resume = argv[argv.index("--resume") + 1] if "--resume" in argv else None
    plugin = "--plugin-dir" in argv
    projects = os.environ["BENCH_PROJECTS"]
    old = glob.glob(os.path.join(projects, "*", f"{resume}.jsonl")) if resume else []
    history = open(old[0]).read() if old else ""
    note_path = os.path.join(work, ".turnwise", "handoff.md")
    note = open(note_path).read() if os.path.exists(note_path) else ""
    home = os.environ.get("TURNWISE_HOME", "")
    try:
        cfg = json.load(open(os.path.join(home, "config.json")))
    except (OSError, ValueError):
        cfg = {}
    with open(os.environ["FAKE_LOG"], "a") as f:
        f.write(json.dumps({"argv": argv, "prompt": "P1" if prompt == D.P1 else "P2" if prompt == D.P2 else "F",
                            "fresh": prompt.startswith(D.PREFIX), "resume": resume, "plugin": plugin, "config": cfg,
                            "note_at_start": note, "old_transcript_on_disk": bool(re.findall(r"Full transcript of that session: (\S+)", note)) and os.path.exists(re.findall(r"Full transcript of that session: (\S+)", note)[0]), "helper_at_start": "def zorb" in open(os.path.join(work, "src/click/utils.py")).read(),
                            "notes_md": os.path.exists(os.path.join(work, "NOTES.md"))}) + "\n")
    if mode == "notlogged":
        print(json.dumps({"type": "result", "result": "Not logged in · Please run /login", "session_id": str(uuid.uuid4()), "total_cost_usd": 0}))
        return
    pick = os.environ.get("FAKE_PICK", "zorbaquine")
    text, tool = "done", None
    sid = resume if old else str(uuid.uuid4())
    if prompt == D.P1:
        text = "The strings are in BoolParamType.convert in types.py." + (f"\nPICK: {pick}" if pick else "")
    elif prompt == D.P2:
        open(os.path.join(work, "NOTES.md"), "w").write("utils.py holds small helpers.\n")
        text = "done"
        # The real agent writes the note only because the plugin's hook reminds it to.
        if plugin and cfg.get("warm_note") and os.environ.get("FAKE_WRITES_NOTE", "1") == "1":
            os.makedirs(os.path.dirname(note_path), exist_ok=True)
            name = "" if os.environ.get("FAKE_NOTE_OMITS_PICK") == "1" else f" Decided helper name: {pick}."
            open(note_path, "w").write(f"<!-- turnwise handoff · written by the agent · session {sid} -->\nGoal: add a bool helper.{name}\n")
            tool = {"type": "tool_use", "id": "t-note", "name": "Write", "input": {"file_path": note_path}}
    else:
        # A session can only use the agreed name if it can see it: in its own history, or in the note it was given.
        known = re.findall(r"PICK: (\w+)", history) if resume else re.findall(r"helper name: (\w+)", note)
        if not known and not resume:              # the note says where the old transcript is; use it if it is still there
            where = re.findall(r"Full transcript of that session: (\S+)", note)
            if where and os.path.exists(where[0]):
                known = re.findall(r"PICK: (\w+)", open(where[0]).read())
        name = known[-1] if known else "zorbguessed"
        if mode != "nothing":
            open(os.path.join(work, "src/click/utils.py"), "a").write(
                f"\n\ndef {name}(value):\n    return value.strip().lower() in {{'1', 'true', 't', 'yes', 'y', 'on'}}\n")
    if old:
        path = old[0]
        open(path, "a").write(json.dumps(entry(sid, text, tool)) + "\n")
    else:
        proj = os.path.join(projects, re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(work)))
        os.makedirs(proj, exist_ok=True)
        path = os.path.join(proj, sid + ".jsonl")
        open(path, "w").write(json.dumps({"type": "user", "sessionId": sid, "message": {"role": "user", "content": prompt}}) + "\n"
                              + json.dumps(entry(sid, text, tool)) + "\n")
    earlier = sum(1 for l in open(path) if '"assistant"' in l) - 1
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": text, "session_id": sid,
                      "total_cost_usd": cost * (1 + (earlier if resume else 0)), "num_turns": 2}))
