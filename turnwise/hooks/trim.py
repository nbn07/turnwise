#!/usr/bin/env python3
"""PostToolUse: shorten large, noisy tool results before the model reads them. Off by default.

Covers Bash and MCP tools. The full text is saved under .turnwise/full/ so the agent can read it back.
Everything is deterministic and decided once per result, so the prompt cache is never disturbed.
Passes through untouched: small results, images, and commands whose exact output matters (file views, diffs).
"""
import json, os, re, sys, time

MIN_CHARS = 8000        # about 2k tokens; below this, leave the result alone
BUDGET = 6000           # target size of a trimmed result
MIN_SAVING = 0.30       # replace only when at least this fraction is removed
LINE_MAX = 400
KEEP_ITEMS = 10
KEEP_DAYS = 7
# Commands whose output the agent asked for line by line: file views, diffs, searches, listings.
EXACT = re.compile(r"(^|[;&|(]\s*)(?:\w+=\S+\s+|sudo\s+)*"
                   r"(git\s+(diff|show|blame|log|status|ls-files|grep)|cat|sed|awk|head|tail|diff|nl|less|bat|jq|xxd"
                   r"|grep|rg|ag|find|fd|ls|tree|wc)\b")
MIN_RUN = 4             # collapse only runs of at least this many similar lines, keeping the first and last


def shrink_json(value, depth=0):
    """Keep the first items of long lists and say how many were dropped."""
    if isinstance(value, list):
        kept = [shrink_json(v, depth + 1) for v in value[:KEEP_ITEMS]]
        if len(value) > KEEP_ITEMS:
            kept.append(f"… {len(value) - KEEP_ITEMS} more items of {len(value)} not shown")
        return kept
    if isinstance(value, dict) and depth < 6:
        return {k: shrink_json(v, depth + 1) for k, v in value.items()}
    if isinstance(value, str) and len(value) > LINE_MAX * 2:
        return value[:LINE_MAX * 2] + f"… ({len(value) - LINE_MAX * 2} more characters)"
    return value


def shrink_text(text):
    stripped = text.strip()
    if stripped[:1] in "[{":
        try:
            text = json.dumps(shrink_json(json.loads(stripped)), indent=1, ensure_ascii=False)
        except ValueError:
            pass
    # Collapse runs of lines that differ only in their numbers (progress output, repeated log lines).
    clip = lambda l: l if len(l) <= LINE_MAX else l[:LINE_MAX] + f"… ({len(l) - LINE_MAX} more characters)"
    out, group, prev = [], [], None

    def flush():
        if len(group) >= MIN_RUN:
            out.extend([clip(group[0]), f"… {len(group) - 2} similar lines not shown", clip(group[-1])])
        else:
            out.extend(clip(l) for l in group)

    for line in text.split("\n"):
        key = re.sub(r"\d+", "#", line.strip())
        if group and key and key == prev:
            group.append(line)
            continue
        flush()
        group, prev = [line], key
    flush()
    text = "\n".join(out)
    if len(text) > BUDGET:
        head, tail = text[:BUDGET // 2], text[-BUDGET // 2 + 500:]
        head = head[:head.rfind("\n") + 1] or head
        tail = tail[tail.find("\n") + 1:] or tail
        cut = text.count("\n") - head.count("\n") - tail.count("\n")
        text = f"{head}… {cut} lines in the middle not shown\n{tail}"
    return text


def save_full(cwd, tool_use_id, text):
    d = os.path.join(cwd, ".turnwise", "full")
    os.makedirs(d, exist_ok=True)
    exclude = os.path.join(cwd, ".git", "info", "exclude")
    if os.path.isdir(os.path.dirname(exclude)):
        have = open(exclude, encoding="utf-8").read() if os.path.exists(exclude) else ""
        if ".turnwise/" not in have:
            open(exclude, "a", encoding="utf-8").write(("" if have.endswith("\n") or not have else "\n") + ".turnwise/\n")
    cutoff = time.time() - KEEP_DAYS * 86400
    for f in os.listdir(d):
        fp = os.path.join(d, f)
        if os.path.getmtime(fp) < cutoff:
            os.remove(fp)
    name = re.sub(r"[^A-Za-z0-9_-]", "", tool_use_id or "")[-24:] or str(int(time.time()))
    path = os.path.join(d, name + ".txt")
    open(path, "w", encoding="utf-8").write(text)
    return ".turnwise/full/" + name + ".txt"  # shown to the agent: forward slashes on every OS


def trim(text, cwd, tool_use_id):
    """Return the shortened text, or None to leave the result alone."""
    if not isinstance(text, str) or len(text) < MIN_CHARS:
        return None
    short = shrink_text(text)
    if len(short) > len(text) * (1 - MIN_SAVING):
        return None
    path = save_full(cwd, tool_use_id, text)
    return f"{short}\n[turnwise: shortened from {len(text):,} to {len(short):,} characters. Full output: {path}]"


def main():
    from common import HOME, config
    d = json.loads(sys.stdin.buffer.read())
    if not config().get("trim") or os.environ.get("TURNWISE_OFF"):
        return
    name, resp = d.get("tool_name", ""), d.get("tool_response")
    cwd, tid = d.get("cwd") or os.getcwd(), d.get("tool_use_id")
    before = after = 0
    if name == "Bash" and isinstance(resp, dict):
        if resp.get("isImage") or resp.get("interrupted") or EXACT.search((d.get("tool_input") or {}).get("command", "")):
            return
        new = trim(resp.get("stdout"), cwd, tid)
        if new is None:
            return
        before, after = len(resp["stdout"]), len(new)
        resp = {**resp, "stdout": new}
    elif name.startswith("mcp__"):
        if isinstance(resp, str):
            new = trim(resp, cwd, tid)
            if new is None:
                return
            before, after, resp = len(resp), len(new), new
        elif isinstance(resp, list):
            blocks = []
            for i, b in enumerate(resp):
                new = trim(b.get("text"), cwd, f"{tid}-{i}") if isinstance(b, dict) and b.get("type") == "text" else None
                if new is not None:
                    before, after = before + len(b["text"]), after + len(new)
                    b = {**b, "text": new}
                blocks.append(b)
            if not before:
                return
            resp = blocks
        else:
            return
    else:
        return
    os.makedirs(HOME, exist_ok=True)
    open(os.path.join(HOME, "trim.log"), "a", encoding="utf-8").write(json.dumps(
        {"ts": int(time.time()), "session": d.get("session_id"), "tool": name, "before": before, "after": after}) + "\n")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": resp}}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
