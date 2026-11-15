#!/usr/bin/env python3
"""Tests for turnwise. Stdlib only. Run from anywhere:  python3 tests/test_turnwise.py

Every test uses synthetic transcripts and a temporary settings folder. Nothing reads or writes the
user's real Claude Code data or ~/.claude/turnwise.
"""
import datetime, json, os, shutil, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OPUS, SONNET = "claude-opus-5-5", "claude-sonnet-5-5"


def read(path, **kw):
    with open(path, **kw) as f:
        return f.read()


def stamp(seconds_ago):
    t = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=seconds_ago)
    return t.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def assistant(mid, seconds_ago, read=0, write=0, out=100, model=OPUS, one_hour=True, content=None, **extra):
    usage = {"input_tokens": 2, "cache_read_input_tokens": read, "cache_creation_input_tokens": write,
             "output_tokens": out, "output_tokens_details": {"thinking_tokens": out // 4},
             "cache_creation": {"ephemeral_1h_input_tokens": write if one_hour else 0,
                                "ephemeral_5m_input_tokens": 0 if one_hour else write}}
    return {"type": "assistant", "timestamp": stamp(seconds_ago), "sessionId": "sess",
            "message": {"id": mid, "model": model, "usage": usage,
                        "content": content or [{"type": "text", "text": f"answer {mid}"}]}, **extra}


def user(text, **extra):
    return {"type": "user", "sessionId": "sess", "message": {"role": "user", "content": text}, **extra}


def tool_use(tid, name, **inp):
    return {"type": "tool_use", "id": tid, "name": name, "input": inp}


def tool_result(tid, text):
    return user([{"type": "tool_result", "tool_use_id": tid, "content": text}])


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="turnwise-test-")
        self.home = os.path.join(self.tmp, "home")
        self.proj = os.path.join(self.tmp, "proj")
        os.makedirs(self.proj)
        self.env = {**os.environ, "TURNWISE_HOME": self.home}
        self.env.pop("TURNWISE_OFF", None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def transcript(self, entries, name="t.jsonl", raw=None):
        path = os.path.join(self.tmp, name)
        with open(path, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")
            if raw:
                f.write(raw)
        return path

    def run_py(self, rel, *args, stdin=None, env=None, cwd=None):
        return subprocess.run([sys.executable, os.path.join(ROOT, rel), *args], input=stdin, capture_output=True,
                              text=True, env=env or self.env, cwd=cwd or self.proj, timeout=60)

    def hook(self, name, payload, env=None):
        return self.run_py(f"hooks/{name}.py", stdin=payload if isinstance(payload, str) else json.dumps(payload), env=env)

    def config(self, *args):
        return self.run_py("scripts/config.py", *args)

    def big_stale(self, idle=4 * 3600, context=150000, **kw):
        return self.transcript([user("build the thing"),
                                assistant("m1", idle + 600, write=70000, **kw),
                                assistant("m2", idle, read=70000, write=context - 70000, **kw)])

    def prompt(self, transcript, session="s1"):
        return {"session_id": session, "transcript_path": transcript, "cwd": self.proj,
                "hook_event_name": "UserPromptSubmit", "prompt": "continue"}


class Packaging(Case):
    def test_manifest_and_hook_files_exist(self):
        manifest = json.loads(read(os.path.join(ROOT, ".claude-plugin", "plugin.json")))
        self.assertEqual(manifest["name"], "turnwise")
        hooks = json.loads(read(os.path.join(ROOT, "hooks", "hooks.json")))["hooks"]
        self.assertEqual(set(hooks), {"SessionStart", "UserPromptSubmit", "PreModelSwitch", "PostToolUse"})
        for groups in hooks.values():
            for g in groups:
                for h in g["hooks"]:
                    script = h["command"].split("${CLAUDE_PLUGIN_ROOT}/")[1].rstrip('"')
                    self.assertTrue(os.path.exists(os.path.join(ROOT, script)), script)

    def test_rules_stay_small(self):
        self.assertLess(len(read(os.path.join(ROOT, "rules.md"))) / 4, 600)

    def test_skill_has_name_and_description(self):
        text = read(os.path.join(ROOT, "skills", "turnwise", "SKILL.md"))
        front = text.split("---")[1]
        self.assertIn("name: turnwise", front)
        self.assertIn("description:", front)


class SessionStart(Case):
    def test_injects_rules(self):
        r = self.hook("session_start", {"hook_event_name": "SessionStart", "source": "startup"})
        ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Fewer requests", ctx)
        self.assertEqual(r.returncode, 0)

    def test_silent_when_rules_off(self):
        self.config("rules", "off")
        self.assertEqual(self.hook("session_start", {"source": "startup"}).stdout, "")

    def test_silent_when_env_off(self):
        r = self.hook("session_start", {"source": "startup"}, env={**self.env, "TURNWISE_OFF": "1"})
        self.assertEqual(r.stdout, "")

    def test_bad_input_does_nothing(self):
        r = self.hook("session_start", "not json")
        self.assertEqual((r.returncode, r.stdout), (0, ""))


class Guard(Case):
    def on(self):
        self.config("guard", "on")

    def test_off_by_default(self):
        r = self.hook("guard", self.prompt(self.big_stale()))
        self.assertEqual((r.returncode, r.stderr), (0, ""))

    def test_blocks_large_stale_session_with_prices(self):
        self.on()
        r = self.hook("guard", self.prompt(self.big_stale()))
        self.assertEqual(r.returncode, 2)
        self.assertIn("idle for 4h 0m", r.stderr)
        self.assertIn("150,102 tokens, about $1.20", r.stderr)     # 150,102 x $8/M (1-hour write, Opus 5.5)
        self.assertIn("70,002 tokens, about $0.56", r.stderr)
        self.assertIn(".turnwise/handoff.md", r.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.proj, ".turnwise", "handoff.md")))
        self.assertEqual(r.stdout, "")                              # nothing may reach the model

    def test_no_misleading_fresh_price_when_the_first_request_is_already_large(self):
        self.on()
        t = self.transcript([assistant("m1", 3 * 3600, read=40000, write=120000)])
        r = self.hook("guard", self.prompt(t))
        self.assertEqual(r.returncode, 2)
        self.assertIn("only the system prompt and tools", r.stderr)
        self.assertEqual(r.stderr.count("$"), 1)

    def test_resend_goes_through(self):
        self.on()
        p = self.prompt(self.big_stale())
        self.assertEqual(self.hook("guard", p).returncode, 2)
        self.assertEqual(self.hook("guard", p).returncode, 0)
        self.assertEqual(self.hook("guard", p).returncode, 0)

    def test_warns_again_after_a_later_pause(self):
        self.on()
        self.assertEqual(self.hook("guard", self.prompt(self.big_stale(idle=5 * 3600))).returncode, 2)
        self.assertEqual(self.hook("guard", self.prompt(self.big_stale(idle=2 * 3600))).returncode, 2)

    def test_sessions_are_tracked_separately(self):
        self.on()
        t = self.big_stale()
        self.assertEqual(self.hook("guard", self.prompt(t, "a")).returncode, 2)
        self.assertEqual(self.hook("guard", self.prompt(t, "b")).returncode, 2)

    def test_active_session_passes(self):
        self.on()
        self.assertEqual(self.hook("guard", self.prompt(self.big_stale(idle=600))).returncode, 0)

    def test_small_session_passes(self):
        self.on()
        self.assertEqual(self.hook("guard", self.prompt(self.big_stale(context=79000))).returncode, 0)

    def test_threshold_setting_is_respected(self):
        self.on()
        self.config("threshold", "200000")
        self.assertEqual(self.hook("guard", self.prompt(self.big_stale())).returncode, 0)
        self.config("threshold", "50000")
        self.assertEqual(self.hook("guard", self.prompt(self.big_stale(context=60000))).returncode, 2)

    def test_five_minute_cache_is_detected_and_priced(self):
        self.on()
        r = self.hook("guard", self.prompt(self.big_stale(idle=600, one_hour=False)))
        self.assertEqual(r.returncode, 2)                           # 10 minutes idle beats a 5-minute cache
        self.assertIn("about $0.75", r.stderr)                      # 150,100 x $5/M (5-minute write)

    def test_one_hour_cache_not_expired_at_ten_minutes(self):
        self.on()
        self.assertEqual(self.hook("guard", self.prompt(self.big_stale(idle=600))).returncode, 0)

    def test_subagent_requests_are_ignored(self):
        self.on()
        t = self.transcript([user("go"), assistant("m1", 5 * 3600, write=150000),
                             assistant("sub", 30, write=9000, isSidechain=True)])
        self.assertEqual(self.hook("guard", self.prompt(t)).returncode, 2)

    def test_env_switch_disables(self):
        self.on()
        r = self.hook("guard", self.prompt(self.big_stale()), env={**self.env, "TURNWISE_OFF": "1"})
        self.assertEqual(r.returncode, 0)

    def test_fails_open(self):
        self.on()
        empty = self.transcript([], "empty.jsonl")
        no_usage = self.transcript([user("hi")], "nousage.jsonl")
        broken = self.transcript([assistant("m1", 9000, write=150000)], "broken.jsonl", raw='{"type": "assist\n\x00\xff junk\n[1, 2]\n"text"\n7\nnull\n')
        unknown = self.transcript([assistant("m1", 9000, write=150000, model="some-other-model")], "unknown.jsonl")
        no_ts = self.transcript([{k: v for k, v in assistant("m1", 9000, write=150000).items() if k != "timestamp"}], "nots.jsonl")
        for payload in ["", "not json", "[]", json.dumps({"session_id": "x"}),
                        json.dumps(self.prompt("/no/such/file")), json.dumps(self.prompt(empty)),
                        json.dumps(self.prompt(no_usage)), json.dumps(self.prompt(unknown)), json.dumps(self.prompt(no_ts))]:
            r = self.hook("guard", payload)
            self.assertEqual((r.returncode, r.stderr), (0, ""), payload[:60])
        self.assertEqual(self.hook("guard", self.prompt(broken)).returncode, 2)   # bad lines are skipped, good ones used

    def test_still_warns_when_handoff_cannot_be_written(self):
        self.on()
        p = self.prompt(self.big_stale())
        p["cwd"] = "/dev/null/nowhere"
        r = self.hook("guard", p)
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("handoff", r.stderr)

    def test_corrupt_settings_fall_back_to_defaults(self):
        os.makedirs(self.home)
        with open(os.path.join(self.home, "config.json"), "w") as fh:
            fh.write("{broken")
        self.assertEqual(self.hook("guard", self.prompt(self.big_stale())).returncode, 0)   # default is off


