#!/usr/bin/env python3
"""Live check: does Claude Code accept turnwise's shortened tool results?  (costs a few cents)

  python3 bench/harness/livecheck.py

Runs one headless prompt with the plugin loaded and adaptive trim on. The prompt makes the agent run a command
that prints 900 near-identical lines (about 18,000 characters: large enough for trim, below Claude Code's own
30,000-character limit). It then reads the transcript to see what the model was actually given.

PASS means the model received the shortened output and still answered correctly.
The model-switch warning cannot be checked this way: see the note printed at the end.
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run as H  # noqa: E402

COMMAND = "python3 -c \"for i in range(900): print('row', i, 'status ok')\""
PROMPT = f"Run this exact command once with the Bash tool and tell me the last line it prints: {COMMAND}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--claude")
    a = ap.parse_args()
    claude = H.find_claude(a.claude)
    work = tempfile.mkdtemp(prefix="turnwise-bench-live-")
    home = tempfile.mkdtemp(prefix="turnwise-bench-home-")
    env = {**os.environ, "TURNWISE_HOME": home}
    subprocess.run([sys.executable, os.path.join(H.PLUGIN, "scripts", "config.py"), "trim", "on"], env=env, capture_output=True)
    project = None
    try:
        r = subprocess.run([claude, "-p", PROMPT, "--model", a.model, "--output-format", "json", "--allowedTools", "Bash",
                            "--permission-mode", "acceptEdits", "--setting-sources", "project", "--strict-mcp-config",
                            "--max-budget-usd", "1.00", "--plugin-dir", H.PLUGIN],
                           cwd=work, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=300)
        try:
            out = json.loads(r.stdout)
        except ValueError:
            sys.exit("no JSON from claude: " + (r.stdout + r.stderr)[-300:])
        answer = out.get("result") or ""
        found = H.transcript_for(out.get("session_id") or "-")
        project = os.path.dirname(found) if found else None     # removed in the finally block, whatever happens next
        if re.match(r"\s*(Not logged in|Invalid API key|Please run /login)", answer):
            sys.exit("claude is not logged in. Run it once interactively and use /login, then retry.")
        transcript = H.transcript_for(out.get("session_id") or "-")
        if not transcript:
            sys.exit("the run left no transcript to inspect")
        project = os.path.dirname(transcript)
        results = []
        with open(transcript, errors="replace") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                c = (d.get("message") or {}).get("content") if isinstance(d, dict) else None
                for b in c if isinstance(c, list) else []:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        t = b.get("content")
                        results.append(t if isinstance(t, str) else "".join(x.get("text", "") for x in t or [] if isinstance(x, dict)))
        print(f"cost ${out.get('total_cost_usd') or 0:.3f} · tool results seen by the model: {len(results)}")
        big = max(results, key=len) if results else ""
        trimmed = "[turnwise: shortened" in big
        saved = os.path.isdir(os.path.join(work, ".turnwise", "full")) and bool(os.listdir(os.path.join(work, ".turnwise", "full")))
        log = os.path.exists(os.path.join(home, "trim.log"))
        correct = "row 899 status ok" in answer
        print(f"  hook ran and shortened the output (its log exists):        {'yes' if log else 'NO'}")
        print(f"  full output was saved under .turnwise/full/:               {'yes' if saved else 'NO'}")
        print(f"  the model was given the shortened output:                  {'yes' if trimmed else 'NO'}  ({len(big):,} characters)")
        print(f"  the model still answered correctly (row 899 status ok):    {'yes' if correct else 'NO'}")
        if trimmed and correct:
            print("\nPASS: Claude Code accepted the shortened result.")
        elif log and not trimmed:
            print("\nFAIL: the hook ran, but Claude Code gave the model the original output. The replacement was not accepted.")
        elif not log:
            print("\nFAIL: the hook did not shorten anything. Either it did not fire or it decided to pass the result through.")
        else:
            print("\nPARTIAL: the result was shortened but the answer was wrong; read the transcript.")
        if big:
            print("\nwhat the model saw (start and end):\n  " + big[:160].replace("\n", "\n  ") + "\n  …\n  " + big[-200:].replace("\n", "\n  "))
        print("\nNot covered here: the model-switch warning. To check it, start `claude --plugin-dir turnwise` in a terminal,\n"
              "have a conversation of a few turns, then change model with /model. A turnwise message should stop the\n"
              "first attempt and show a cost; repeating /model should go through.")
    finally:
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(home, ignore_errors=True)
        if project and "turnwise-bench-" in os.path.basename(project):
            shutil.rmtree(project, ignore_errors=True)


if __name__ == "__main__":
    main()
