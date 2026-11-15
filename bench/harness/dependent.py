#!/usr/bin/env python3
"""Dependent follow-up test: can a fresh session finish work that depends on something the earlier session decided?

  python3 bench/harness/dependent.py --budget 3        (costs real money; a few minutes)

Each trial builds a short session in which the agent itself chooses a made-up name for a helper function, then is
given an unrelated job, so the choice is not in the last answer. The follow-up asks for the helper "using the name
you picked earlier". Nothing in the code or in the user's own words contains the name. It is then done three ways:

  resume        continue the old session (it has the whole conversation)
  fresh-bare    a new session from the script-built note, with the old transcript gone from disk:
                the note alone, which records what was asked and the last answer but not the choice
  fresh-script  the same note with the old transcript still on disk, where the note says to search it
  fresh-agent   a new session from the note the agent wrote when turnwise's warm_note option asked it to

The build runs with the turnwise plugin and warm_note on, so this is also the live check that the agent writes
the note when reminded. The follow-ups run with no plugin. Nothing waits for caches to expire: this test is about
whether the work succeeds, not about cost. Results: <results>/summary.csv and <results>/raw/.
"""
import argparse, csv, glob, json, os, re, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run as H        # noqa: E402
import sessions as S   # noqa: E402
import tasks as T      # noqa: E402

REPO = "click"
P1 = ("Do not change any files. I want a new helper in src/click/utils.py that returns True when a string, "
      "lower-cased and stripped, is one of the strings click's bool type accepts as true, and False otherwise. "
      "First find where click defines those strings. Then choose a name for the helper: a single made-up word of "
      "9 to 12 lowercase letters that is not an ordinary English word or compound, so it cannot clash with anything. "
      "Say in two sentences where the strings are defined, then end your reply with a line of exactly this form: "
      "PICK: <name>")
# The reply is pinned to one word so the choice made earlier cannot leak into the session's last answer.
# (In the first version of this test it did: the agent ended with "the <name> helper is not added yet".)
P2 = ("Unrelated housekeeping: write NOTES.md containing one line that says what src/click/utils.py is for. "
      "Reply with the single word done and nothing else.")
F = ("Now add the helper we discussed to src/click/utils.py, using the name you picked earlier. It takes one string "
     "and returns True or False as described. Do not ask me for the name.")
PREFIX = "Continue from .turnwise/handoff.md, which describes the previous session. "
NOTE = os.path.join(".turnwise", "handoff.md")
AGENT_MARK = "written by the agent"
FIELDS = ["trial", "way", "passed", "cost_usd", "requests", "duration_s", "pick", "note_written", "note_has_pick",
          "model", "claude_version", "detail"]


def find_pick(transcript):
    pick = ""
    with open(transcript, errors="replace") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            m = d.get("message") if isinstance(d, dict) else None
            if isinstance(m, dict) and d.get("type") == "assistant":
                for b in m.get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "text":
                        for found in re.findall(r"PICK:\s*`?([a-z]{6,20})`?", b.get("text", "")):
                            pick = found
    return pick


