#!/usr/bin/env python3
"""Break Claude Code session spend down by billing category and by cost driver.

Reads Claude Code transcripts (~/.claude/projects/**/*.jsonl), stdlib only.
Usage: cost_anatomy.py [--root DIR] [--json OUT]

Prices are $ per million tokens: (input, cache write 5m, cache write 1h, cache read, output).
Check them against https://platform.claude.com/docs/en/about-claude/pricing before trusting totals.
"""
import argparse, collections, datetime, glob, json, os, statistics, sys

PRICES = {  # input, write_5m, write_1h, read, output
    "claude-fable-5-2": (8.00, 10.00, 16.00, 0.20, 40.00),
    "claude-opus-5-5": (4.00, 5.00, 8.00, 0.20, 20.00),
    "claude-sonnet-5-5": (2.00, 2.50, 4.00, 0.10, 10.00),
    "claude-haiku-5-5": (0.10, 0.125, 0.20, 0.01, 0.50),
}
CHARS_PER_TOKEN = 4  # rough; used only for tool-result sizes, never for billed totals
BIG_READ_TOKENS = 2000


def price(model):
    for k, v in PRICES.items():
        if model and model.startswith(k):
            return v
    return None


def text_len(content):
    if isinstance(content, str):
        return len(content)
    n = 0
    for b in content or []:
        if isinstance(b, dict):
            if b.get("type") == "text":
                n += len(b.get("text", ""))
            elif b.get("type") == "tool_result":
                n += text_len(b.get("content"))
            elif b.get("type") == "image":
                n += 6000  # ~1.5k tokens placeholder
    return n


SEEN_IDS = set()  # forked/resumed sessions repeat earlier requests; bill each once


