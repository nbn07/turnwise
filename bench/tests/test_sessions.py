#!/usr/bin/env python3
"""Tests for the session test runner. Stdlib only. Run:  python3 bench/tests/test_sessions.py

Driven end to end with the stand-in CLI and no waiting, so nothing is spent.
"""
import csv, glob, json, os, shutil, subprocess, sys, tempfile, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.dirname(HERE)
RUN = os.path.join(BENCH, "harness", "sessions.py")
FAKE = os.path.join(HERE, "fake_claude.py")


def temp_copies():
    return set(glob.glob(os.path.join(tempfile.gettempdir(), "turnwise-bench-*")))


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sessions-test-")
        self.results = os.path.join(self.tmp, "results")
        self.projects = os.path.join(self.tmp, "projects")
        self.log = os.path.join(self.tmp, "calls.jsonl")
        os.makedirs(self.projects)
        self.before = temp_copies()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_it(self, *args, mode="solve", cost="0.5", env=None, fake=True, wait="0"):
        e = {**os.environ, "BENCH_PROJECTS": self.projects, "FAKE_LOG": self.log, "FAKE_MODE": mode, "FAKE_COST": cost, **(env or {})}
        cmd = [sys.executable, RUN, *args, "--results", self.results] + (["--wait", wait] if "--selftest" not in args else [])
        return subprocess.run(cmd + (["--claude", FAKE] if fake else []), capture_output=True, text=True, env=e, timeout=600)

    def rows(self):
        p = os.path.join(self.results, "summary.csv")
        if not os.path.exists(p):
            return []
        with open(p, newline="") as f:
            return list(csv.DictReader(f))

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            return [json.loads(l) for l in f]

    def assert_clean(self):
        self.assertEqual(temp_copies(), self.before, "repo copies or kept snapshots were left behind")
        self.assertEqual(os.listdir(self.projects), [], "session folders were left behind")


class SelfTest(Case):
    def test_follow_up_and_small_jobs_can_fail_and_pass(self):
        r = self.run_it("--selftest", fake=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.count("ok  "), 4)
        self.assert_clean()


class FullRun(Case):
    def setUp(self):
        super().setUp()
        self.r = self.run_it()
        self.measured = [x for x in self.rows() if x["scenario"] != "build"]

    def test_every_planned_run_happens_once_and_passes(self):
        self.assertEqual(self.r.returncode, 0, self.r.stdout + self.r.stderr)
        got = sorted((x["session"], x["scenario"], x["way"], x["trial"]) for x in self.measured)
        want = sorted((s, sc, w, str(t)) for s in ("click", "more-itertools") for t in (1, 2)
                      for sc, ws in (("stale", ("resume", "fresh")), ("model-switch", ("switch", "stay"))) for w in ws)
        self.assertEqual(got, want)
        self.assertTrue(all(x["passed"] == "1" for x in self.measured), [(x["way"], x["detail"]) for x in self.measured])
        self.assertEqual(len([x for x in self.rows() if x["scenario"] == "build"]), 2)
        self.assertIn("spent $9.00 · 16 measured runs", self.r.stdout)      # 2 builds + 16 runs at $0.50
        self.assert_clean()

    def test_each_way_is_called_the_way_it_claims(self):
        calls = [c for c in self.calls() if c["job"] != "build"]
        for c, row in zip(calls, self.measured):
            way, a = row["way"], c["argv"]
            self.assertEqual(c["job"], "followup" if row["scenario"] == "stale" else "small")
            self.assertEqual(c["fresh"], way == "fresh")
            self.assertEqual(c["resume"] is None, way == "fresh")
            self.assertEqual(c["model"], "claude-sonnet-5-5" if way == "switch" else "claude-opus-5-5")
            self.assertEqual(row["model"], c["model"])
            self.assertEqual(c["handoff_exists"], way == "fresh")               # the note exists only for the fresh way
            self.assertNotIn("--plugin-dir", a)
            i = a.index("--allowedTools")
            self.assertEqual(a[i + 1:i + 7], ["Read", "Edit", "Write", "Grep", "Glob", "Bash"])
            self.assertNotIn("Task", a)
            if way != "fresh":
                self.assertTrue(c["resume_found"])

    def test_everything_is_put_back_before_each_run(self):
        calls = [c for c in self.calls() if c["job"] != "build"]
        self.assertEqual(len(calls), 16)
        for c in calls:
            self.assertTrue(c["bug_present"], c)           # an earlier run's fix is gone
            self.assertFalse(c["funcs_exists"], c)         # so is an earlier run's file
            self.assertTrue(c["notes_exists"], c)          # what the build made is still there
        lines = {(c["session"]): set() for c in calls}
        for c in calls:
            if c["resume"]:
                lines[c["session"]].add(c["transcript_lines"])
        self.assertTrue(all(len(v) == 1 for v in lines.values()), lines)       # the transcript never grows between runs

    def test_schedule_keeps_caches_in_the_intended_state(self):
        order = [(x["session"], x["scenario"], x["way"], x["trial"]) for x in self.rows()]
        for s in ("click", "more-itertools"):
            mine = [o for o in order if o[0] == s]
            self.assertEqual(mine[0][1], "build")
            self.assertEqual({o[1] for o in mine[1:3]}, {"model-switch"})       # trial 1 right after the build (warm)
            i = mine.index((s, "stale", "resume", "1"))
            self.assertEqual({o[1:] for o in mine[i + 1:i + 3]}, {("model-switch", "switch", "2"), ("model-switch", "stay", "2")})
        firsts = {s: next(o[2] for o in order if o[0] == s and o[1] == "stale") for s in ("click", "more-itertools")}
        self.assertEqual(set(firsts.values()), {"resume", "fresh"})             # which way goes first is balanced

    def test_first_request_cache_state_is_recorded(self):
        for x in self.measured:
            self.assertNotEqual(x["first_cache_write"], "", x)
            if x["way"] == "stay":
                self.assertEqual((x["first_cache_read"], x["first_cache_write"]), ("120000", "500"))
            if x["way"] == "switch":
                self.assertEqual((x["first_cache_read"], x["first_cache_write"]), ("0", "120000"))
            if x["way"] == "fresh":
                self.assertEqual((x["first_cache_write"], x["context_before"]), ("19000", "0"))
        self.assertEqual(len(glob.glob(os.path.join(self.results, "raw", "*.jsonl"))), 18)