def check(work, pick):
    """The helper exists under the agreed name and behaves as described."""
    code = ("import click.utils as u, sys\n"
            f"f = getattr(u, {pick!r}, None)\n"
            "if f is None:\n"
            "    import inspect\n"
            "    names = sorted(n for n, o in vars(u).items() if inspect.isfunction(o) and o.__module__ == u.__name__)\n"
            "    print('MISSING ' + ' '.join(names)); sys.exit(3)\n"
            "ok = f(' YES ') is True and f('on') is True and f('1') is True and f('no') is False and f('maybe') is False\n"
            "print('BEHAVIOUR ok' if ok else 'BEHAVIOUR wrong'); sys.exit(0 if ok else 4)\n")
    env = {**os.environ, "PYTHONPATH": os.path.join(work, T.REPOS[REPO][3]), "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        r = subprocess.run([H.PYTHON, "-c", code], cwd=work, env=env, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return False, "the helper did not return"
    out = (r.stdout + r.stderr).strip().splitlines()
    last = out[-1] if out else "no output"
    if r.returncode == 0:
        return True, f"{pick} exists and behaves as described"
    if last.startswith("MISSING"):
        with open(os.path.join(H.CACHE, REPO, "src/click/utils.py")) as f:
            original = f.read()
        new = [n for n in last.split()[1:] if f"def {n}(" not in original]
        return False, f"no function named {pick}" + (f"; found instead: {', '.join(new[:3])}" if new else "")
    return False, last[:120]


class Runner(S.Runner):
    def __init__(self, a):
        super().__init__(a)
        self.made_projects = []       # Claude Code's session folders for our throwaway repos

    def cleanup_all(self):
        for p in self.made_projects:
            if "turnwise-bench-" in os.path.basename(p):
                shutil.rmtree(p, ignore_errors=True)
        super().cleanup_all()

    def call2(self, prompt, work, cap, resume=None, plugin_home=None):
        """Like the session test's call, optionally with the turnwise plugin and its own settings folder."""
        env = {**os.environ, "PATH": os.path.join(H.VENV, "bin") + os.pathsep + os.environ["PATH"],
               "PYTHONPATH": os.path.join(work, T.REPOS[REPO][3]), "PYTHONDONTWRITEBYTECODE": "1"}
        cmd = [self.claude, "-p", prompt, "--model", self.a.model, "--output-format", "json", "--allowedTools", *S.TOOLS,
               "--permission-mode", "acceptEdits", "--setting-sources", "project", "--strict-mcp-config",
               "--max-budget-usd", f"{cap:.2f}"]
        if resume:
            cmd += ["--resume", resume]
        if plugin_home:
            cmd += ["--plugin-dir", H.PLUGIN]
            env["TURNWISE_HOME"] = plugin_home
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

    def row(self, trial, way, passed, out, detail, b=None, requests=""):
        r = {"trial": trial, "way": way, "passed": int(passed), "cost_usd": round(out.get("total_cost_usd") or 0, 4),
             "requests": requests, "duration_s": out.get("seconds", ""), "pick": (b or {}).get("pick", ""),
             "note_written": int((b or {}).get("note_written", False)), "note_has_pick": int((b or {}).get("note_has_pick", False)),
             "model": self.a.model, "claude_version": self.version, "detail": detail[:160]}
        self.rows.append(r)
        self.save_row(r, FIELDS)
        print(f"  {'PASS' if passed else 'FAIL'} trial {trial} {way:<13} ${r['cost_usd']:.2f}  {detail[:78]}", flush=True)

    def build(self, trial):
        work = H.prepare({"repo": REPO, "mutate": None})
        self.temps.append(os.path.dirname(work))
        home = tempfile.mkdtemp(prefix="turnwise-bench-home-")
        self.temps.append(home)
        env = {**os.environ, "TURNWISE_HOME": home}
        for args in (["warm_note", "on"], ["threshold", "5000"]):      # a headless session opens near 19k tokens
            subprocess.run([sys.executable, os.path.join(H.PLUGIN, "scripts", "config.py"), *args], env=env, capture_output=True)
        o1 = self.call2(P1, work, 1.5, plugin_home=home)
        self.spent += o1.get("total_cost_usd") or 0
        sid = o1.get("session_id")
        if sid and H.transcript_for(sid):
            self.made_projects.append(os.path.dirname(H.transcript_for(sid)))
        if not sid or not H.transcript_for(sid):
            self.row(trial, "build", False, o1, o1.get("detail") or "the first prompt produced no session")
            return None
        o2 = self.call2(P2, work, 1.5 + (o1.get("total_cost_usd") or 0), resume=sid, plugin_home=home)
        build_cost = max(o2.get("total_cost_usd") or 0, o1.get("total_cost_usd") or 0)   # a resume reports the session so far
        self.spent += max(0.0, build_cost - (o1.get("total_cost_usd") or 0))
        transcript = H.transcript_for(o2.get("session_id") or "-") or H.transcript_for(sid)
        self.made_projects.append(os.path.dirname(transcript))
        sid = o2.get("session_id") or sid
        pick = find_pick(transcript)
        note_path = os.path.join(work, NOTE)
        note = open(note_path).read() if os.path.exists(note_path) else ""
        b = {"s": {"id": f"trial{trial}"}, "work": work, "sid": sid, "transcript": transcript, "pick": pick, "cost": build_cost,
             "note_written": AGENT_MARK in note.split("\n", 1)[0], "note_has_pick": bool(pick) and pick in note,
             "nreq": len(S.requests_in(transcript))}
        keep = tempfile.mkdtemp(prefix="turnwise-bench-keep-")
        self.temps.append(keep)
        shutil.copytree(work, os.path.join(keep, "repo"), symlinks=True)
        shutil.copy2(transcript, os.path.join(keep, "base.jsonl"))
        b["keep"] = keep
        raw = os.path.join(self.results, "raw")
        os.makedirs(raw, exist_ok=True)
        shutil.copy2(transcript, os.path.join(raw, f"trial{trial}-build.jsonl"))
        if note:
            shutil.copy2(note_path, os.path.join(raw, f"trial{trial}-agent-note.md"))
        detail = (f"pick {pick or 'NOT FOUND'}; agent note " +
                  ("written" + (" and names the pick" if b["note_has_pick"] else " but does not name the pick") if b["note_written"] else "not written"))
        o2["total_cost_usd"] = build_cost
        self.row(trial, "build", bool(pick), o2, detail, b, b["nreq"])
        return b if pick else None

    def follow_up(self, b, trial, way):
        if not self.room(0.6):
            return False
        self.reset(b)
        note_path = os.path.join(b["work"], NOTE)
        prompt, resume = F, b["sid"]
        if way != "resume":
            if way in ("fresh-script", "fresh-bare") and os.path.exists(note_path):
                os.remove(note_path)                      # what a user without the warm_note option would have
            made = subprocess.run([sys.executable, os.path.join(H.PLUGIN, "scripts", "handoff.py"), b["transcript"], b["work"]],
                                  capture_output=True, text=True)
            if made.returncode != 0:
                self.row(trial, way, False, {}, "could not build the handoff note: " + made.stderr.strip()[:80], b)
                return True
            shutil.copy2(note_path, os.path.join(self.results, "raw", f"trial{trial}-{way}-note.md"))
            prompt, resume = PREFIX + F, None
            if way == "fresh-bare":                       # as if the old session's history had been deleted
                for p in glob.glob(os.path.join(os.path.dirname(b["transcript"]), "*")):
                    shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
        out = self.call2(prompt, b["work"], (b["cost"] if resume else 0) + 1.5, resume=resume)
        if resume and out.get("total_cost_usd") is not None:
            out["total_cost_usd"] = max(0.0, out["total_cost_usd"] - b["cost"])
        self.spent += out.get("total_cost_usd") or 0
        try:
            passed, detail = check(b["work"], b["pick"])
        except Exception as e:
            passed, detail = False, f"check crashed: {e}"
        if out.get("detail"):
            passed, detail = False, out["detail"]
        src = H.transcript_for(out.get("session_id") or "-") or (b["transcript"] if resume else None)
        usage = S.requests_in(src) if src else []
        if resume:
            usage = usage[b["nreq"]:]
        if src:
            shutil.copy2(src, os.path.join(self.results, "raw", f"trial{trial}-{way}.jsonl"))
            other = os.path.dirname(src)
            if other != os.path.dirname(b["transcript"]) and "turnwise-bench-" in os.path.basename(other):
                shutil.rmtree(other, ignore_errors=True)
        self.row(trial, way, passed, out, detail, b, len(usage))
        return True

    def go(self):
        a = self.a
        print(f"dependent follow-up test · model {a.model} · claude {self.version} · {a.trials} trial(s) · budget ${a.budget:.2f}")
        self.built = []
        try:
            for trial in range(1, a.trials + 1):
                if not self.room(1.0):
                    break
                b = self.build(trial)
                if not b:
                    continue
                self.built.append(b)
                ways = ["resume", "fresh-bare", "fresh-script"] + (["fresh-agent"] if b["note_written"] else [])
                for way in ways[trial % len(ways):] + ways[:trial % len(ways)]:
                    if not self.follow_up(b, trial, way):
                        return
                self.drop(b)
        finally:
            self.cleanup_all()
            self.report()

    def report(self):
        builds = [r for r in self.rows if r["way"] == "build"]
        print(f"\nspent ${self.spent:.2f} · results in {os.path.relpath(self.results)}")
        if builds:
            print(f"  agent wrote the handoff note when reminded: {sum(r['note_written'] for r in builds)}/{len(builds)} builds; "
                  f"note named the pick: {sum(r['note_has_pick'] for r in builds)}/{len(builds)}")
        for way in ("resume", "fresh-bare", "fresh-script", "fresh-agent"):
            mine = [r for r in self.rows if r["way"] == way]
            if mine:
                print(f"  {way:<13} {sum(r['passed'] for r in mine)}/{len(mine)} passed, mean ${sum(r['cost_usd'] for r in mine) / len(mine):.3f}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--budget", type=float, default=3.0)
    ap.add_argument("--results", default=os.path.join(H.RESULTS, "dependent-v2"))
    ap.add_argument("--claude")
    a = ap.parse_args()
    if a.trials < 1 or a.budget <= 0:
        ap.error("--trials and --budget must be positive")
    a.cheap_model, a.wait, a.sessions, a.scenarios = "", 0, None, []
    H.setup()
    Runner(a).go()


if __name__ == "__main__":
    main()