def analyze(path):
    reqs = {}          # message id -> dict(usage, model, ts order)
    order = []
    tool_names = {}    # tool_use id -> (name, input, request index at call time)
    results = []       # (tool name, tokens, index of request that produced the call)
    events = []        # chronological ('read'|'write', path) for re-read detection
    user_prompts = 0
    out_split = collections.Counter()
    dup_tools = set()
    for line in open(path, errors="replace", encoding="utf-8"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        m = d.get("message") or {}
        if d.get("type") == "assistant" and m.get("usage") and price(m.get("model")):
            mid = m.get("id") or d.get("uuid")
            if mid in SEEN_IDS and mid not in reqs:
                dup_tools.update(b["id"] for b in m.get("content") or [] if b.get("type") == "tool_use")
                continue
            SEEN_IDS.add(mid)
            if mid not in reqs:
                reqs[mid] = {"model": m["model"], "usage": m["usage"], "ts": d.get("timestamp")}
                order.append(mid)
            elif m["usage"].get("output_tokens", 0) >= reqs[mid]["usage"].get("output_tokens", 0):
                reqs[mid]["usage"] = m["usage"]
            for b in m.get("content") or []:
                if b.get("type") == "tool_use":
                    tool_names[b["id"]] = (b["name"], b.get("input") or {}, len(order) - 1)
                    inp = b.get("input") or {}
                    out_split["tool_call_args"] += len(json.dumps(inp))
                    if b["name"] == "Read":
                        events.append(("read", inp.get("file_path"), b["id"], not ("offset" in inp or "limit" in inp),
                                       (inp.get("offset"), inp.get("limit"))))
                    elif b["name"] in ("Edit", "Write", "NotebookEdit"):
                        events.append(("write", inp.get("file_path"), b["id"], False, None))
                elif b.get("type") == "text":
                    out_split["visible_text"] += len(b.get("text", ""))
        elif d.get("type") == "user":
            c = m.get("content")
            is_tool = False
            for b in c if isinstance(c, list) else []:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    is_tool = True
                    if b.get("tool_use_id") in dup_tools:
                        continue
                    name, _, idx = tool_names.get(b.get("tool_use_id"), ("?", {}, len(order) - 1))
                    results.append((name, text_len(b.get("content")) // CHARS_PER_TOKEN, idx, b.get("tool_use_id")))
            if not is_tool and not d.get("isMeta"):
                user_prompts += 1

    n = len(order)
    cat = collections.Counter()
    tok = collections.Counter()
    by_model = collections.Counter()
    ctx = []
    split = collections.Counter()
    writes = collections.Counter()   # $ of cache writes by cause
    breaks = collections.Counter()
    prev_total, prev_model, prev_ts = 0, None, None
    thinking = 0
    for mid in order:
        r = reqs[mid]
        u, p = r["usage"], price(r["model"])
        cc = u.get("cache_creation") or {}
        w1h = cc.get("ephemeral_1h_input_tokens", 0)
        w5m = u.get("cache_creation_input_tokens", 0) - w1h
        rd, inp, out = u.get("cache_read_input_tokens", 0), u.get("input_tokens", 0), u.get("output_tokens", 0)
        thinking += (u.get("output_tokens_details") or {}).get("thinking_tokens", 0)
        c = {"uncached_input": inp * p[0], "cache_write": w5m * p[1] + w1h * p[2],
             "cache_read": rd * p[3], "output": out * p[4]}
        for k, v in c.items():
            cat[k] += v / 1e6
        tok.update({"uncached_input": inp, "cache_write": w5m + w1h, "cache_read": rd, "output": out})
        by_model[r["model"]] += sum(c.values()) / 1e6
        total = inp + w5m + w1h + rd
        ctx.append(total)
        # Cache break: a large prefix that was in context last request is being written again.
        ts = datetime.datetime.fromisoformat(r["ts"].replace("Z", "+00:00")) if r.get("ts") else None
        if prev_model is None:
            cause = "session_start"
        elif prev_total > 20000 and rd < 0.5 * prev_total:
            gap = (ts - prev_ts).total_seconds() / 60 if ts and prev_ts else 0
            cause = ("break_model_switch" if r["model"] != prev_model else
                     "break_idle_expiry" if gap > 5 else "break_other")
            breaks[cause] += 1
        else:
            cause = "normal_growth"
        writes[cause] += c["cache_write"] / 1e6
        prev_total, prev_model, prev_ts = total + out, r["model"], ts
        fixed = min(ctx[0], rd)   # the session's opening prefix (system prompt, tool schemas, memory) re-read each request
        split["fixed_prefix_reread"] += fixed * p[3] / 1e6
        split["conversation_reread"] += (rd - fixed) * p[3] / 1e6

    # Carry cost: a tool result stays in context and is re-read on every later request.
    carry = collections.Counter()
    first = collections.Counter()
    size = collections.Counter()
    calls = collections.Counter()
    main_p = price(reqs[order[0]]["model"]) if order else None
    res_tokens = {}
    for name, t, idx, tid in results:
        later = max(0, n - idx - 2)
        calls[name] += 1
        size[name] += t
        res_tokens[tid] = t
        if main_p:
            first[name] += t * main_p[2] / 1e6           # written to cache once (1h rate, Claude Code default here)
            carry[name] += t * later * main_p[3] / 1e6   # then re-read every later request (upper bound: ignores compaction)

    # Re-reads of unchanged files, and whole-file reads of big files.
    # A re-read asks again for something already in context: the same line range, or any part of a file
    # that was read whole. Reading a different range of the same file is not a re-read.
    seen, reread_tok, rereads, whole_big, whole_big_tok, reads = {}, 0, 0, 0, 0, 0
    for kind, fp, tid, whole, span in events:
        if kind == "write":
            seen.pop(fp, None)
            continue
        reads += 1
        t = res_tokens.get(tid, 0)
        ranges = seen.setdefault(fp, set())
        if "whole" in ranges or span in ranges:
            rereads += 1
            reread_tok += t
        ranges.add("whole" if whole else span)
        if whole and t >= BIG_READ_TOKENS:
            whole_big += 1
            whole_big_tok += t

    return {
        "session": os.path.basename(path)[:8], "project": os.path.basename(os.path.dirname(path))[-28:],
        "requests": n, "user_prompts": user_prompts, "cost": dict(cat), "tokens": dict(tok),
        "by_model": dict(by_model), "ctx_median": int(statistics.median(ctx)) if ctx else 0,
        "ctx_max": max(ctx) if ctx else 0, "cache_breaks": dict(breaks), "write_cost_by_cause": dict(writes), "ctx_first": ctx[0] if ctx else 0, "read_split": dict(split),
        "thinking_tokens": thinking, "out_chars": dict(out_split),
        "tool_calls": dict(calls), "tool_tokens": dict(size), "tool_first_cost": dict(first),
        "tool_carry_cost": dict(carry), "reads": reads, "rereads": rereads, "reread_tokens": reread_tok,
        "whole_big_reads": whole_big, "whole_big_read_tokens": whole_big_tok,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--json")
    a = ap.parse_args()
    files = [f for f in glob.glob(os.path.join(a.root, "**", "*.jsonl"), recursive=True)]
    rows = [r for r in (analyze(f) for f in sorted(files)) if r["requests"]]
    if not rows:
        sys.exit("no sessions with usage data found")

    def total(key):
        c = collections.Counter()
        for r in rows:
            c.update(r[key])
        return c

    cost, tokens = total("cost"), total("tokens")
    grand = sum(cost.values())
    print(f"sessions: {len(rows)}   API requests: {sum(r['requests'] for r in rows)}   "
          f"user prompts: {sum(r['user_prompts'] for r in rows)}   billed (API list price): ${grand:.2f}\n")
    print("BILLING CATEGORY        tokens        $      share")
    for k in ("cache_read", "cache_write", "uncached_input", "output"):
        print(f"  {k:<16} {tokens[k]:>12,} {cost[k]:>8.2f}   {100*cost[k]/grand:5.1f}%")
    think = sum(r["thinking_tokens"] for r in rows)
    print(f"  (thinking is {100*think/max(1,tokens['output']):.0f}% of output tokens)\n")
    print("PER SESSION             reqs prompts  req/prompt  ctx median   ctx max      $   $/req  cache breaks ($)")
    for r in rows:
        c = sum(r["cost"].values())
        print(f"  {r['project'][-14:]:<14} {r['session']} {r['requests']:>4} {r['user_prompts']:>6} "
              f"{r['requests']/max(1,r['user_prompts']):>10.1f} {r['ctx_median']:>11,} {r['ctx_max']:>9,} "
              f"{c:>6.2f} {c/r['requests']:>7.3f}   {sum(r['cache_breaks'].values())} "
              f"(${sum(v for k, v in r['write_cost_by_cause'].items() if k.startswith('break')):.2f})")
    print("\nBY MODEL")
    for k, v in total("by_model").most_common():
        print(f"  {k:<22} ${v:>7.2f}  {100*v/grand:5.1f}%")
    calls, size, first, carry = total("tool_calls"), total("tool_tokens"), total("tool_first_cost"), total("tool_carry_cost")
    print("\nTOOL RESULTS (est. tokens = chars/4)   calls   tokens   avg   write $   carry $ (re-read on later requests)")
    for k, _ in sorted(carry.items(), key=lambda x: -(x[1] + first[x[0]]))[:12]:
        print(f"  {k[:34]:<34} {calls[k]:>5} {size[k]:>9,} {size[k]//max(1,calls[k]):>6,} {first[k]:>8.2f} {carry[k]:>9.2f}")
    tr = sum(first.values()) + sum(carry.values())
    print(f"  all tool results: ${tr:.2f} = {100*tr/grand:.1f}% of spend "
          f"(Bash {100*(first['Bash']+carry['Bash'])/max(tr,1e-9):.0f}% of that, "
          f"Read/Grep/Glob {100*sum(first[k]+carry[k] for k in ('Read','Grep','Glob'))/max(tr,1e-9):.0f}%)")
    reads = sum(r["reads"] for r in rows)
    print(f"\nREADS: {reads} Read calls; {sum(r['rereads'] for r in rows)} re-reads of an unchanged file "
          f"({sum(r['reread_tokens'] for r in rows):,} tokens); "
          f"{sum(r['whole_big_reads'] for r in rows)} whole-file reads over {BIG_READ_TOKENS} tokens "
          f"({sum(r['whole_big_read_tokens'] for r in rows):,} tokens)")
    wc, br = total("write_cost_by_cause"), total("cache_breaks")
    print("\nCACHE WRITES BY CAUSE          n        $   share of all spend")
    for k in ("normal_growth", "break_idle_expiry", "break_model_switch", "break_other", "session_start"):
        print(f"  {k:<22} {br.get(k, ''):>6} {wc[k]:>8.2f}   {100*wc[k]/grand:5.1f}%")
    rs = total("read_split")
    print("\nCACHE READS")
    for k, v in rs.items():
        print(f"  {k:<22}        {v:>8.2f}   {100*v/grand:5.1f}%")
    oc = total("out_chars")
    print(f"\nOUTPUT (chars): visible text {oc['visible_text']:,}, tool-call arguments {oc['tool_call_args']:,}; "
          f"thinking {think:,} tokens")
    firsts = [r["ctx_first"] for r in rows if r["ctx_first"] > 5000]
    print(f"FIXED PREFIX: first request of a session carries a median {int(statistics.median(firsts)):,} tokens before any work")
    if a.json:
        json.dump(rows, open(a.json, "w", encoding="utf-8"), indent=1)


if __name__ == "__main__":
    main()
