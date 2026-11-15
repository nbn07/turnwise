#!/usr/bin/env python3
"""Run the pilot tasks through Claude Code and record cost and pass/fail. Stdlib only.

  python3 bench/harness/run.py --selftest            prove every check can fail and can pass; no model, no cost
  python3 bench/harness/run.py --arm baseline        run the tasks with no plugin   (costs real money)
  python3 bench/harness/run.py --arm turnwise        same tasks with the turnwise plugin loaded
  python3 bench/harness/run.py --arm turnwise-trim   plugin loaded and adaptive trim switched on

Each task runs in a fresh throwaway copy of its repo in the system temp folder. Results go to
bench/results/raw/<arm>/ (one transcript and one JSON per run) and bench/results/summary.csv.
"""
import argparse, csv, glob, json, os, re, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.dirname(HERE)
PLUGIN = os.path.join(os.path.dirname(BENCH), "turnwise")
CACHE = os.path.join(BENCH, ".cache")
VENV = os.path.join(BENCH, ".venv")
PYTHON = os.path.join(VENV, "bin", "python")
RESULTS = os.environ.get("BENCH_RESULTS") or os.path.join(BENCH, "results")
PROJECTS = os.environ.get("BENCH_PROJECTS") or os.path.expanduser("~/.claude/projects")
TIMEOUT = int(os.environ.get("BENCH_TIMEOUT") or 1800)   # seconds per task
ARMS = {"baseline": {"plugin_dir": None, "trim": False}, "turnwise": {"plugin_dir": PLUGIN, "trim": False},
        "turnwise-trim": {"plugin_dir": PLUGIN, "trim": True}}
TOOLS = ["Read", "Edit", "Write", "Grep", "Glob", "Bash", "Task"]   # Task = subagents, so delegation is possible in every arm
FIELDS = ["arm", "task", "kind", "run", "passed", "cost_usd", "turns", "duration_s", "uncached_input", "cache_write",
          "cache_read", "output", "model", "claude_version", "session_id", "detail"]
sys.path.insert(0, HERE)
from tasks import REPOS, TASKS  # noqa: E402


_fail_writes = int(os.environ.get("BENCH_FAIL_WRITES") or 0)   # test hook: make the first N result writes time out


def retry(action, what, tries=6):
    """Run a file operation, retrying when the disk stalls (a synced folder such as OneDrive can time out).

    Returns True on success. After the last try it reports the problem and returns False; it never raises,
    because a paid run must not be thrown away over a slow disk.
    """
    global _fail_writes
    for attempt in range(tries):
        try:
            if _fail_writes > 0:
                _fail_writes -= 1
                raise TimeoutError(60, "Operation timed out (injected by BENCH_FAIL_WRITES)")
            action()
            return True
        except OSError as e:
            if attempt == tries - 1:
                print(f"    could not {what}: {e}", flush=True)
                return False
            time.sleep(float(os.environ.get("BENCH_RETRY_SECONDS") or 1.0) * 2 ** attempt)
    return False