class Guards(Case):
    def test_small_context_sessions_are_skipped_before_spending_more(self):
        r = self.run_it(env={"FAKE_CONTEXT": "5000"})
        self.assertEqual([x["scenario"] for x in self.rows()], ["build", "build"])
        self.assertEqual(r.stdout.count("too small to be a useful test"), 2)
        self.assert_clean()

    def test_budget_stops_the_run(self):
        r = self.run_it("--budget", "10", cost="3")
        self.assertEqual(len(self.rows()), 3)                                   # build $3, two runs $6: $1 left, not enough
        self.assertIn("not enough left", r.stdout)
        self.assertIn("spent $9.00", r.stdout)
        self.assert_clean()

    def test_failed_work_is_recorded_as_failed(self):
        self.run_it("--sessions", "click", "--trials", "1", mode="nothing")
        measured = [x for x in self.rows() if x["scenario"] != "build"]
        self.assertEqual(len(measured), 4)
        self.assertEqual({x["passed"] for x in measured}, {"0"})

    def test_not_logged_in_stops_cleanly(self):
        r = self.run_it(mode="notlogged")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not logged in", r.stderr)
        self.assertEqual(self.rows(), [])
        self.assert_clean()

    def test_waits_happen_before_stale_runs_only(self):
        start = time.time()
        r = self.run_it("--sessions", "click", "--trials", "1", wait="1")
        self.assertEqual(r.stdout.count("waiting 1s"), 2)                       # one per stale run, none for model-switch
        self.assertGreaterEqual(time.time() - start, 2)

    def test_one_scenario_can_be_run_alone(self):
        self.run_it("--scenarios", "stale", "--trials", "1")
        measured = [x for x in self.rows() if x["scenario"] != "build"]
        self.assertEqual(sorted((x["session"], x["way"]) for x in measured),
                         [("click", "fresh"), ("click", "resume"), ("more-itertools", "fresh"), ("more-itertools", "resume")])
        self.assert_clean()

    def test_resumed_runs_report_their_own_cost_and_get_a_cap_that_allows_for_the_build(self):
        r = self.run_it("--sessions", "click", "--trials", "1", cost="0.5")
        rows = {x["way"]: x for x in self.rows() if x["scenario"] != "build"}
        # The stand-in, like the real CLI, reports a resumed session's whole cost so far ($1.00): the build's $0.50 is taken off.
        self.assertEqual({w: x["cost_usd"] for w, x in rows.items()}, {"stay": "0.5", "switch": "0.5", "resume": "0.5", "fresh": "0.5"})
        self.assertIn("spent $2.50", r.stdout)
        caps = {("fresh" if c["fresh"] else c["model"][7:13] + ("-stale" if c["job"] == "followup" else "")): float(c["argv"][c["argv"].index("--max-budget-usd") + 1])
                for c in self.calls() if c["job"] != "build"}
        self.assertAlmostEqual(caps["fresh"], 0.40 + 1.0)                         # a new session: no build cost to allow for
        self.assertAlmostEqual(caps["opus-5-stale"], 0.5 + (120203 * 5 / 1e6 + 0.20) + 1.0, places=2)
        self.assertIn("the remaining 2 runs should cost about $1.20", r.stdout)

    def test_bad_arguments_are_refused(self):
        for args in [["--trials", "0"], ["--budget", "0"], ["--sessions", "nope"]]:
            self.assertNotEqual(self.run_it(*args).returncode, 0, args)
        self.assertNotEqual(self.run_it("--wait", "-1", wait="-1").returncode, 0)
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
