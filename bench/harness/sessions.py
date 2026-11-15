#!/usr/bin/env python3
"""Session test: what do the two session-level choices that turnwise's guards point at actually cost?

  python3 bench/harness/sessions.py --selftest      check the follow-up tasks themselves; no model, no cost
  python3 bench/harness/sessions.py --budget 10     run it (costs real money; about an hour, mostly waiting)

For each of two large sessions (about 110k tokens of context), it measures:

  stale session   the same follow-up bug fix done two ways after the prompt cache has expired:
                    resume  continue the old session
                    fresh   start a new session from the handoff note turnwise writes
  model switch    the same small job done two ways while the session's cache is still warm:
                    switch  continue the session on a cheaper model
                    stay    continue on the same model

No plugin is loaded in any run. The "fresh" way uses only the handoff note built by turnwise/scripts/handoff.py.
Before every run the repo copy and the session transcript are put back exactly as the build left them.
Results: <results>/summary.csv and <results>/raw/.
"""
import argparse, csv, glob, json, os, re, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run as H        # noqa: E402  (shared pieces of the task harness)
import tasks as T      # noqa: E402

TOOLS = ["Read", "Edit", "Write", "Grep", "Glob", "Bash"]     # no subagents: the build must fill this session's own context
FIELDS = ["session", "scenario", "way", "trial", "passed", "cost_usd", "requests", "duration_s", "context_before",
          "first_cache_read", "first_cache_write", "cache_write", "cache_read", "output", "model", "claude_version", "detail"]
MIN_CONTEXT = 80000


def click_mutate(work):
    T.edit(os.path.join(work, "src/click/types.py"),
           'if norm in {"1", "true", "t", "yes", "y", "on"}:', 'if norm in {"1", "true", "t", "yes", "y"}:')


def click_check(work, pristine, answer):
    T.restore(work, pristine, "tests")
    return T.pytest(work, "click", H.PYTHON, "tests/test_basic.py")


def mi_check(work, pristine, answer):
    T.restore(work, pristine, "tests")
    return T.pytest(work, "more-itertools", H.PYTHON, "tests/test_more.py")


def names_check(path, names):
    def check(work, pristine, answer):
        p = os.path.join(work, path)
        if not os.path.exists(p):
            return False, f"{path} was not written"
        text = open(p).read()
        missing = [n for n in names if not re.search(rf"\b{re.escape(n)}\b", text)]
        return not missing, "all names present" if not missing else "missing: " + ", ".join(missing)
    return check


SESSIONS = [
    {"id": "click", "repo": "click", "mutate": click_mutate,
     "build": "Read every Python file under src/click from its first line to its last. Use the Read tool, not shell "
              "commands, and as many reads as it takes; do not skip or skim any file. Then write NOTES.md with a "
              "two-sentence summary of each file.",
     "followup": "A boolean option rejects the value \"on\": with @click.option(\"--flag\", type=bool), running the "
                 "command with --flag on fails with \"'on' is not a valid boolean\". Find the cause and fix it. "
                 "Run the relevant tests to confirm.",
     "followup_check": click_check, "followup_solve": T.from_pristine("src/click/types.py"),
     "small": "Write FUNCS.md listing the name of every top-level function defined in src/click/utils.py, one per line.",
     "small_check": names_check("FUNCS.md", ["make_str", "echo", "open_file", "get_app_dir", "format_filename", "get_text_stream"]),
     "small_solve": "make_str\necho\nopen_file\nget_app_dir\nformat_filename\nget_text_stream\n"},
    {"id": "more-itertools", "repo": "more-itertools", "mutate": T.mi_mutate,
     "build": "Read more_itertools/more.py, more_itertools/recipes.py and tests/test_more.py from first line to last. "
              "Use the Read tool, not shell commands, and as many reads as it takes; do not skip or skim. Then write "
              "NOTES.md with a one-line description of twenty functions you found most useful.",
     "followup": "list(chunked_even([1, 2, 3, 4, 5, 6], 3)) should return two lists of three items, but it returns "
                 "three lists of two. Find the cause and fix it. Run the relevant tests to confirm.",
     "followup_check": mi_check, "followup_solve": T.from_pristine("more_itertools/more.py"),
     "small": "Write FUNCS.md listing the name of every top-level function defined in more_itertools/recipes.py, one per line.",
     "small_check": names_check("FUNCS.md", ["take", "tabulate", "nth", "flatten", "grouper", "roundrobin"]),
     "small_solve": "take\ntabulate\nnth\nflatten\ngrouper\nroundrobin\n"},
]