def append_row(summary, row):
    def write():
        new = not os.path.exists(summary) or os.path.getsize(summary) == 0
        with open(summary, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if new:
                w.writeheader()
            w.writerow(row)
    return retry(write, f"write a row to {os.path.basename(summary)}")


def recover_rows(summary, results):
    """Add to summary.csv any finished run whose own result file exists but whose row was never written."""
    have = set()
    if os.path.exists(summary):
        with open(summary, newline="") as f:
            have = {(r["arm"], r["task"], str(r["run"])) for r in csv.DictReader(f)}
    added = 0
    for path in sorted(glob.glob(os.path.join(results, "raw", "*", "*.result.json")), key=os.path.getmtime):
        try:
            with open(path) as f:
                row = json.load(f)["row"]
        except (OSError, ValueError, KeyError):
            continue
        key = (row.get("arm"), row.get("task"), str(row.get("run")))
        if key not in have and set(row) == set(FIELDS) and append_row(summary, row):
            have.add(key)
            added += 1
    return added


def sh(*cmd, cwd=None, check=True):
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def setup():
    """Fetch each repo at its pinned commit and build the test environment. Safe to run again."""
    os.makedirs(CACHE, exist_ok=True)
    for name, (url, tag, commit, _) in REPOS.items():
        d = os.path.join(CACHE, name)
        if not os.path.isdir(d):
            print(f"fetching {name} {tag}")
            sh("git", "clone", "-q", "--depth", "1", "--branch", tag, url, d)
        have = sh("git", "rev-parse", "HEAD", cwd=d).stdout.strip()
        if have != commit:
            sys.exit(f"{name}: expected commit {commit}, found {have}. Delete {d} and run again.")
    if not os.path.exists(PYTHON):
        print("building test environment")
        sh(sys.executable, "-m", "venv", VENV)
        sh(os.path.join(VENV, "bin", "pip"), "-q", "install", "pytest==8.4.2", "freezegun", "humanize==4.9.0")


def prepare(task):
    """A fresh copy of the repo with the task's starting change applied, as a single commit with no history."""
    work = os.path.join(tempfile.mkdtemp(prefix="turnwise-bench-"), task["repo"])
    shutil.copytree(os.path.join(CACHE, task["repo"]), work, ignore=shutil.ignore_patterns(".git"))
    if task["mutate"]:
        task["mutate"](work)
    for args in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.name=bench", "-c", "user.email=bench@example.invalid", "commit", "-q", "-m", "initial"]):
        sh("git", *args, cwd=work)
    return work


def selftest(tasks):
    ok = True
    for t in tasks:
        pristine = os.path.join(CACHE, t["repo"])
        work = prepare(t)
        before, d1 = t["check"](work, pristine, PYTHON, "")
        shutil.rmtree(os.path.dirname(work), ignore_errors=True)
        work = prepare(t)
        if t["solve"]:
            t["solve"](work, pristine)
        after, d2 = t["check"](work, pristine, PYTHON, t.get("reference_answer", ""))
        shutil.rmtree(os.path.dirname(work), ignore_errors=True)
        good = (not before) and after
        ok &= good
        print(f"{'ok  ' if good else 'FAIL'} {t['id']:<34} unsolved: {'pass' if before else 'fail'} ({d1[:48]}) | solved: {'pass' if after else 'fail'} ({d2[:40]})")
    return ok


def find_claude(explicit):
    if explicit:
        return explicit
    found = shutil.which("claude")
    if found:
        return found
    bundled = sorted(glob.glob(os.path.expanduser(
        "~/Library/Application Support/Claude/claude-code/*/*/claude.app/Contents/MacOS/claude")))
    if bundled:
        return bundled[-1]
    sys.exit("could not find the claude CLI; pass --claude PATH")


def transcript_for(session_id):
    hits = glob.glob(os.path.join(PROJECTS, "*", session_id + ".jsonl"))
    return hits[0] if hits else None


def run_task(claude, version, arm, task, run, model, effort, cap, keep, results=RESULTS):
    cfg = ARMS[arm]
    work = prepare(task)
    home = tempfile.mkdtemp(prefix="turnwise-bench-home-")
    env = {**os.environ, "PATH": os.path.join(VENV, "bin") + os.pathsep + os.environ["PATH"],
           "PYTHONPATH": os.path.join(work, REPOS[task["repo"]][3]), "TURNWISE_HOME": home, "PYTHONDONTWRITEBYTECODE": "1"}
    env.update(cfg.get("env", {}))
    if cfg["trim"]:
        subprocess.run([sys.executable, os.path.join(PLUGIN, "scripts", "config.py"), "trim", "on"], env=env, capture_output=True)
    cmd = [claude, "-p", task["prompt"], "--model", model, "--output-format", "json", "--allowedTools", *TOOLS,
           "--permission-mode", "acceptEdits", "--setting-sources", "project", "--strict-mcp-config",
           "--max-budget-usd", f"{cap:.2f}"]
    if effort:
        cmd += ["--effort", effort]
    if cfg["plugin_dir"]:
        cmd += ["--plugin-dir", cfg["plugin_dir"]]
    start = time.time()
    try:
        r = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=TIMEOUT)
        out = json.loads(r.stdout)
    except subprocess.TimeoutExpired:
        out = {"result": "", "is_error": True, "detail": f"timed out after {TIMEOUT} seconds"}
    except ValueError:
        out = {"result": "", "is_error": True, "detail": "no JSON from claude: " + (r.stdout + r.stderr)[-200:]}
    answer = out.get("result") or ""
    if re.match(r"\s*(Not logged in|Invalid API key|Please run /login)", answer):
        shutil.rmtree(os.path.dirname(work), ignore_errors=True)
        shutil.rmtree(home, ignore_errors=True)
        stale = transcript_for(out.get("session_id", "")) if out.get("session_id") else None
        if stale and "turnwise-bench-" in os.path.basename(os.path.dirname(stale)):
            shutil.rmtree(os.path.dirname(stale), ignore_errors=True)
        sys.exit("claude is not logged in. Run it once interactively and use /login, or set ANTHROPIC_API_KEY, then retry.")
    try:
        passed, detail = task["check"](work, os.path.join(CACHE, task["repo"]), PYTHON, answer)
    except Exception as e:
        passed, detail = False, f"check crashed: {e}"
    if out.get("detail"):
        passed, detail = False, out["detail"]
    elif out.get("subtype") not in (None, "success"):
        detail = f"[{out['subtype']}] {detail}"
    u = out.get("usage") or {}
    row = {"arm": arm, "task": task["id"], "kind": task["kind"], "run": run, "passed": int(passed),
           "cost_usd": round(out.get("total_cost_usd") or 0, 4), "turns": out.get("num_turns", ""),
           "duration_s": round(time.time() - start, 1), "uncached_input": u.get("input_tokens", ""),
           "cache_write": u.get("cache_creation_input_tokens", ""), "cache_read": u.get("cache_read_input_tokens", ""),
           "output": u.get("output_tokens", ""), "model": model, "claude_version": version,
           "session_id": out.get("session_id", ""), "detail": detail[:160]}
    raw = os.path.join(results, "raw", arm)
    stem = os.path.join(raw, f"{task['id']}-run{run}")
    src = transcript_for(row["session_id"]) if row["session_id"] else None
    if not src:
        row["detail"] = (detail + " (no transcript found)")[:160]

    def save_result():
        os.makedirs(raw, exist_ok=True)
        with open(stem + ".result.json", "w") as f:
            json.dump({"row": row, "claude": out}, f, indent=1)
    retry(save_result, "save the result file")
    if src:
        retry(lambda: shutil.copy2(src, stem + ".jsonl"), "copy the transcript")
        for i, sub in enumerate(sorted(glob.glob(os.path.join(src[:-6], "**", "*.jsonl"), recursive=True))):
            retry(lambda sub=sub, i=i: shutil.copy2(sub, f"{stem}.sub{i}.jsonl"), "copy a subagent transcript")
        if "turnwise-bench-" in os.path.basename(os.path.dirname(src)):   # only ever our own throwaway project
            shutil.rmtree(os.path.dirname(src), ignore_errors=True)
    if keep:
        print(f"    kept: {work}")
    else:
        shutil.rmtree(os.path.dirname(work), ignore_errors=True)
    shutil.rmtree(home, ignore_errors=True)
    return row


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true", help="check the tasks themselves; no model, no cost")
    ap.add_argument("--arm", nargs="+", metavar="ARM",
                    help="one or more of: " + ", ".join(sorted(ARMS)) + ", or a name defined with --plugin. "
                         "With several arms, each task is run once per arm in turn (interleaved), and the order "
                         "of the arms rotates, so drift over time falls on every arm equally.")
    ap.add_argument("--plugin", action="append", default=[], metavar="NAME=PATH",
                    help="define an extra arm NAME that loads the Claude Code plugin at PATH (repeatable)")
    ap.add_argument("--env", action="append", default=[], metavar="ARM:KEY=VALUE",
                    help="set an environment variable for one arm's runs only (repeatable). Some tools stay "
                         "inactive in headless runs unless told otherwise, for example caveman:CAVEMAN_DEFAULT_MODE=caveman")
    ap.add_argument("--results", default=RESULTS, help="folder for summary.csv and raw transcripts")
    ap.add_argument("--tasks", nargs="*", help="task ids to run (default: every task in the chosen set)")
    ap.add_argument("--set", choices=["short", "long", "all"], default="short",
                    help="short: the five pilot tasks (default). long: three multi-part tasks. all: both")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--effort", default="", help="pin the effort level (default: Claude Code's own default)")
    ap.add_argument("--budget", type=float, default=20.0, help="stop starting new runs once this many dollars are spent")
    ap.add_argument("--per-task-cap", type=float, default=5.0)
    ap.add_argument("--claude", help="path to the claude CLI")
    ap.add_argument("--keep", action="store_true", help="keep each throwaway repo copy for inspection")
    a = ap.parse_args()
    if a.runs < 1 or a.budget <= 0 or a.per_task_cap <= 0:
        ap.error("--runs, --budget and --per-task-cap must be positive")
    in_set = lambda t: a.set == "all" or t.get("set", "short") == a.set
    tasks = [t for t in TASKS if (t["id"] in a.tasks if a.tasks else in_set(t))]
    if a.tasks and len(tasks) != len(set(a.tasks)):
        sys.exit("unknown task id. Known: " + ", ".join(t["id"] for t in TASKS))
    setup()
    if a.selftest:
        sys.exit(0 if selftest(tasks) else 1)
    if not a.arm:
        ap.error("choose --selftest or --arm")
    for spec in a.plugin:
        name, _, path = spec.partition("=")
        path = os.path.abspath(os.path.expanduser(path))
        if not name or name in ARMS or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            ap.error(f"--plugin {spec}: the name must be new and use only letters, digits, dot, dash, underscore")
        if not os.path.exists(os.path.join(path, ".claude-plugin", "plugin.json")):
            ap.error(f"--plugin {spec}: no Claude Code plugin found at {path} (.claude-plugin/plugin.json is missing)")
        ARMS[name] = {"plugin_dir": path, "trim": False}
    for spec in a.env:
        arm, _, pair = spec.partition(":")
        key, eq, value = pair.partition("=")
        if arm not in ARMS or not eq or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            ap.error(f"--env {spec}: use ARM:KEY=VALUE with a known arm")
        ARMS[arm] = {**ARMS[arm], "env": {**ARMS[arm].get("env", {}), key: value}}
    arms = list(dict.fromkeys(a.arm))
    unknown = [x for x in arms if x not in ARMS]
    if unknown:
        ap.error("unknown arm: " + ", ".join(unknown) + ". Known: " + ", ".join(sorted(ARMS)))
    results = os.path.abspath(a.results)
    claude = find_claude(a.claude)
    try:
        version = sh(claude, "--version").stdout.split()[0]
    except (OSError, subprocess.CalledProcessError, IndexError):
        sys.exit(f"could not run the claude CLI at {claude}; pass --claude PATH")
    for arm in arms:
        if ARMS[arm].get("env"):
            print(f"  {arm} runs with " + ", ".join(f"{k}={v}" for k, v in ARMS[arm]["env"].items()))
    print(f"arm{'s (interleaved)' if len(arms) > 1 else ''} {', '.join(arms)} · model {a.model} · claude {version} · "
          f"{len(tasks)} tasks x {a.runs} run(s) · budget ${a.budget:.2f}")
    os.makedirs(results, exist_ok=True)
    summary = os.path.join(results, "summary.csv")
    new = not os.path.exists(summary)
    done = {}                                   # (arm, task) -> highest run number already recorded
    if not new:
        with open(summary, newline="") as old:
            reader = csv.DictReader(old)
            if reader.fieldnames != FIELDS:
                sys.exit(f"{summary} has different columns from this version. Move it aside and run again.")
    recovered = recover_rows(summary, results)
    if recovered:
        print(f"  recovered {recovered} finished run(s) whose row was missing from {os.path.basename(summary)}")
    if os.path.exists(summary):
        with open(summary, newline="") as old:
            for r in csv.DictReader(old):
                key = (r["arm"], r["task"])
                done[key] = max(done.get(key, 0), int(r["run"] or 0))
    spent, rows, unwritten = 0.0, [], []
    stopped = False
    try:
        for run in range(1, a.runs + 1):
            if stopped:
                break
            for ti, t in enumerate(tasks):
                if stopped:
                    break
                shift = (run + ti) % len(arms)                      # rotate which arm goes first
                for arm in arms[shift:] + arms[:shift]:
                    if a.budget - spent < 0.25:
                        print(f"budget reached (${spent:.2f} of ${a.budget:.2f}); stopping before {arm} {t['id']}")
                        stopped = True
                        break
                    number = done.get((arm, t["id"]), 0) + run      # continue after earlier invocations; never overwrite
                    row = run_task(claude, version, arm, t, number, a.model, a.effort,
                                   min(a.per_task_cap, a.budget - spent), a.keep, results)
                    spent += row["cost_usd"]
                    rows.append(row)
                    if not append_row(summary, row):
                        unwritten.append(row)                       # still saved in its own result file
                    print(f"  {'PASS' if row['passed'] else 'FAIL'} {arm:<14} {t['id']:<34} ${row['cost_usd']:.2f}  "
                          f"{row['turns']} turns  {row['duration_s']}s  {row['detail'][:44]}")
    finally:
        still = [r for r in unwritten if not append_row(summary, r)]
        if still:
            print(f"\n{len(still)} row(s) could not be written to {os.path.basename(summary)}. They are safe in the raw result "
                  f"files; the next run of this command recovers them.")
    for arm in arms:
        mine = [r for r in rows if r["arm"] == arm]
        solved, cost = sum(r["passed"] for r in mine), sum(r["cost_usd"] for r in mine)
        print(f"{'' if arm != arms[0] else chr(10)}{arm}: {solved}/{len(mine)} solved · ${cost:.2f} spent"
              + (f" · ${cost / solved:.2f} per solved task" if solved else ""))
    print(f"rows appended to {os.path.relpath(summary)}\n")
    if len(arms) > 1:
        print("compare the arms with:  python3 bench/harness/analyze.py --summary " + os.path.relpath(summary)
              + " --a " + arms[0] + " --b " + arms[1])
        return
    raw = os.path.join(results, "raw", arms[0])
    if glob.glob(os.path.join(raw, "*.jsonl")):
        subprocess.run([sys.executable, os.path.join(PLUGIN, "scripts", "cost_anatomy.py"), "--root", raw,
                        "--json", os.path.join(results, f"cost_anatomy_{arms[0]}.json")])


if __name__ == "__main__":
    main()
