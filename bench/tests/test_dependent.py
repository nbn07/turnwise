#!/usr/bin/env python3
"""Tests for the dependent follow-up test. Stdlib only. Run:  python3 bench/tests/test_dependent.py"""
import csv, glob, json, os, shutil, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.dirname(HERE)
RUN = os.path.join(BENCH, "harness", "dependent.py")
FAKE = os.path.join(HERE, "fake_claude.py")


def temp_copies():
    return set(glob.glob(os.path.join(tempfile.gettempdir(), "turnwise-bench-*")))


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dependent-test-")
        self.results = os.path.join(self.tmp, "results")
        self.projects = os.path.join(self.tmp, "projects")
        self.log = os.path.join(self.tmp, "calls.jsonl")
        os.makedirs(self.projects)
        self.before = temp_copies()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_it(self, *args, mode="solve", cost="0.1", env=None):
        e = {**os.environ, "BENCH_PROJECTS": self.projects, "FAKE_LOG": self.log, "FAKE_MODE": mode, "FAKE_COST": cost, **(env or {})}
        return subprocess.run([sys.executable, RUN, *args, "--results", self.results, "--claude", FAKE],
                              capture_output=True, text=True, env=e, timeout=600)

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
        self.assertEqual(temp_copies(), self.before, "throwaway folders were left behind")
        self.assertEqual(os.listdir(self.projects), [], "session folders were left behind")


class Dependent(Case):
    def test_three_ways_are_run_and_told_apart(self):
        r = self.run_it("--trials", "2")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rows = self.rows()
        self.assertEqual(sorted((x["trial"], x["way"]) for x in rows),
                         sorted((str(t), w) for t in (1, 2) for w in ("build", "resume", "fresh-bare", "fresh-script", "fresh-agent")))
        by = {(x["trial"], x["way"]): x for x in rows}
        for t in ("1", "2"):
            self.assertEqual(by[(t, "build")]["pick"], "zorbaquine")
            self.assertEqual((by[(t, "build")]["note_written"], by[(t, "build")]["note_has_pick"]), ("1", "1"))
            self.assertEqual(by[(t, "resume")]["passed"], "1")               # it has the conversation
            self.assertEqual(by[(t, "fresh-agent")]["passed"], "1")          # the agent's note names the pick
            self.assertEqual(by[(t, "fresh-script")]["passed"], "1")         # the note points at the old transcript
            self.assertEqual(by[(t, "fresh-bare")]["passed"], "0")           # the note alone cannot know the choice
            self.assertIn("no function named zorbaquine; found instead: zorbguessed", by[(t, "fresh-bare")]["detail"])
        self.assertIn("agent wrote the handoff note when reminded: 2/2", r.stdout)
        self.assertIn("fresh-bare    0/2 passed", r.stdout)
        self.assertIn("fresh-script  2/2 passed", r.stdout)
        self.assert_clean()

    def test_each_call_gets_the_right_setup(self):
        self.run_it("--trials", "1")
        calls = self.calls()
        p1, p2 = calls[0], calls[1]
        self.assertEqual((p1["prompt"], p2["prompt"]), ("P1", "P2"))
        for c in (p1, p2):                                                   # the build runs with the plugin and warm_note on
            self.assertTrue(c["plugin"])
            self.assertTrue(c["config"]["warm_note"])
            self.assertEqual(c["config"]["threshold_tokens"], 5000)
            self.assertFalse(c["config"]["guard"])
        self.assertIsNone(p1["resume"])
        self.assertIsNotNone(p2["resume"])
        def which(c):
            if not c["fresh"]:
                return "resume"
            if "written by the agent" in c["note_at_start"]:
                return "fresh-agent"
            return "fresh-script" if c["old_transcript_on_disk"] else "fresh-bare"
        follow = {which(c): c for c in calls[2:]}
        self.assertEqual(set(follow), {"resume", "fresh-bare", "fresh-script", "fresh-agent"})
        self.assertTrue(follow["fresh-agent"]["old_transcript_on_disk"])
        self.assertNotIn("zorbaquine", follow["fresh-bare"]["note_at_start"])
        for way, c in follow.items():
            self.assertFalse(c["plugin"], way)                               # follow-ups run with no plugin
            self.assertFalse(c["helper_at_start"], way)                      # an earlier way's work is gone
            self.assertTrue(c["notes_md"], way)                              # the build's work is still there
            self.assertNotIn("Task", c["argv"])
        self.assertIsNotNone(follow["resume"]["resume"])
        self.assertIn("Built from the previous session's transcript by a script", follow["fresh-script"]["note_at_start"])
        self.assertNotIn("zorbaquine", follow["fresh-script"]["note_at_start"])   # the pick is in neither request nor last answer
        self.assertIn("Decided helper name: zorbaquine", follow["fresh-agent"]["note_at_start"])
        self.assertIn("Since that note", follow["fresh-agent"]["note_at_start"])

    def test_costs_are_per_run_not_cumulative(self):
        r = self.run_it("--trials", "1", cost="0.1")
        by = {x["way"]: float(x["cost_usd"]) for x in self.rows()}
        self.assertAlmostEqual(by["build"], 0.2)                             # two prompts
        self.assertAlmostEqual(by["resume"], 0.1)                            # the build's share is taken off
        self.assertAlmostEqual(by["fresh-script"], 0.1)
        self.assertAlmostEqual(by["fresh-bare"], 0.1)
        self.assertIn("spent $0.60", r.stdout)

    def test_no_agent_note_means_that_way_is_skipped(self):
        r = self.run_it("--trials", "1", env={"FAKE_WRITES_NOTE": "0"})
        self.assertEqual(sorted(x["way"] for x in self.rows()), ["build", "fresh-bare", "fresh-script", "resume"])
        self.assertEqual(self.rows()[0]["note_written"], "0")
        self.assertIn("agent wrote the handoff note when reminded: 0/1", r.stdout)
        self.assert_clean()

    def test_agent_note_that_omits_the_decision_is_reported_and_the_transcript_covers_it(self):
        self.run_it("--trials", "1", env={"FAKE_NOTE_OMITS_PICK": "1"})
        by = {x["way"]: x for x in self.rows()}
        self.assertEqual((by["build"]["note_written"], by["build"]["note_has_pick"]), ("1", "0"))
        self.assertEqual(by["fresh-agent"]["passed"], "1")                   # found in the transcript the note points at

    def test_trial_without_a_pick_is_invalid_and_spends_no_more(self):
        self.run_it("--trials", "1", env={"FAKE_PICK": ""})
        rows = self.rows()
        self.assertEqual([(x["way"], x["passed"]) for x in rows], [("build", "0")])
        self.assertIn("NOT FOUND", rows[0]["detail"])
        self.assert_clean()

    def test_work_not_done_fails_every_way(self):
        self.run_it("--trials", "1", mode="nothing")
        self.assertEqual({x["passed"] for x in self.rows() if x["way"] != "build"}, {"0"})

    def test_budget_and_login_and_arguments(self):
        r = self.run_it("--budget", "1.2", cost="0.5")
        self.assertIn("not enough left", r.stdout)                           # the build costs $1.00, leaving too little
        self.assertEqual([x["way"] for x in self.rows()], ["build"])
        self.assert_clean()
        r = self.run_it(mode="notlogged")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not logged in", r.stderr)
        self.assert_clean()
        for args in (["--trials", "0"], ["--budget", "0"]):
            self.assertNotEqual(self.run_it(*args).returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=1)
