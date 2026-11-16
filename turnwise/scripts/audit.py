#!/usr/bin/env python3
"""Show what fills the fixed prefix that every request re-reads, and what each part costs.

Usage: audit.py [--root DIR] [--model MODEL] [--requests N]
Reads the newest session under ~/.claude/projects that recorded its request shape, and counts how
often each tool group was actually called across all sessions. Sizes are estimated at 4 characters per token.
"""
import argparse, collections, glob, json, os

from cost_anatomy import PRICES, price


def group(name):
    return name.split("__")[1] if name.startswith("mcp__") else "(built-in tools)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--requests", type=int, default=100)
    a = ap.parse_args()
    files = sorted(glob.glob(os.path.join(a.root, "**", "*.jsonl"), recursive=True), key=os.path.getmtime)
    shape, calls, sessions = None, collections.Counter(), 0
    for f in files:
        used = False
        for line in open(f, errors="replace", encoding="utf-8"):
            if '"api-request-shape"' in line[:60]:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(d, dict) or not isinstance(d.get("shape"), dict):
                    continue
                if len(d["shape"].get("tools", [])) >= 10:   # skip subagent shapes; newest main session wins
                    shape = d["shape"]
            elif '"tool_use"' in line:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(d, dict):
                    continue
                for b in (d.get("message") or {}).get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        calls[group(b["name"])] += 1
                        used = True
        sessions += used
    if not shape:
        raise SystemExit("no session with a recorded request shape found")
    p = price(a.model) or PRICES["claude-opus-5-5"]
    size = collections.Counter({"(system prompt)": sum(len(json.dumps(b)) for b in shape.get("system", [])) // 4})
    count = collections.Counter()
    for t in shape.get("tools", []):
        size[group(t["name"])] += len(json.dumps(t)) // 4
        count[group(t["name"])] += 1
    total = sum(size.values())
    print(f"Fixed prefix of the newest session: about {total:,} tokens "
          f"({len(shape.get('tools', []))} tool definitions). Prices for {a.model}.\n")
    print(f"{'part':<40} {'tools':>5} {'tokens':>8} {'$ per ' + str(a.requests) + ' requests':>20} {'calls in ' + str(sessions) + ' sessions':>22}")
    for k, v in size.most_common():
        fixed = k.startswith("(")
        print(f"{k[:40]:<40} {count[k] or '':>5} {v:>8,} {v * a.requests * p[3] / 1e6:>20.3f} "
              f"{'' if k == '(system prompt)' else calls[k]:>22}{'' if fixed else '   <- never called' if not calls[k] else ''}")
    removable = sum(v for k, v in size.items() if not k.startswith("("))
    unused = sum(v for k, v in size.items() if not k.startswith("(") and not calls[k])
    print(f"\nMCP servers and app tools: {removable:,} tokens ({100 * removable // total}% of the prefix). "
          f"Never called in these sessions: {unused:,} tokens.")
    print("Each of those tokens is written once per session and re-read on every request. "
          "Turn off a server you don't use in your MCP settings; this script changes nothing.")


if __name__ == "__main__":
    main()
