#!/usr/bin/env python3
"""PreModelSwitch: stop a mid-session model change once and show what rebuilding the cache will cost.

Observed live on Claude Code 2.1.325: the first /model was stopped with this message and the second went through.
"""
import json, os, sys

MIN_COST = 0.10   # dollars; below this the warning would cost more attention than it saves

try:
    from common import STATE, block, config, load, save, session_state, write_cost
    d = json.load(sys.stdin)
    cfg = config()
    src, dst = d.get("from_model"), d.get("to_model")
    if not cfg["switch_guard"] or os.environ.get("TURNWISE_OFF") or not dst or src == dst:
        sys.exit(0)
    s = session_state(d["transcript_path"])
    if not s or s["context"] < 20000:
        sys.exit(0)
    cost = write_cost(s["context"], dst, s["one_hour"])
    if 0 < cost < MIN_COST:                   # a known, trivial cost (a small session, or a very cheap model): not worth a stop
        sys.exit(0)
    state = load(STATE, {})
    key = "switch:" + d["session_id"]
    if state.get(key) == f"{dst}@{s['last_ts']}":
        sys.exit(0)
    state[key] = f"{dst}@{s['last_ts']}"
    save(STATE, state)
    price_note = f", about ${cost:.2f}" if cost else ""
    # One line: Claude Code shows a hook's message inline, and line breaks in it do not render.
    message = (
        f"turnwise: caches are per model. Switching to {dst} now re-writes this session's "
        f"{s['context']:,} tokens{price_note}. "
        f"Cheaper: keep this model and hand the cheap work to a subagent, or switch at the start of a new session. "
        f"To switch anyway, run the command again.")
except SystemExit:
    raise
except Exception:
    sys.exit(0)
block(message)
