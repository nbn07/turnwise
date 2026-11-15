#!/usr/bin/env python3
"""Build a short handoff note from a Claude Code transcript, with no model call.

Usage: handoff.py [TRANSCRIPT.jsonl [PROJECT_DIR]]   (default: newest session of the current folder)
Writes PROJECT_DIR/.turnwise/handoff.md (overwritten each time) and prints its path.
"""
import datetime, json, os, re, sys

MAX_REQUESTS, MAX_REQUEST_CHARS, MAX_ANSWER_CHARS, MAX_FILES = 8, 500, 1000, 30


def _text(content):
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")


def _clean(s):
    s = re.sub(r"<(system-reminder|local-command-\w+|command-\w+|bash-\w+|pasted_content)[^>]*>.*?</\1>", "", s, flags=re.S)
    return re.sub(r"\s+", " ", s).strip()


def newest_transcript(project_dir):
    """Claude Code stores a project's sessions under ~/.claude/projects/<path with non-alphanumerics as dashes>/."""
    import glob
    d = os.path.join(os.path.expanduser("~/.claude/projects"), re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(project_dir)))
    files = glob.glob(os.path.join(d, "*.jsonl"))
    return max(files, key=os.path.getmtime) if files else None


AGENT_MARK = "written by the agent"
SCRIPT_MARK = "<!-- added by the turnwise script"
NOTE_PATH = os.path.join(".turnwise", "handoff.md")


def _cap(text, n):
    return text[:n] + ("…" if len(text) > n else "")


def write_handoff(transcript, project_dir):
    """Write the note and return its path relative to the project.

    If the agent wrote a note for this same session (the warm_note option asks it to), that note is kept and
    only what happened after it is added. Otherwise the whole note is built from the transcript.
    """
    events, session, note_at = [], "", -1          # events: ("ask", text) | ("file", path) | ("answer", text)
    for line in open(transcript, errors="replace"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        m = d.get("message") or {}
        session = d.get("sessionId") or session
        if d.get("type") == "user" and not d.get("isMeta") and not d.get("isSidechain"):
            c = m.get("content")
            if isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
                continue
            t = _clean(_text(c))
            if t:
                events.append(("ask", _cap(t, MAX_REQUEST_CHARS)))
        elif d.get("type") == "assistant" and not d.get("isSidechain"):
            for b in m.get("content") or []:
                if b.get("type") == "tool_use" and b.get("name") in ("Edit", "Write", "NotebookEdit"):
                    fp = (b.get("input") or {}).get("file_path") or ""
                    if fp.replace(os.sep, "/").endswith(".turnwise/handoff.md"):
                        note_at = len(events)      # everything recorded so far is covered by the agent's note
                    elif fp:
                        events.append(("file", fp))
                elif b.get("type") == "text" and b.get("text", "").strip():
                    events.append(("answer", b["text"].strip()))

    out_dir = os.path.join(project_dir, ".turnwise")
    os.makedirs(out_dir, exist_ok=True)
    exclude = os.path.join(project_dir, ".git", "info", "exclude")
    if os.path.isdir(os.path.dirname(exclude)):
        have = open(exclude).read() if os.path.exists(exclude) else ""
        if ".turnwise/" not in have:
            with open(exclude, "a") as f:
                f.write(("" if have.endswith("\n") or not have else "\n") + ".turnwise/\n")
    path = os.path.join(out_dir, "handoff.md")
    rel = lambda f: os.path.relpath(f, project_dir) if f.startswith(project_dir) else f
    now = datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")

    # A note cannot hold everything. The saved transcript can, so say where it is and how to use it cheaply.
    pointer = [f"Full transcript of that session: {os.path.abspath(transcript)}",
               "If something you need is not in this note, search that file for it (for example with grep). "
               "It can be very large, so do not read it whole."]

    agent_note = ""
    if os.path.exists(path):
        with open(path) as f:
            existing = f.read()
        first = existing.split("\n", 1)[0]
        if AGENT_MARK in first and session and f"session {session} " in first + " ":
            agent_note = existing.split(SCRIPT_MARK, 1)[0].rstrip()

    def unique(items):
        out = []
        for x in items:
            out = [y for y in out if y != x] + [x]
        return out

    if agent_note:
        known = note_at >= 0                       # False when the note was not written with Write or Edit
        later = events[note_at:] if known else events
        asks = [t for k, t in later if k == "ask"]
        files = unique(t for k, t in later if k == "file")
        answers = [t for k, t in later if k == "answer"]
        lines = [agent_note, "", f"{SCRIPT_MARK} · {now} -->",
                 "## Since that note" if known else
                 "## From the transcript (the script could not tell which of this the note already covers)"]
        if not asks and not files:
            lines.append("Nothing was asked and no file was changed after the note above was written.")
        else:
            lines += ["What was asked:"] + ([f"- {r}" for r in asks[-MAX_REQUESTS:]] or ["- nothing"])
            lines += ["", "Files created or changed:"] + ([f"- {rel(f)}" for f in files[-MAX_FILES:]] or ["- none"])
            if asks and answers:
                lines += ["", "Last answer:", _cap(answers[-1], MAX_ANSWER_CHARS)]
        lines += [""] + pointer
    else:
        asks = [t for k, t in events if k == "ask"]
        files = unique(t for k, t in events if k == "file")
        answers = [t for k, t in events if k == "answer"]
        lines = [f"<!-- turnwise handoff · written {now} · from session {session} -->",
                 "# Handoff", "",
                 "Built from the previous session's transcript by a script. It lists what was asked, which files "
                 "changed, and the last answer. Check the files themselves before relying on it.", "",
                 "## What was asked (oldest first)"]
        if len(asks) > MAX_REQUESTS:
            lines.append(f"- ({len(asks) - MAX_REQUESTS} earlier requests left out)")
        lines += [f"- {r}" for r in asks[-MAX_REQUESTS:]]
        lines += ["", "## Files created or changed"] + ([f"- {rel(f)}" for f in files[-MAX_FILES:]] or ["- none"])
        lines += ["", "## Last answer", _cap(answers[-1] if answers else "", MAX_ANSWER_CHARS)]
        lines += ["", "## If this note is not enough"] + pointer
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return os.path.relpath(path, project_dir)


if __name__ == "__main__":
    project = sys.argv[2] if len(sys.argv) > 2 else os.getcwd()
    transcript = sys.argv[1] if len(sys.argv) > 1 else newest_transcript(project)
    if not transcript:
        sys.exit("no transcript found for this folder; pass one: handoff.py TRANSCRIPT.jsonl [PROJECT_DIR]")
    print(os.path.join(project, write_handoff(transcript, project)))