class WarmNote(Case):
    """While the cache is warm, ask the agent to keep a handoff note up to date."""

    def warm(self, context=150000, name="t.jsonl"):
        return self.transcript([user("build the thing"), assistant("m1", 700, write=70000),
                                assistant("m2", 60, read=70000, write=context - 70000)], name)

    def ask(self, transcript, session="s1", env=None):
        r = self.hook("guard", self.prompt(transcript, session), env=env)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"] if r.stdout else None

    def test_off_by_default(self):
        self.assertIsNone(self.ask(self.warm()))

    def test_reminds_in_a_large_warm_session(self):
        self.config("warm_note", "on")
        text = self.ask(self.warm())
        self.assertIn("150,102 tokens", text)
        self.assertIn(".turnwise/handoff.md", text)
        self.assertIn("<!-- turnwise handoff · written by the agent · session s1 -->", text)
        self.assertLess(len(text) / 4, 200)                                   # the reminder itself stays small

    def test_asks_again_only_after_the_context_has_grown_enough(self):
        self.config("warm_note", "on")
        self.assertIsNotNone(self.ask(self.warm(150000)))
        self.assertIsNone(self.ask(self.warm(150000)))                         # same size: no repeat
        self.assertIsNone(self.ask(self.warm(165000, "b.jsonl")))              # grew 15k: below the 20k step
        self.assertIsNotNone(self.ask(self.warm(171000, "c.jsonl")))           # grew 21k since the last reminder
        self.assertIsNotNone(self.ask(self.warm(150000), session="other"))     # each session is tracked on its own

    def test_first_reminder_does_not_wait_for_growth(self):
        # Found in a live run: with a low threshold, a 19.9k-token session was never reminded, because the
        # first reminder was wrongly made to wait for 20k tokens of growth from zero.
        self.config("warm_note", "on")
        self.config("threshold", "5000")
        self.assertIsNotNone(self.ask(self.warm(19900)))
        self.assertIsNone(self.ask(self.warm(19900)))

    def test_step_setting_is_respected(self):
        self.config("warm_note", "on")
        self.config("note_every", "5000")
        self.assertIsNotNone(self.ask(self.warm(150000)))
        self.assertIsNotNone(self.ask(self.warm(156000, "b.jsonl")))

    def test_small_or_stale_sessions_get_no_reminder(self):
        self.config("warm_note", "on")
        self.assertIsNone(self.ask(self.warm(60000)))
        self.assertIsNone(self.ask(self.big_stale()))                          # cache expired: writing now would cost a rebuild

    def test_stale_session_with_both_options_on_blocks_and_does_not_remind(self):
        self.config("warm_note", "on")
        self.config("guard", "on")
        r = self.hook("guard", self.prompt(self.big_stale()))
        self.assertEqual((r.returncode, r.stdout), (2, ""))

    def test_guard_alone_does_not_remind(self):
        self.config("guard", "on")
        self.assertIsNone(self.ask(self.warm()))

    def test_env_switch_and_bad_input(self):
        self.config("warm_note", "on")
        self.assertIsNone(self.ask(self.warm(), env={**self.env, "TURNWISE_OFF": "1"}))
        for payload in ["", "not json", json.dumps({"session_id": "x"}), json.dumps(self.prompt("/no/such/file"))]:
            r = self.hook("guard", payload)
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""), payload[:40])


