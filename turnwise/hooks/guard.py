#!/usr/bin/env python3
"""UserPromptSubmit: two optional helpers for large sessions. Both are off by default.

guard      When the prompt cache has expired, stop the prompt once and show what resuming costs against
           starting a new session from a handoff note.           python3 scripts/config.py guard on
warm_note  While the cache is still warm, ask the agent to keep a short handoff note up to date, so a good
           note already exists if the session later goes stale.  python3 scripts/config.py warm_note on

Fails open: on any error it does nothing and the prompt goes through.
"""
import json, os, sys


def reminder(context, session_id):
    return (
        f"turnwise: this session is large ({context:,} tokens). So that it can be continued cheaply in a new "
        "session later, finish this task by writing .turnwise/handoff.md, replacing what is there (create the "
        f"folder if needed). Its first line must be exactly: <!-- turnwise handoff · written by the agent · session {session_id} --> "
        "Then, in under 200 words: the goal, what is done, the decisions made and why, what is not done, and the "
        "next step. Where you can, write it in the same message as your last tool calls. You don't need to "
        "mention the note in your reply.")


def decide(d):
    """Return ("block", message), ("context", text) or None."""
    from common import STATE, config, load, save, session_state, span, write_cost
    from handoff import AGENT_MARK, write_handoff
    cfg = config()
    if os.environ.get("TURNWISE_OFF") or not (cfg["guard"] or cfg["warm_note"]):
        return None
    s = session_state(d["transcript_path"])
    if not s or s["context"] < cfg["threshold_tokens"]:
        return None
    state = load(STATE, {})
    sid = d["session_id"]

    if s["idle"] <= s["ttl"]:                         # cache still warm: the cheap moment to write a good note
        key = "note:" + sid
        # First time in a session: ask as soon as it is over the threshold. After that: only once it has grown.
        if not cfg["warm_note"] or (key in state and s["context"] - state[key] < cfg["note_every_tokens"]):
            return None
        state[key] = s["context"]
        save(STATE, state)
        return "context", reminder(s["context"], sid)

    if not cfg["guard"]:
        return None
    key = "guard:" + sid
    if state.get(key) == s["last_ts"]:                # already warned for this pause; let the resend through
        return None
    state[key] = s["last_ts"]
    save(STATE, state)
    cwd = d.get("cwd") or os.getcwd()
    try:
        note = write_handoff(d["transcript_path"], cwd)
        with open(os.path.join(cwd, note)) as f:
            by_agent = AGENT_MARK in f.readline()
        note_line = (f"A handoff note{' written by the agent' if by_agent else ''} is in {note}. "
                     f"In a new session, say: continue from {note} ")
    except Exception:
        note_line = ""
    resume = write_cost(s["context"], s["model"], s["one_hour"])
    fresh = write_cost(s["opening"], s["model"], s["one_hour"])
    # A forked or resumed transcript can open with a large request, which says nothing about a fresh start.
    fresh_line = (f"A new session starts at about {s['opening']:,} tokens, about ${fresh:.2f}. "
                  if s["opening"] < 0.8 * s["context"] else
                  "A new session starts with only the system prompt and tools, so it costs much less. ")
    # One line: Claude Code shows a hook's message inline, and line breaks in it do not render.
    return "block", (
        f"turnwise: this session has been idle for {span(s['idle'])}, so its prompt cache has expired. "
        f"Resuming here re-writes up to {s['context']:,} tokens, about ${resume:.2f} on {s['model']}. "
        f"{fresh_line}{note_line}"
        f"To resume here anyway, send your prompt again.")


try:
    result = decide(json.load(sys.stdin))
except Exception:
    result = None
if result and result[0] == "context":
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": result[1]}}))
elif result and result[0] == "block":
    print(result[1], file=sys.stderr)
    sys.exit(2)
