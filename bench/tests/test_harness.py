#!/usr/bin/env python3
"""Tests for the benchmark harness. Stdlib only. Run:  python3 bench/tests/test_harness.py

The harness is driven end to end with fake_claude.py standing in for the real CLI, so nothing is spent.
Results and Claude's session folder are redirected to a temp folder; real results are never touched.
"""
import csv, glob, json, os, shutil, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.dirname(HERE)
RUN = os.path.join(BENCH, "harness", "run.py")
FAKE = os.path.join(HERE, "fake_claude.py")
PLUGIN = os.path.join(os.path.dirname(BENCH), "turnwise")
ALL = ["bugfix-small-tomli", "bugfix-largefile-more-itertools", "feature-humanize-metric-v2",
       "question-click-option-sources", "refactor-itsdangerous-rename"]
QUICK = "question-click-option-sources"


def temp_copies():
    return set(glob.glob(os.path.join(tempfile.gettempdir(), "turnwise-bench-*")))


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="harness-test-")
        self.results = os.path.join(self.tmp, "results")
        self.projects = os.path.join(self.tmp, "projects")
        self.log = os.path.join(self.tmp, "calls.jsonl")
        os.makedirs(self.projects)
        self.before = temp_copies()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_harness(self, *args, mode="solve", cost="0.5", extra_env=None, fake=True):
        env = {**os.environ, "BENCH_RESULTS": self.results, "BENCH_PROJECTS": self.projects, "FAKE_LOG": self.log,
               "FAKE_MODE": mode, "FAKE_COST": cost, **(extra_env or {})}
        cmd = [sys.executable, RUN, *args] + (["--claude", FAKE] if fake else [])
        return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=600)

    def rows(self):
        path = os.path.join(self.results, "summary.csv")
        if not os.path.exists(path):
            return []
        with open(path, newline="") as f:
            return list(csv.DictReader(f))

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            return [json.loads(l) for l in f]

    def raw(self, arm, pattern):
        return sorted(os.path.basename(p) for p in glob.glob(os.path.join(self.results, "raw", arm, pattern)))

    def assert_clean(self):
        self.assertEqual(temp_copies(), self.before, "throwaway repo copies were left behind")
        self.assertEqual(os.listdir(self.projects), [], "session folders were left in Claude's projects folder")


class SelfTest(Case):
    def test_every_check_fails_unsolved_and_passes_solved(self):
        r = self.run_harness("--selftest", fake=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.count("\nok  ") + r.stdout.startswith("ok  "), 5)
        self.assertNotIn("FAIL", r.stdout)
        self.assert_clean()