class ModelSwitch(Case):
    def payload(self, transcript, src=OPUS, dst=SONNET, session="s1"):
        return {"session_id": session, "transcript_path": transcript, "from_model": src, "to_model": dst}

    def test_blocks_once_with_price_then_allows(self):
        t = self.big_stale(idle=60)
        r = self.hook("model_switch", self.payload(t))
        self.assertEqual(r.returncode, 2)
        self.assertIn("150,102 tokens, about $0.60", r.stderr)     # priced at the target model: x $4/M
        self.assertEqual(self.hook("model_switch", self.payload(t)).returncode, 0)

    def test_a_different_target_warns_again(self):
        t = self.big_stale(idle=60)
        self.assertEqual(self.hook("model_switch", self.payload(t)).returncode, 2)
        self.assertEqual(self.hook("model_switch", self.payload(t, dst="claude-fable-5-2")).returncode, 2)

    def test_nearly_free_switch_is_not_stopped(self):
        # Seen live: switching a 70k-token session to Haiku was stopped to warn about a one-cent cost.
        t = self.big_stale(idle=60)
        r = self.hook("model_switch", self.payload(t, dst="claude-haiku-5-5"))       # 150,102 x $0.20/M = $0.03
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        small = self.transcript([assistant("m1", 60, write=22000)], "small.jsonl")
        self.assertEqual(self.hook("model_switch", self.payload(small)).returncode, 0)       # 22k x $4/M = $0.09: below ten cents
        medium = self.transcript([assistant("m1", 60, write=30000)], "medium.jsonl")
        self.assertEqual(self.hook("model_switch", self.payload(medium)).returncode, 2)      # 30k x $4/M = $0.12: worth saying

    def test_messages_are_single_line(self):
        r = self.hook("model_switch", self.payload(self.big_stale(idle=60)))
        self.assertEqual(r.stderr.strip().count("\n"), 0)
        self.config("guard", "on")
        g = self.hook("guard", self.prompt(self.big_stale()))
        self.assertEqual((g.returncode, g.stderr.strip().count("\n")), (2, 0))


    def test_unknown_target_warns_without_a_price(self):
        r = self.hook("model_switch", self.payload(self.big_stale(idle=60), dst="future-model-9"))
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("$", r.stderr)

    def test_passes_when_nothing_to_lose(self):
        small = self.transcript([assistant("m1", 60, write=15000)])
        self.assertEqual(self.hook("model_switch", self.payload(small)).returncode, 0)
        self.assertEqual(self.hook("model_switch", self.payload(self.big_stale(idle=60), dst=OPUS)).returncode, 0)

    def test_can_be_switched_off(self):
        self.config("switch_guard", "off")
        self.assertEqual(self.hook("model_switch", self.payload(self.big_stale(idle=60))).returncode, 0)

    def test_fails_open(self):
        for payload in ["", "not json", json.dumps({"to_model": SONNET}), json.dumps(self.payload("/no/such/file"))]:
            self.assertEqual(self.hook("model_switch", payload).returncode, 0, payload[:40])