def selftest():
    ok = True
    for s in SESSIONS:
        pristine = os.path.join(H.CACHE, s["repo"])
        for name in ("followup", "small"):
            work = H.prepare(s)
            before, d1 = s[name + "_check"](work, pristine, "")
            if name == "followup":
                s["followup_solve"](work, pristine)
            else:
                with open(os.path.join(work, "FUNCS.md"), "w") as f:
                    f.write(s["small_solve"])
            after, d2 = s[name + "_check"](work, pristine, "")
            shutil.rmtree(os.path.dirname(work), ignore_errors=True)
            good = (not before) and after
            ok &= good
            print(f"{'ok  ' if good else 'FAIL'} {s['id']:<16}{name:<9} unsolved: {'pass' if before else 'fail'} ({d1[:44]}) | solved: {'pass' if after else 'fail'} ({d2[:36]})")
    return ok


def requests_in(path):
    """Usage of each API request recorded in a transcript, in order."""
    seen, out = {}, []
    with open(path, errors="replace") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            m = d.get("message") if isinstance(d, dict) else None
            if isinstance(m, dict) and d.get("type") == "assistant" and m.get("usage") and not d.get("isSidechain"):
                if m.get("id") not in seen:
                    out.append(m["usage"])
                seen[m.get("id")] = True
    return out


def context_of(usage):
    return usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0) + usage.get("cache_creation_input_tokens", 0)