class FullRun(Case):
    def test_all_tasks_solved_are_recorded_correctly(self):
        r = self.run_harness("--arm", "baseline")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rows = self.rows()
        self.assertEqual([x["task"] for x in rows], ALL)
        self.assertTrue(all(x["passed"] == "1" for x in rows), [(x["task"], x["detail"]) for x in rows])
        self.assertTrue(all(x["cost_usd"] == "0.5" and x["turns"] == "3" and x["cache_write"] == "30000" for x in rows))
        self.assertTrue(all(x["model"] == "claude-opus-5-5" and x["claude_version"] == "9.9.9" and x["arm"] == "baseline" for x in rows))
        self.assertIn("5/5 solved · $2.50 spent · $0.50 per solved task", r.stdout)
        self.assertEqual(len(self.raw("baseline", "*-run1.jsonl")), 5)
        self.assertEqual(len(self.raw("baseline", "*-run1.sub0.jsonl")), 5)       # subagent transcripts kept
        self.assertEqual(len(self.raw("baseline", "*.result.json")), 5)
        with open(os.path.join(self.results, "cost_anatomy_baseline.json")) as f:
            self.assertEqual(sum(s["requests"] for s in json.load(f)), 10)        # 5 main + 5 subagent requests
        self.assert_clean()

    def test_the_agent_gets_the_right_command_line_and_environment(self):
        self.run_harness("--arm", "baseline", "--tasks", QUICK)
        c = self.calls()[0]
        a = c["argv"]
        self.assertEqual(a[0], "-p")
        for flag, value in [("--model", "claude-opus-5-5"), ("--output-format", "json"), ("--permission-mode", "acceptEdits"),
                            ("--setting-sources", "project"), ("--max-budget-usd", "5.00")]:
            self.assertEqual(a[a.index(flag) + 1], value, flag)
        self.assertIn("--strict-mcp-config", a)
        i = a.index("--allowedTools")
        self.assertEqual(a[i + 1:i + 8], ["Read", "Edit", "Write", "Grep", "Glob", "Bash", "Task"])
        self.assertNotIn("--plugin-dir", a)
        self.assertNotIn("--effort", a)
        self.assertEqual(c["path0"], os.path.join(BENCH, ".venv", "bin"))
        self.assertEqual(os.path.realpath(c["pythonpath"]), os.path.realpath(os.path.join(c["cwd"], "src")))
        self.assertIn("turnwise-bench-", c["cwd"])
        self.assertFalse(os.path.exists(c["cwd"]))                                # the copy is gone afterwards

    def test_the_agent_copy_has_one_commit_and_the_starting_change(self):
        self.run_harness("--arm", "baseline", "--tasks", "bugfix-small-tomli", "--keep", mode="nothing")
        work = self.calls()[0]["cwd"]
        try:
            log = subprocess.run(["git", "log", "--oneline"], cwd=work, capture_output=True, text=True).stdout.strip().splitlines()
            self.assertEqual(len(log), 1)
            with open(os.path.join(work, "src/tomli/_parser.py")) as f:
                self.assertIn('if escape_id == "\\\\U":\n        return parse_hex_char(src, pos, 4)', f.read())
        finally:
            shutil.rmtree(os.path.dirname(work), ignore_errors=True)

    @staticmethod
    def snapshot_user_settings():
        d = os.path.expanduser("~/.claude/turnwise")
        if not os.path.isdir(d):
            return None
        return sorted((f, os.path.getmtime(os.path.join(d, f)), os.path.getsize(os.path.join(d, f))) for f in os.listdir(d))

    def test_arms_differ_only_in_plugin_and_trim(self):
        before = self.snapshot_user_settings()
        for arm in ("baseline", "turnwise", "turnwise-trim"):
            self.run_harness("--arm", arm, "--tasks", QUICK)
        base, tw, trim = self.calls()
        self.assertNotIn("--plugin-dir", base["argv"])
        for c in (tw, trim):
            self.assertEqual(c["argv"][c["argv"].index("--plugin-dir") + 1], PLUGIN)
        self.assertIsNone(base["turnwise_config"])
        self.assertIsNone(tw["turnwise_config"])
        self.assertTrue(trim["turnwise_config"]["trim"])
        self.assertFalse(trim["turnwise_config"]["guard"])
        strip = lambda a: [x for x in a if x not in ("--plugin-dir", PLUGIN)]
        self.assertEqual(strip(base["argv"]), strip(tw["argv"]))
        self.assertEqual([x["arm"] for x in self.rows()], ["baseline", "turnwise", "turnwise-trim"])
        self.assertEqual(self.snapshot_user_settings(), before)                # the user's own turnwise settings were not touched

    def test_task_sets(self):
        self.run_harness("--arm", "baseline", "--set", "long")
        longs = [x["task"] for x in self.rows()]
        self.assertEqual(longs, ["long-more-itertools-three-bugs", "long-click-three-bugs", "long-humanize-feature-and-bug"])
        self.assertTrue(all(x["passed"] == "1" for x in self.rows()), [(x["task"], x["detail"]) for x in self.rows()])
        self.run_harness("--arm", "turnwise", "--set", "all")
        self.assertEqual(len([x for x in self.rows() if x["arm"] == "turnwise"]), 8)

    def test_a_long_task_half_done_fails(self):
        self.run_harness("--arm", "baseline", "--set", "long", mode="nothing")
        self.assertEqual({x["passed"] for x in self.rows()}, {"0"})

    def test_model_and_effort_are_passed_through(self):
        self.run_harness("--arm", "baseline", "--tasks", QUICK, "--model", "claude-sonnet-5-5", "--effort", "high")
        a = self.calls()[0]["argv"]
        self.assertEqual(a[a.index("--model") + 1], "claude-sonnet-5-5")
        self.assertEqual(a[a.index("--effort") + 1], "high")
        self.assertEqual(self.rows()[0]["model"], "claude-sonnet-5-5")

    def test_repeat_runs_and_appending(self):
        self.run_harness("--arm", "baseline", "--tasks", QUICK, "--runs", "2")
        self.run_harness("--arm", "baseline", "--tasks", QUICK)
        rows = self.rows()
        self.assertEqual([x["run"] for x in rows], ["1", "2", "3"])           # a later invocation continues the numbering
        self.assertEqual(self.raw("baseline", "*.result.json"), [f"{QUICK}-run{n}.result.json" for n in (1, 2, 3)])
        self.run_harness("--arm", "turnwise", "--tasks", QUICK)
        self.assertEqual(self.rows()[-1]["run"], "1")                         # each arm is numbered on its own
        with open(os.path.join(self.results, "summary.csv")) as f:
            self.assertEqual(f.read().count("arm,task,kind"), 1)                  # one header only