class Trim(Case):
    LOG = "\n".join([f"Downloading package {i}/400 ... done" for i in range(400)] + ["collected 281 items"]
                    + [f"tests/test_m{i % 7}.py::test_{i} PASSED [{i * 100 // 281}%]" for i in range(140)]
                    + ["tests/test_m3.py::test_44 FAILED [50%]"]
                    + [f"tests/test_m{i % 7}.py::test_{i} PASSED [{i * 100 // 281}%]" for i in range(141, 281)]
                    + ["=== 1 failed, 280 passed in 12.4s ==="])
    JSON = json.dumps([{"id": i, "name": f"item {i}", "body": "x" * 120} for i in range(200)])
    PROSE = "\n".join(f"line {chr(97 + i % 26) * (i % 9 + 3)} about topic {chr(65 + i % 23)}{'!' * (i % 4)} ends" for i in range(1500))

    def setUp(self):
        super().setUp()
        self.config("trim", "on")

    def bash(self, command, stdout, tid="toolu_abc123", **resp):
        return {"session_id": "s", "cwd": self.proj, "hook_event_name": "PostToolUse", "tool_name": "Bash",
                "tool_use_id": tid, "tool_input": {"command": command},
                "tool_response": {"stdout": stdout, "stderr": "", "interrupted": False, "isImage": False, **resp}}

    def out(self, payload):
        r = self.hook("trim", payload)
        self.assertEqual(r.returncode, 0)
        return json.loads(r.stdout)["hookSpecificOutput"]["updatedToolOutput"] if r.stdout else None

    def test_off_by_default(self):
        self.config("trim", "off")
        self.assertIsNone(self.out(self.bash("pytest -v", self.LOG)))

    def test_log_is_shortened_and_keeps_what_matters(self):
        o = self.out(self.bash("pytest -v", self.LOG))
        self.assertLess(len(o["stdout"]), len(self.LOG) * 0.1)
        for needle in ["test_44 FAILED", "1 failed, 280 passed", "collected 281 items", "similar lines not shown",
                       "Downloading package 0/400", "Downloading package 399/400"]:
            self.assertIn(needle, o["stdout"])

    def test_result_keeps_the_bash_shape(self):
        o = self.out(self.bash("pytest -v", self.LOG, stderr="warn"))
        self.assertEqual(set(o), {"stdout", "stderr", "interrupted", "isImage"})
        self.assertEqual(o["stderr"], "warn")

    def test_full_text_is_saved_and_named(self):
        o = self.out(self.bash("pytest -v", self.LOG))
        path = o["stdout"].rsplit("Full output: ", 1)[1].rstrip("]\n")
        self.assertEqual(read(os.path.join(self.proj, path)), self.LOG)

    def test_json_list_keeps_first_items_and_count(self):
        o = self.out(self.bash("curl -s https://api.example/items", self.JSON))
        self.assertIn("190 more items of 200 not shown", o["stdout"])
        self.assertIn('"item 9"', o["stdout"])
        self.assertNotIn('"item 10"', o["stdout"])

    def test_long_text_keeps_start_and_end(self):
        o = self.out(self.bash("mytool report", self.PROSE))
        self.assertTrue(o["stdout"].startswith(self.PROSE[:200]))
        self.assertIn(self.PROSE[-200:], o["stdout"])
        self.assertIn("lines in the middle not shown", o["stdout"])
        self.assertLess(len(o["stdout"]), 7000)

    def test_short_runs_are_not_collapsed(self):
        text = "\n".join(["step 1 ok", "step 2 ok", "step 3 ok"] + [f"unique line {chr(97 + i % 26) * (i % 50 + 1)}" for i in range(600)])
        o = self.out(self.bash("mytool", text))
        for line in ["step 1 ok", "step 2 ok", "step 3 ok"]:
            self.assertIn(line, o["stdout"])

    def test_same_input_same_output(self):
        a = self.hook("trim", self.bash("pytest -v", self.LOG)).stdout
        b = self.hook("trim", self.bash("pytest -v", self.LOG)).stdout
        self.assertEqual(a, b)

    def test_small_result_untouched(self):
        self.assertIsNone(self.out(self.bash("pytest -v", self.LOG[:7999])))

    def test_exact_output_commands_untouched(self):
        for cmd in ["cat big.py", "git diff", "cd src && git diff HEAD~1", "rg -n TODO", "grep -rn foo .", "ls -la",
                    "find . -name '*.py'", "FOO=1 cat x.log", "sudo tail -n 500 /var/log/x", "make test | tail -100",
                    "git log --oneline", "sed -n 1,400p big.py"]:
            self.assertIsNone(self.out(self.bash(cmd, self.LOG)), cmd)

    def test_lookalike_commands_are_still_trimmed(self):
        for cmd in ["catalog-sync --all", "npm run lsp-check", "./findings.sh", "pytest tests/test_cat.py"]:
            self.assertIsNotNone(self.out(self.bash(cmd, self.LOG)), cmd)

    def test_images_and_interrupted_untouched(self):
        self.assertIsNone(self.out(self.bash("shot", self.LOG, isImage=True)))
        self.assertIsNone(self.out(self.bash("pytest", self.LOG, interrupted=True)))

    def test_mcp_text_blocks_shortened_other_blocks_kept(self):
        p = {"session_id": "s", "cwd": self.proj, "tool_name": "mcp__srv__search", "tool_use_id": "toolu_m1",
             "tool_response": [{"type": "text", "text": self.JSON}, {"type": "image", "data": "abc"}, {"type": "text", "text": "tiny"}]}
        o = self.out(p)
        self.assertLess(len(o[0]["text"]), 4000)
        self.assertEqual(o[1], {"type": "image", "data": "abc"})
        self.assertEqual(o[2], {"type": "text", "text": "tiny"})

    def test_mcp_string_shortened_unknown_shapes_untouched(self):
        base = {"session_id": "s", "cwd": self.proj, "tool_name": "mcp__srv__get", "tool_use_id": "toolu_m2"}
        self.assertIsInstance(self.out({**base, "tool_response": self.PROSE}), str)
        for resp in [{"content": self.PROSE}, None, 42, [], [self.PROSE]]:
            self.assertIsNone(self.out({**base, "tool_response": resp}), repr(resp)[:30])

    def test_other_tools_untouched(self):
        for name in ["Read", "Grep", "WebFetch", "Edit"]:
            p = self.bash("x", self.LOG)
            p["tool_name"] = name
            self.assertIsNone(self.out(p), name)

    def test_unicode_survives(self):
        text = "\n".join(f"résultat {i}: 日本語 ✓ {'é' * (i % 30 + 5)} {chr(0x4e00 + i)}" for i in range(900))
        o = self.out(self.bash("mytool", text))
        self.assertIn("日本語", o["stdout"])
        path = o["stdout"].rsplit("Full output: ", 1)[1].rstrip("]\n")
        self.assertEqual(read(os.path.join(self.proj, path), encoding="utf-8"), text)

    def test_fails_open(self):
        for payload in ["", "not json", "[]", json.dumps({"tool_name": "Bash"}),
                        json.dumps({"tool_name": "Bash", "tool_response": {"stdout": None}}),
                        json.dumps({"tool_name": "Bash", "tool_response": "a string"}),
                        json.dumps(self.bash("pytest", self.LOG) | {"cwd": "/dev/null/nowhere"})]:
            r = self.hook("trim", payload)
            self.assertEqual((r.returncode, r.stdout), (0, ""), payload[:50])

    def test_trims_are_logged_and_git_ignores_the_folder(self):
        os.makedirs(os.path.join(self.proj, ".git", "info"))
        self.out(self.bash("pytest -v", self.LOG))
        self.out(self.bash("pytest -v", self.LOG, tid="toolu_second"))
        entry = json.loads(read(os.path.join(self.home, "trim.log")).splitlines()[0])
        self.assertEqual((entry["tool"], entry["before"]), ("Bash", len(self.LOG)))
        self.assertEqual(read(os.path.join(self.proj, ".git", "info", "exclude")).count(".turnwise/"), 1)

    def test_old_saved_files_are_removed(self):
        d = os.path.join(self.proj, ".turnwise", "full")
        os.makedirs(d)
        old, new = os.path.join(d, "old.txt"), os.path.join(d, "new.txt")
        for f in (old, new):
            with open(f, "w") as fh:
                fh.write("x")
        os.utime(old, (0, 0))
        self.out(self.bash("pytest -v", self.LOG))
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(new))