class Runner:
    def __init__(self, a):
        self.a = a
        self.claude = H.find_claude(a.claude)
        try:
            self.version = H.sh(self.claude, "--version").stdout.split()[0]
        except (OSError, subprocess.CalledProcessError, IndexError):
            sys.exit(f"could not run the claude CLI at {self.claude}; pass --claude PATH")
        self.results = os.path.abspath(a.results)
        self.spent = 0.0
        self.temps = []          # every throwaway folder made, so an early exit can still remove them
        self.rows = []
        self.file = None
        self.checked = False

    def call(self, prompt, work, repo, model, cap, resume=None):
        env = {**os.environ, "PATH": os.path.join(H.VENV, "bin") + os.pathsep + os.environ["PATH"],
               "PYTHONPATH": os.path.join(work, T.REPOS[repo][3]), "PYTHONDONTWRITEBYTECODE": "1"}
        cmd = [self.claude, "-p", prompt, "--model", model, "--output-format", "json", "--allowedTools", *TOOLS,
               "--permission-mode", "acceptEdits", "--setting-sources", "project", "--strict-mcp-config",
               "--max-budget-usd", f"{cap:.2f}"]
        if resume:
            cmd += ["--resume", resume]
        start = time.time()
        try:
            r = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=H.TIMEOUT)
            out = json.loads(r.stdout)
        except subprocess.TimeoutExpired:
            out = {"result": "", "detail": f"timed out after {H.TIMEOUT} seconds"}
        except ValueError:
            out = {"result": "", "detail": "no JSON from claude: " + (r.stdout + r.stderr)[-200:]}
        out["seconds"] = round(time.time() - start, 1)
        if re.match(r"\s*(Not logged in|Invalid API key|Please run /login)", out.get("result") or ""):
            stale = H.transcript_for(out.get("session_id") or "-")
            if stale and "turnwise-bench-" in os.path.basename(os.path.dirname(stale)):
                shutil.rmtree(os.path.dirname(stale), ignore_errors=True)
            self.cleanup_all()
            sys.exit("claude is not logged in. Run it once interactively and use /login, or set ANTHROPIC_API_KEY, then retry.")
        return out

    def estimate(self, b, way):
        """Rough cost of one run, from list prices and this session's real size."""
        write = {"claude-opus-5-5": 5.0, "claude-sonnet-5-5": 2.5, "claude-haiku-5-5": 0.125, "claude-fable-5-2": 10.0}
        if way == "resume":
            return b["context"] * write.get(self.a.model, 5.0) / 1e6 + 0.20
        if way == "switch":
            return b["context"] * write.get(self.a.cheap_model, 2.5) / 1e6 + 0.10
        return 0.40 if way == "fresh" else 0.20

    def save_row(self, row, fields):
        """Append one row, retrying if the disk stalls (a synced folder can time out). Never raises."""
        path = os.path.join(self.results, "summary.csv")
        if not self.checked:
            self.checked = True
            if os.path.exists(path):
                with open(path) as old:
                    if old.readline().strip().split(",") != fields:
                        self.cleanup_all()
                        sys.exit(f"{path} has different columns from this version. Move it aside and run again.")

        def write():
            os.makedirs(self.results, exist_ok=True)
            new = not os.path.exists(path) or os.path.getsize(path) == 0
            with open(path, "a", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                if new:
                    w.writeheader()
                w.writerow(row)
        if not H.retry(write, "write a row to summary.csv"):
            print("    that row is NOT saved; copy it from the line printed below", flush=True)

    def room(self, need):
        if self.a.budget - self.spent < need:
            print(f"budget: ${self.spent:.2f} of ${self.a.budget:.2f} spent, not enough left for the next step (${need:.2f}); stopping")
            return False
        return True

    def wait(self, why):
        if self.a.wait > 0:
            print(f"  waiting {self.a.wait}s so the prompt cache expires ({why})", flush=True)
            time.sleep(self.a.wait)

    def build(self, s):
        """Create the large session and keep a copy of the repo and the transcript as the build left them."""
        work = H.prepare(s)
        self.temps.append(os.path.dirname(work))
        out = self.call(s["build"], work, s["repo"], self.a.model, 3.0)
        self.spent += out.get("total_cost_usd") or 0
        sid = out.get("session_id")
        transcript = H.transcript_for(sid) if sid else None
        if not transcript:
            print(f"  {s['id']}: build failed ({out.get('detail') or out.get('subtype') or 'no transcript'})")
            shutil.rmtree(os.path.dirname(work), ignore_errors=True)
            return None
        usage = requests_in(transcript)
        context = context_of(usage[-1]) + usage[-1].get("output_tokens", 0) if usage else 0
        keep = tempfile.mkdtemp(prefix="turnwise-bench-keep-")
        self.temps.append(keep)
        shutil.copytree(work, os.path.join(keep, "repo"), symlinks=True)
        shutil.copy2(transcript, os.path.join(keep, "base.jsonl"))
        raw = os.path.join(self.results, "raw")
        os.makedirs(raw, exist_ok=True)
        shutil.copy2(transcript, os.path.join(raw, f"{s['id']}-build.jsonl"))
        print(f"  built {s['id']}: context {context:,} tokens, ${out.get('total_cost_usd') or 0:.2f}, {out['seconds']}s")
        b = {"s": s, "work": work, "sid": sid, "transcript": transcript, "keep": keep, "context": context,
             "nreq": len(usage), "cost": out.get("total_cost_usd") or 0}
        out["num_turns"] = len(usage)
        self.record(b, "build", "build", 0, out, True, f"context {context:,} tokens", usage[:1], context_before=0)
        if context < MIN_CONTEXT:
            print(f"  {s['id']}: context is below {MIN_CONTEXT:,} tokens, too small to be a useful test; skipping this session")
            self.drop(b)
            return None
        return b

    def reset(self, b):
        """Put the repo copy and the session transcript back exactly as the build left them."""
        for name in os.listdir(b["work"]):
            p = os.path.join(b["work"], name)
            shutil.rmtree(p) if os.path.isdir(p) and not os.path.islink(p) else os.remove(p)
        for name in os.listdir(os.path.join(b["keep"], "repo")):
            src, dst = os.path.join(b["keep"], "repo", name), os.path.join(b["work"], name)
            shutil.copytree(src, dst, symlinks=True) if os.path.isdir(src) and not os.path.islink(src) else shutil.copy2(src, dst)
        project = os.path.dirname(b["transcript"])
        for p in glob.glob(os.path.join(project, "*")):
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
        shutil.copy2(os.path.join(b["keep"], "base.jsonl"), b["transcript"])

    def measure(self, b, scenario, way, trial):
        s = b["s"]
        need = self.estimate(b, way)
        if not self.room(need * 1.25):
            return False
        self.reset(b)
        pristine = os.path.join(H.CACHE, s["repo"])
        job = "followup" if scenario == "stale" else "small"
        prompt, model, resume = s[job], self.a.model, b["sid"]
        if way == "fresh":
            note = subprocess.run([sys.executable, os.path.join(H.PLUGIN, "scripts", "handoff.py"), b["transcript"], b["work"]],
                                  capture_output=True, text=True)
            if note.returncode != 0:
                print(f"  could not write the handoff note: {note.stderr.strip()[:120]}")
                return True
            prompt, resume = "Continue from .turnwise/handoff.md, which describes the previous session. " + prompt, None
        if way == "switch":
            model = self.a.cheap_model
        out = self.call(prompt, b["work"], s["repo"], model, (b["cost"] if resume else 0) + need + 1.0, resume)
        if resume and out.get("total_cost_usd") is not None:
            out["total_cost_usd"] = max(0.0, out["total_cost_usd"] - b["cost"])
        self.spent += out.get("total_cost_usd") or 0
        try:
            passed, detail = s[job + "_check"](b["work"], pristine, out.get("result") or "")
        except Exception as e:
            passed, detail = False, f"check crashed: {e}"
        if out.get("detail"):
            passed, detail = False, out["detail"]
        elif out.get("subtype") not in (None, "success"):
            detail = f"[{out['subtype']}] {detail}"
        # A resumed session may keep its id or get a new one that repeats the history; either way the
        # requests made by this run are the ones after the build's own.
        src = H.transcript_for(out.get("session_id") or "-") or (b["transcript"] if resume else None)
        usage = requests_in(src) if src else []
        if resume:
            usage = usage[b["nreq"]:]
        out["usage"] = {k: sum(u.get(k, 0) for u in usage) for k in
                        ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")}
        out["num_turns"] = len(usage)
        self.record(b, scenario, way, trial, out, passed, detail, usage[:1], context_before=b["context"] if resume else 0, model=model)
        if src:
            shutil.copy2(src, os.path.join(self.results, "raw", f"{s['id']}-{scenario}-{way}-{trial}.jsonl"))
            other = os.path.dirname(src)             # a new session normally lands in the same project folder; if not, remove it
            if other != os.path.dirname(b["transcript"]) and "turnwise-bench-" in os.path.basename(other):
                shutil.rmtree(other, ignore_errors=True)
        return True

    def record(self, b, scenario, way, trial, out, passed, detail, first, context_before, model=None):
        u = out.get("usage") or {}
        f0 = first[0] if first else {}
        row = {"session": b["s"]["id"], "scenario": scenario, "way": way, "trial": trial, "passed": int(passed),
               "cost_usd": round(out.get("total_cost_usd") or 0, 4), "requests": out.get("num_turns", ""),
               "duration_s": out.get("seconds", ""), "context_before": context_before,
               "first_cache_read": f0.get("cache_read_input_tokens", ""), "first_cache_write": f0.get("cache_creation_input_tokens", ""),
               "cache_write": u.get("cache_creation_input_tokens", ""), "cache_read": u.get("cache_read_input_tokens", ""),
               "output": u.get("output_tokens", ""), "model": model or self.a.model, "claude_version": self.version,
               "detail": detail[:160]}
        self.rows.append(row)
        self.save_row(row, FIELDS)
        if scenario != "build":
            print(f"  {'PASS' if passed else 'FAIL'} {row['session']:<15}{scenario:<13}{way:<7} trial {trial}  ${row['cost_usd']:.2f}  "
                  f"first request: {row['first_cache_read'] or 0:,} read / {row['first_cache_write'] or 0:,} written  {detail[:40]}", flush=True)

    def drop(self, b):
        shutil.rmtree(os.path.dirname(b["work"]), ignore_errors=True)
        shutil.rmtree(b["keep"], ignore_errors=True)
        project = os.path.dirname(b["transcript"])
        if "turnwise-bench-" in os.path.basename(project):
            shutil.rmtree(project, ignore_errors=True)

    def cleanup_all(self):
        for b in getattr(self, "built", []):
            self.drop(b)
        for d in self.temps:
            shutil.rmtree(d, ignore_errors=True)
        if self.file:
            self.file.close()

    def go(self):
        a = self.a
        print(f"session test · model {a.model} · cheaper model {a.cheap_model} · claude {self.version} · "
              f"{a.trials} trial(s) · budget ${a.budget:.2f}")
        self.built = []
        sessions = [s for s in SESSIONS if not a.sessions or s["id"] in a.sessions]
        try:
            # Step 1: build each session, then measure the model switch at once, while its cache is still warm.
            for i, s in enumerate(sessions):
                if not self.room(3.0):
                    break
                b = self.build(s)
                if not b:
                    continue
                self.built.append(b)
                for way in (("stay", "switch") if i % 2 == 0 else ("switch", "stay")):
                    if "model-switch" in a.scenarios and not self.measure(b, "model-switch", way, 1):
                        return
            if self.built:
                plan = [(b, w) for b in self.built for w in (("resume", "fresh") if "stale" in a.scenarios else ())] * a.trials
                plan += [(b, w) for b in self.built for w in (("switch", "stay") if "model-switch" in a.scenarios else ())] * (a.trials - 1)
                left = sum(self.estimate(b, w) for b, w in plan)
                print(f"  spent ${self.spent:.2f} so far; the remaining {len(plan)} runs should cost about ${left:.2f} "
                      f"(budget ${a.budget:.2f})", flush=True)
            # Step 2: stale-session runs. Each one starts after a wait, so nothing it needs is still cached.
            # A resume leaves the session's cache warm, so later model-switch trials follow it directly.
            for trial in range(1, a.trials + 1):
                for i, b in enumerate(self.built):
                    order = ("fresh", "resume") if (i + trial) % 2 == 0 else ("resume", "fresh")
                    for way in (order if "stale" in a.scenarios else ()):
                        self.wait(f"before {b['s']['id']} {way}")
                        if not self.measure(b, "stale", way, trial):
                            return
                        if way == "resume" and trial < a.trials and "model-switch" in a.scenarios:
                            for w in (("switch", "stay") if (i + trial) % 2 == 0 else ("stay", "switch")):
                                if not self.measure(b, "model-switch", w, trial + 1):
                                    return
        finally:
            self.cleanup_all()
            self.report()

    def report(self):
        runs = [r for r in self.rows if r["scenario"] != "build"]
        print(f"\nspent ${self.spent:.2f} · {len(runs)} measured runs · results in {os.path.relpath(self.results)}")
        for scenario, ways in (("stale", ("resume", "fresh")), ("model-switch", ("switch", "stay"))):
            line = []
            for way in ways:
                mine = [r for r in runs if r["scenario"] == scenario and r["way"] == way]
                if mine:
                    line.append(f"{way}: ${sum(r['cost_usd'] for r in mine) / len(mine):.3f} mean over {len(mine)}, "
                                f"{sum(r['passed'] for r in mine)}/{len(mine)} passed")
            if line:
                print(f"  {scenario:<13} " + "  |  ".join(line))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--sessions", nargs="*", help="session ids to use (default: all): " + ", ".join(s["id"] for s in SESSIONS))
    ap.add_argument("--scenarios", nargs="+", choices=["stale", "model-switch"], default=["stale", "model-switch"])
    ap.add_argument("--trials", type=int, default=2)
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--cheap-model", default="claude-sonnet-5-5")
    ap.add_argument("--budget", type=float, default=10.0)
    ap.add_argument("--wait", type=int, default=360, help="seconds to wait before each stale-session run (cache lifetime is 300)")
    ap.add_argument("--results", default=os.path.join(H.RESULTS, "sessions"))
    ap.add_argument("--claude")
    a = ap.parse_args()
    if a.trials < 1 or a.budget <= 0 or a.wait < 0:
        ap.error("--trials and --budget must be positive, --wait must not be negative")
    if a.sessions and set(a.sessions) - {s["id"] for s in SESSIONS}:
        ap.error("unknown session id")
    H.setup()
    if a.selftest:
        sys.exit(0 if selftest() else 1)
    Runner(a).go()


if __name__ == "__main__":
    main()