class Interleaving(Case):
    def test_arms_alternate_within_each_task_and_the_order_rotates(self):
        two = ["bugfix-small-tomli", QUICK]
        r = self.run_harness("--arm", "baseline", "turnwise", "--tasks", *two, "--runs", "2")
        self.assertEqual(r.returncode, 0, r.stderr)
        order = [(x["task"], x["arm"], x["run"]) for x in self.rows()]
        self.assertEqual(order, [
            ("bugfix-small-tomli", "turnwise", "1"), ("bugfix-small-tomli", "baseline", "1"),
            (QUICK, "baseline", "1"), (QUICK, "turnwise", "1"),
            ("bugfix-small-tomli", "baseline", "2"), ("bugfix-small-tomli", "turnwise", "2"),
            (QUICK, "turnwise", "2"), (QUICK, "baseline", "2")])
        first = [arm for i, (_, arm, _) in enumerate(order) if i % 2 == 0]
        self.assertEqual(first.count("baseline"), first.count("turnwise"))        # each arm goes first equally often
        self.assertIn("arms (interleaved) baseline, turnwise", r.stdout)
        self.assertIn("baseline: 4/4 solved · $2.00 spent", r.stdout)
        self.assertIn("turnwise: 4/4 solved · $2.00 spent", r.stdout)
        self.assertEqual(len(self.raw("baseline", "*.jsonl")) + len(self.raw("turnwise", "*.jsonl")), 16)   # 8 main + 8 subagent
        plug = ["--plugin-dir" in c["argv"] for c in self.calls()]
        self.assertEqual(plug, [x[1] == "turnwise" for x in order])
        self.assert_clean()

    def test_budget_is_shared_across_arms(self):
        self.run_harness("--arm", "baseline", "turnwise", "--budget", "5", cost="3")
        self.assertEqual(len(self.rows()), 2)
        self.assertEqual({x["arm"] for x in self.rows()}, {"baseline", "turnwise"})   # it stops mid-pair, not per arm

    def test_same_arm_named_twice_runs_once(self):
        self.run_harness("--arm", "baseline", "baseline", "--tasks", QUICK)
        self.assertEqual(len(self.rows()), 1)

    def test_third_party_plugin_arm(self):
        other = os.path.join(self.tmp, "other-plugin")
        os.makedirs(os.path.join(other, ".claude-plugin"))
        with open(os.path.join(other, ".claude-plugin", "plugin.json"), "w") as f:
            f.write('{"name": "other", "version": "0.0.1"}')
        r = self.run_harness("--arm", "baseline", "other", "--plugin", f"other={other}", "--tasks", QUICK)
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = {("--plugin-dir" in c["argv"]): c["argv"] for c in self.calls()}
        self.assertEqual(calls[True][calls[True].index("--plugin-dir") + 1], other)
        self.assertEqual(sorted(x["arm"] for x in self.rows()), ["baseline", "other"])

    def test_env_is_set_for_one_arm_only(self):
        other = os.path.join(self.tmp, "other-plugin")
        os.makedirs(os.path.join(other, ".claude-plugin"))
        with open(os.path.join(other, ".claude-plugin", "plugin.json"), "w") as f:
            f.write('{"name": "other", "version": "0.0.1"}')
        r = self.run_harness("--arm", "baseline", "other", "--plugin", f"other={other}", "--env", "other:BENCH_TEST_MARKER=full",
                             "--tasks", QUICK)
        self.assertEqual(r.returncode, 0, r.stderr)
        seen = {("--plugin-dir" in c["argv"]): c["marker_env"] for c in self.calls()}
        self.assertEqual(seen, {True: "full", False: None})
        self.assertIn("other runs with BENCH_TEST_MARKER=full", r.stdout)
        for bad in ["nosucharm:K=V", "baseline:NOEQUALS", "baseline:9BAD=1"]:
            self.assertNotEqual(self.run_harness("--arm", "baseline", "--env", bad, "--tasks", QUICK).returncode, 0, bad)

    def test_bad_arm_and_plugin_arguments_are_refused(self):
        missing = os.path.join(self.tmp, "not-a-plugin")
        os.makedirs(missing)
        for args in [["--arm", "baseline", "nonsense"], ["--arm", "x", "--plugin", f"x={missing}"],
                     ["--arm", "baseline", "--plugin", f"baseline={PLUGIN}"], ["--arm", "bad name", "--plugin", f"bad name={PLUGIN}"],
                     ["--arm", "x", "--plugin", "x"]]:
            r = self.run_harness(*args)
            self.assertNotEqual(r.returncode, 0, args)
        self.assertEqual(self.calls(), [])

    def test_results_folder_option_and_analysis(self):
        out = os.path.join(self.tmp, "elsewhere")
        self.run_harness("--arm", "baseline", "turnwise", "--tasks", QUICK, "--runs", "3", "--results", out)
        self.assertEqual(self.rows(), [])                                          # nothing went to the default folder
        self.assertTrue(os.path.exists(os.path.join(out, "raw", "turnwise", f"{QUICK}-run3.jsonl")))
        r = subprocess.run([sys.executable, os.path.join(BENCH, "harness", "analyze.py"), "--summary", os.path.join(out, "summary.csv")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("baseline: 3/3 solved", r.stdout)
        self.assertIn("+0.0%", r.stdout)                                           # the stand-in costs the same in both arms
        r = subprocess.run([sys.executable, os.path.join(BENCH, "harness", "analyze.py"), "--summary", os.path.join(out, "summary.csv"),
                            "--b", "no-such-arm"], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no task has runs in both", r.stderr)


class WrongWork(Case):
    def test_doing_nothing_fails_every_task(self):
        r = self.run_harness("--arm", "baseline", mode="nothing")
        self.assertEqual([x["passed"] for x in self.rows()], ["0"] * 5)
        self.assertIn("0/5 solved", r.stdout)
        self.assertNotIn("per solved task", r.stdout)
        self.assert_clean()

    def test_cheating_fails_every_task(self):
        self.run_harness("--arm", "baseline", mode="cheat")
        rows = {x["task"]: x for x in self.rows()}
        self.assertEqual([x["passed"] for x in rows.values()], ["0"] * 5, [(k, v["detail"]) for k, v in rows.items()])
        self.assertIn("failed", rows["bugfix-small-tomli"]["detail"])              # weakened tests were restored
        self.assertRegex(rows["feature-humanize-metric-v2"]["detail"], "failed|error")   # a stub is not an implementation
        self.assertIn("left the repository unchanged", rows["question-click-option-sources"]["detail"])
        self.assertIn("still present", rows["refactor-itsdangerous-rename"]["detail"])   # half a rename

    def test_scratch_files_do_not_fail_a_correct_task(self):
        self.run_harness("--arm", "baseline", mode="scratch")
        self.assertEqual([x["passed"] for x in self.rows()], ["1"] * 5, [(x["task"], x["detail"]) for x in self.rows()])


class Failures(Case):
    def test_budget_stops_new_runs_and_caps_each_task(self):
        r = self.run_harness("--arm", "baseline", "--budget", "5", "--runs", "3", cost="3")
        self.assertEqual(len(self.rows()), 2)                                      # $3, then $6: over, so stop
        self.assertEqual(r.stdout.count("budget reached"), 1)
        caps = [c["argv"][c["argv"].index("--max-budget-usd") + 1] for c in self.calls()]
        self.assertEqual(caps, ["5.00", "2.00"])                                   # the second task only gets what is left

    def test_tiny_remainder_is_not_handed_to_the_cli(self):
        self.run_harness("--arm", "baseline", "--budget", "1.1", cost="1")
        self.assertEqual(len(self.rows()), 1)                                      # $0.10 left is below the $0.25 floor

    def test_not_logged_in_stops_cleanly(self):
        r = self.run_harness("--arm", "baseline", mode="notlogged")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not logged in", r.stderr)
        self.assertEqual(self.rows(), [])
        self.assertEqual(len(self.calls()), 1)                                     # it did not go on to the other tasks
        self.assert_clean()

    def test_garbage_from_the_cli_is_a_failed_row_not_a_crash(self):
        r = self.run_harness("--arm", "baseline", "--tasks", QUICK, mode="notjson")
        self.assertEqual(r.returncode, 0, r.stderr)
        row = self.rows()[0]
        self.assertEqual((row["passed"], row["cost_usd"]), ("0", "0"))
        self.assertIn("no JSON from claude", row["detail"])
        self.assert_clean()

    def test_timeout_is_a_failed_row(self):
        r = self.run_harness("--arm", "baseline", "--tasks", QUICK, mode="hang", extra_env={"BENCH_TIMEOUT": "2"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("timed out after 2 seconds", self.rows()[0]["detail"])
        self.assertEqual(self.rows()[0]["passed"], "0")

    def test_hitting_the_cost_cap_is_recorded_with_its_cost(self):
        self.run_harness("--arm", "baseline", "--tasks", "refactor-itsdangerous-rename", mode="budget", cost="5")
        row = self.rows()[0]
        self.assertTrue(row["detail"].startswith("[error_max_budget_usd]"), row["detail"])
        self.assertEqual(row["cost_usd"], "5.0")
        self.assertEqual(row["passed"], "1")                                       # the work was finished before the cap hit

    def test_missing_transcript_is_noted(self):
        self.run_harness("--arm", "baseline", "--tasks", QUICK, mode="notranscript")
        row = self.rows()[0]
        self.assertEqual(row["passed"], "1")
        self.assertIn("no transcript found", row["detail"])
        self.assertEqual(self.raw("baseline", "*.jsonl"), [])

    def test_a_stalled_disk_is_retried_and_no_run_is_lost(self):
        # Seen live: the project sat in a synced folder, one write timed out, and the run crashed mid-way.
        fast = {"BENCH_RETRY_SECONDS": "0.01"}
        r = self.run_harness("--arm", "baseline", "turnwise", "--tasks", QUICK, "--runs", "2",
                             extra_env={**fast, "BENCH_FAIL_WRITES": "4"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(len(self.rows()), 4)                                     # every row made it after retries
        self.assertEqual(len(self.raw("baseline", "*.result.json")) + len(self.raw("turnwise", "*.result.json")), 4)

    def test_a_disk_that_never_recovers_does_not_crash_the_run(self):
        r = self.run_harness("--arm", "baseline", "--tasks", QUICK, extra_env={"BENCH_RETRY_SECONDS": "0.001", "BENCH_FAIL_WRITES": "9999"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("could not write a row", r.stdout)
        self.assertIn("1/1 solved", r.stdout)                                     # the run itself was still reported
        self.assert_clean()

    def test_rows_missing_from_the_summary_are_recovered_from_result_files(self):
        self.run_harness("--arm", "baseline", "turnwise", "--tasks", QUICK)
        path = os.path.join(self.results, "summary.csv")
        with open(path) as f:
            lines = f.read().splitlines()
        with open(path, "w") as f:
            f.write("\n".join(l for l in lines if not l.startswith("baseline,")) + "\n")   # as if that write had been lost
        self.assertEqual([x["arm"] for x in self.rows()], ["turnwise"])
        r = self.run_harness("--arm", "baseline", "turnwise", "--tasks", QUICK)
        self.assertIn("recovered 1 finished run", r.stdout)
        got = sorted((x["arm"], x["run"]) for x in self.rows())
        self.assertEqual(got, [("baseline", "1"), ("baseline", "2"), ("turnwise", "1"), ("turnwise", "2")])   # recovered, then continued
        r = self.run_harness("--arm", "baseline", "--tasks", QUICK)
        self.assertNotIn("recovered", r.stdout)                                   # nothing is recovered twice

    def test_old_results_file_with_other_columns_is_refused(self):
        os.makedirs(self.results)
        with open(os.path.join(self.results, "summary.csv"), "w") as f:
            f.write("arm,task,old_column\nbaseline,x,1\n")
        r = self.run_harness("--arm", "baseline", "--tasks", QUICK)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("different columns", r.stderr)
        self.assertEqual(self.calls(), [])                                         # nothing was run or spent

    def test_bad_arguments_are_refused_before_anything_runs(self):
        for args in [["--arm", "baseline", "--tasks", "no-such-task"], ["--arm", "baseline", "--runs", "0"],
                     ["--arm", "baseline", "--budget", "-1"], ["--arm", "nonsense"], [],
                     ["--arm", "baseline", "--per-task-cap", "0"]]:
            r = self.run_harness(*args)
            self.assertNotEqual(r.returncode, 0, args)
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.rows(), [])

    def test_missing_cli_path_is_reported(self):
        r = self.run_harness("--arm", "baseline", "--tasks", QUICK, "--claude", "/no/such/claude", fake=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("could not run the claude CLI", r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=1)