class Handoff(Case):
    def build(self):
        return self.transcript([
            user("<system-reminder>ignore me</system-reminder>Fix the login bug"),
            assistant("m1", 500, content=[tool_use("t1", "Edit", file_path=os.path.join(self.proj, "src", "auth.py")),
                                          tool_use("t2", "Read", file_path=os.path.join(self.proj, "README.md"))]),
            tool_result("t1", "ok"),
            user("<bash-input>ls</bash-input><bash-stdout>a b c</bash-stdout>"),
            user("internal note", isMeta=True),
            assistant("sub", 400, content=[{"type": "text", "text": "subagent chatter"}], isSidechain=True),
            user("Now add a test " + "please " * 100),
            assistant("m2", 300, content=[tool_use("t3", "Write", file_path="/elsewhere/notes.md"),
                                          {"type": "text", "text": "Done. The fix is in auth.py."}])])

    def test_note_contents(self):
        r = self.run_py("scripts/handoff.py", self.build(), self.proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        note = read(os.path.join(self.proj, ".turnwise", "handoff.md"))
        self.assertIn("- Fix the login bug", note)
        self.assertIn("- src/auth.py", note)                 # project files shown relative
        self.assertIn("- /elsewhere/notes.md", note)         # others shown in full
        self.assertIn("Done. The fix is in auth.py.", note)
        for absent in ["ignore me", "a b c", "internal note", "subagent chatter", "README.md", "tool_result"]:
            self.assertNotIn(absent, note)
        self.assertIn("…", note)                             # the long request was cut
        self.assertIn("Full transcript of that session: " + os.path.realpath(self.tmp), os.path.realpath(self.tmp) and note.replace(self.tmp, os.path.realpath(self.tmp)))
        self.assertIn("do not read it whole", note)
        self.assertLess(len(note), 4600)

    AGENT = "<!-- turnwise handoff · written by the agent · session sess -->\nGoal: fix login. Decided to keep the old hash for now.\n"

    def with_agent_note(self, later=True, session="sess"):
        """A session where the agent wrote a note, with or without more work after it."""
        note = os.path.join(self.proj, ".turnwise", "handoff.md")
        os.makedirs(os.path.dirname(note), exist_ok=True)
        with open(note, "w") as f:
            f.write(self.AGENT.replace("session sess", f"session {session}"))
        entries = [user("Fix the login bug"),
                   assistant("m1", 500, content=[tool_use("t1", "Edit", file_path=os.path.join(self.proj, "src", "auth.py")),
                                                 {"type": "text", "text": "Fixed the login bug."},
                                                 tool_use("t2", "Write", file_path=note)])]
        if later:
            entries += [user("Now add a logout button"),
                        assistant("m2", 300, content=[tool_use("t3", "Edit", file_path=os.path.join(self.proj, "src", "ui.py")),
                                                      {"type": "text", "text": "Logout button added."}])]
        return self.transcript(entries), note

    def test_agent_note_is_kept_and_only_later_work_is_added(self):
        t, note = self.with_agent_note()
        self.assertEqual(self.run_py("scripts/handoff.py", t, self.proj).returncode, 0)
        text = read(note)
        self.assertTrue(text.startswith(self.AGENT.rstrip()))
        self.assertIn("## Since that note", text)
        self.assertIn("- Now add a logout button", text)
        self.assertIn("- src/ui.py", text)
        self.assertIn("Logout button added.", text)
        since = text.split("## Since that note")[1]
        for covered in ["Fix the login bug", "src/auth.py", "Fixed the login bug.", "handoff.md"]:
            self.assertNotIn(covered, since)                                  # the note already covers these

    def test_agent_note_with_nothing_after_it_says_so(self):
        t, note = self.with_agent_note(later=False)
        self.run_py("scripts/handoff.py", t, self.proj)
        self.assertIn("Nothing was asked and no file was changed after the note", read(note))

    def test_running_twice_does_not_stack_sections(self):
        t, note = self.with_agent_note()
        self.run_py("scripts/handoff.py", t, self.proj)
        self.run_py("scripts/handoff.py", t, self.proj)
        text = read(note)
        self.assertEqual((text.count("## Since that note"), text.count("Goal: fix login")), (1, 1))
        self.assertEqual(text.count("Full transcript of that session:"), 1)        # the pointer is added once, to the agent's note too

    def test_note_from_another_session_is_replaced(self):
        t, note = self.with_agent_note(session="someone-else")
        self.run_py("scripts/handoff.py", t, self.proj)
        text = read(note)
        self.assertNotIn("Goal: fix login", text)
        self.assertIn("Built from the previous session's transcript by a script", text)

    def test_agent_note_written_another_way_is_kept_with_a_caveat(self):
        note = os.path.join(self.proj, ".turnwise", "handoff.md")
        os.makedirs(os.path.dirname(note))
        with open(note, "w") as f:
            f.write(self.AGENT)
        t = self.transcript([user("Fix the login bug"), assistant("m1", 500, content=[{"type": "text", "text": "Done."}])])
        self.run_py("scripts/handoff.py", t, self.proj)
        text = read(note)
        self.assertIn("Goal: fix login", text)
        self.assertIn("could not tell which of this the note already covers", text)
        self.assertIn("- Fix the login bug", text)

    def test_guard_says_when_the_note_is_the_agents(self):
        self.config("guard", "on")
        t, _ = self.with_agent_note()
        big = self.transcript([json.loads(l) for l in read(t).splitlines()] + [assistant("m9", 4 * 3600 - 1, write=150000)], "big.jsonl")
        r = self.hook("guard", {**self.prompt(big, "sess")})
        self.assertEqual(r.returncode, 2)
        self.assertIn("A handoff note written by the agent is in .turnwise/handoff.md", r.stderr)

    def test_overwrites_instead_of_appending(self):
        t = self.build()
        self.run_py("scripts/handoff.py", t, self.proj)
        self.run_py("scripts/handoff.py", t, self.proj)
        self.assertEqual(read(os.path.join(self.proj, ".turnwise", "handoff.md")).count("# Handoff"), 1)

    def test_git_exclude_added_once_and_keeps_existing_lines(self):
        info = os.path.join(self.proj, ".git", "info")
        os.makedirs(info)
        with open(os.path.join(info, "exclude"), "w") as fh:
            fh.write("*.log")
        t = self.build()
        self.run_py("scripts/handoff.py", t, self.proj)
        self.run_py("scripts/handoff.py", t, self.proj)
        self.assertEqual(read(os.path.join(info, "exclude")), "*.log\n.turnwise/\n")

    def test_empty_transcript_still_writes_a_valid_note(self):
        r = self.run_py("scripts/handoff.py", self.transcript([]), self.proj)
        self.assertEqual(r.returncode, 0)
        self.assertIn("- none", read(os.path.join(self.proj, ".turnwise", "handoff.md")))

    def test_errors_are_reported(self):
        self.assertNotEqual(self.run_py("scripts/handoff.py", "/no/such/file", self.proj).returncode, 0)
        r = self.run_py("scripts/handoff.py", cwd=self.proj)   # no transcript exists for this temp folder
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no transcript found", r.stderr)


class Meter(Case):
    def root(self, files):
        root = os.path.join(self.tmp, "projects")
        for name, entries in files.items():
            os.makedirs(os.path.dirname(os.path.join(root, name)), exist_ok=True)
            with open(os.path.join(root, name), "w") as f:
                for e in entries:
                    f.write(json.dumps(e) + "\n")
        return root

    def report(self, root):
        out = os.path.join(self.tmp, "out.json")
        r = self.run_py("scripts/cost_anatomy.py", "--root", root, "--json", out)
        return r, (json.loads(read(out)) if os.path.exists(out) else None)

    def test_costs_match_hand_calculation(self):
        root = self.root({"p/a.jsonl": [
            user("go"),
            assistant("m1", 9000, write=100000, out=1000),                    # 100k x $8 + 1k x $20 = 0.80 + 0.02
            assistant("m2", 8990, read=100000, write=10000, out=500),          # 0.02 + 0.08 + 0.01
            assistant("m3", 8980, read=110000, write=1000, out=0, model=SONNET, one_hour=False)]})  # 0.011 + 0.0025
        r, rows = self.report(root)
        self.assertEqual(r.returncode, 0, r.stderr)
        c = rows[0]["cost"]
        self.assertAlmostEqual(c["cache_write"], 0.80 + 0.08 + 0.0025, places=6)
        self.assertAlmostEqual(c["cache_read"], 0.02 + 0.011, places=6)
        self.assertAlmostEqual(c["output"], 0.02 + 0.01, places=6)
        self.assertAlmostEqual(c["uncached_input"], (2 * 4 + 2 * 4 + 2 * 2) / 1e6, places=9)
        self.assertEqual((rows[0]["requests"], rows[0]["user_prompts"]), (3, 1))

    def test_cache_breaks_are_classified(self):
        root = self.root({"p/a.jsonl": [
            assistant("m1", 30000, write=100000),
            assistant("m2", 29990, read=100000, write=2000),                   # normal growth
            assistant("m3", 10000, read=20000, write=90000),                   # hours later: idle expiry
            assistant("m4", 9990, read=20000, write=95000, model=SONNET),      # model switch
            assistant("m5", 9980, read=115000, write=1000, model=SONNET)]})
        _, rows = self.report(root)
        self.assertEqual(rows[0]["cache_breaks"], {"break_idle_expiry": 1, "break_model_switch": 1})
        w = rows[0]["write_cost_by_cause"]
        self.assertAlmostEqual(w["break_idle_expiry"], 90000 * 8 / 1e6)
        self.assertAlmostEqual(w["break_model_switch"], 95000 * 4 / 1e6)
        self.assertAlmostEqual(w["session_start"], 100000 * 8 / 1e6)

    def test_repeated_requests_in_forked_sessions_count_once(self):
        shared = [assistant("m1", 9000, write=50000), assistant("m2", 8990, read=50000, write=1000)]
        root = self.root({"p/a.jsonl": shared, "p/b.jsonl": shared + [assistant("m3", 8000, read=51000, write=500)]})
        _, rows = self.report(root)
        self.assertEqual(sum(r["requests"] for r in rows), 3)

    def test_streamed_duplicates_of_one_request_count_once(self):
        root = self.root({"p/a.jsonl": [assistant("m1", 900, write=50000, out=10), assistant("m1", 900, write=50000, out=400)]})
        _, rows = self.report(root)
        self.assertEqual(rows[0]["requests"], 1)
        self.assertEqual(rows[0]["tokens"]["output"], 400)

    def test_rereads_and_big_reads(self):
        f = "/p/x.py"
        root = self.root({"p/a.jsonl": [
            assistant("m1", 900, write=50000, content=[tool_use("t1", "Read", file_path=f)]), tool_result("t1", "y" * 12000),
            assistant("m2", 890, read=50000, content=[tool_use("t2", "Read", file_path=f)]), tool_result("t2", "y" * 12000),
            assistant("m3", 880, read=50000, content=[tool_use("t3", "Edit", file_path=f)]), tool_result("t3", "ok"),
            assistant("m4", 870, read=50000, content=[tool_use("t4", "Read", file_path=f, offset=1, limit=20)]), tool_result("t4", "z" * 400)]})
        _, rows = self.report(root)
        r = rows[0]
        self.assertEqual((r["reads"], r["rereads"], r["reread_tokens"]), (3, 1, 3000))   # the read after the edit is not a re-read
        self.assertEqual(r["whole_big_reads"], 2)

    def test_different_line_ranges_of_one_file_are_not_rereads(self):
        f = "/p/big.py"
        calls = [("t1", dict(offset=100, limit=20)), ("t2", dict(offset=900, limit=40)),      # two different ranges
                 ("t3", dict(offset=100, limit=20)),                                           # the first range again
                 ("t4", {}), ("t5", dict(offset=5000, limit=10))]                              # whole file, then a part of it
        entries = []
        for i, (tid, inp) in enumerate(calls):
            entries += [assistant(f"m{i}", 900 - i, read=50000, content=[tool_use(tid, "Read", file_path=f, **inp)]),
                        tool_result(tid, "y" * 400)]
        _, rows = self.report(self.root({"p/a.jsonl": entries}))
        self.assertEqual((rows[0]["reads"], rows[0]["rereads"], rows[0]["reread_tokens"]), (5, 2, 200))

    def test_unknown_models_and_bad_lines_are_skipped(self):
        root = self.root({"p/a.jsonl": [assistant("m1", 900, write=50000), assistant("m2", 890, write=50000, model="<synthetic>")]})
        with open(os.path.join(root, "p", "a.jsonl"), "a") as fh:
            fh.write("{broken json\n\n[1,2]\n\"text\"\n7\nnull\n")
        r, rows = self.report(root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(rows[0]["requests"], 1)

    def test_empty_folder_gives_a_clear_message(self):
        r, rows = self.report(self.root({"p/a.jsonl": [user("hi")]}))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no sessions with usage data", r.stderr)
        self.assertIsNone(rows)


class Audit(Case):
    def test_groups_sizes_and_unused(self):
        tools = [{"name": f"Builtin{i}", "description": "d" * 400, "input_schema": {}} for i in range(10)]
        tools += [{"name": "mcp__used__go", "description": "u" * 800, "input_schema": {}},
                  {"name": "mcp__idle__a", "description": "i" * 1200, "input_schema": {}},
                  {"name": "mcp__idle__b", "description": "i" * 1200, "input_schema": {}}]
        shape = {"type": "api-request-shape", "shape": {"system": [{"type": "text", "text": "s" * 4000}], "tools": tools}}
        root = os.path.join(self.tmp, "projects", "p")
        os.makedirs(root)
        with open(os.path.join(root, "a.jsonl"), "w") as f:
            for e in [shape, assistant("m1", 900, write=50000, content=[tool_use("t1", "mcp__used__go")])]:
                f.write(json.dumps(e) + "\n")
        r = self.run_py("scripts/audit.py", "--root", os.path.dirname(root))
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = {l.split()[0]: l for l in r.stdout.splitlines() if l.strip()}
        self.assertIn("never called", lines["idle"])
        self.assertNotIn("never called", lines["used"])
        self.assertNotIn("never called", lines["(built-in"])
        self.assertIn("13 tool definitions", r.stdout)

    def test_no_shape_gives_a_clear_message(self):
        root = os.path.join(self.tmp, "projects")
        os.makedirs(root)
        r = self.run_py("scripts/audit.py", "--root", root)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no session with a recorded request shape", r.stderr)


class Config(Case):
    def test_defaults(self):
        out = self.config().stdout
        for line in ["rules              on", "guard              off", "switch_guard       on", "trim               off",
                     "warm_note          off", "threshold_tokens   80000", "note_every_tokens  20000"]:
            self.assertIn(line, out)

    def test_changes_persist(self):
        self.config("guard", "on")
        self.config("threshold", "120000")
        out = self.config().stdout
        self.assertIn("guard              on", out)
        self.assertIn("threshold_tokens   120000", out)
        self.assertIn("trim               off", out)

    def test_bad_arguments_change_nothing(self):
        for args in [("guard", "maybe"), ("nonsense", "on"), ("threshold", "-5"), ("threshold", "abc"), ("guard",), ("guard", "on", "extra"),
                     ("warm_note", "yes"), ("note_every", "0"), ("note_every", "x")]:
            r = self.config(*args)
            self.assertNotEqual(r.returncode, 0, args)
        self.assertFalse(os.path.exists(os.path.join(self.home, "config.json")))


if __name__ == "__main__":
    unittest.main(verbosity=1)
