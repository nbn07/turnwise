# turnwise benchmark: pilot harness

Runs coding tasks through Claude Code and records what each one cost and whether it was solved. Results so far are in [the pilot report](../report/PILOT-RESULTS.md). This is the 5-task pilot, not the full benchmark described in [the design](../research/design.md).

**Status:** the tasks and their checks are verified without the model, and the harness has 20 automated tests driven by a stand-in for the CLI (`python3 bench/tests/test_harness.py`, 28 tests). No task has been run through Claude yet, because the CLI on this machine is not logged in.

## Before the first run

Log the CLI in (open it once and use `/login`), or set `ANTHROPIC_API_KEY` in your shell profile. Then check the tasks themselves, which costs nothing:

```bash
python3 bench/harness/run.py --selftest
```

The first run fetches five repos at pinned commits into `bench/.cache/` and builds a test environment in `bench/.venv/`.

## Run the baseline

This sends real requests and costs real money. It stops starting new runs once `--budget` dollars are spent (default 20), and each task is capped at `--per-task-cap` (default 5).

```bash
python3 bench/harness/run.py --arm baseline --budget 20
```

Compare with the plugin afterwards:

```bash
python3 bench/harness/run.py --arm turnwise --budget 20
```

```bash
python3 bench/harness/run.py --arm turnwise-trim --budget 20
```

### Interleaved arms (preferred)

Name several arms and each task is run once per arm in turn, with the order of the arms rotating. Drift over time (service load, cache state) then falls on every arm equally. Use a separate results folder so these runs are not pooled with the earlier one-arm-at-a-time runs:

```bash
python3 bench/harness/run.py --arm baseline turnwise --runs 6 --budget 8 --results bench/results/interleaved
```

```bash
python3 bench/harness/analyze.py --summary bench/results/interleaved/summary.csv
```

### Another tool as an arm

Any Claude Code plugin folder can be an arm. Read its hook scripts before running it: they execute on your machine.

```bash
python3 bench/harness/run.py --arm baseline turnwise other --plugin other=/path/to/plugin --results bench/results/interleaved
```

Useful options: `--tasks ID ...` to run some tasks, `--runs N` to repeat, `--model`, `--effort` to pin the effort level, `--keep` to keep each throwaway repo copy.

## Session test

The task runs above cannot show what the guards are for, because a short headless run has no idle gap and no model switch. `sessions.py` measures those directly. It builds two sessions of about 170k and 200k tokens, then compares:

- **Stale session:** the same follow-up bug fix after the cache has expired, by resuming the old session or by starting fresh from turnwise's handoff note.
- **Model switch:** the same small job while the cache is warm, by continuing on a cheaper model or by staying on the same one.

```bash
python3 bench/harness/sessions.py --selftest
```

```bash
python3 bench/harness/sessions.py --budget 10
```

With the default two trials it takes about an hour, mostly six-minute waits for the cache to expire, and stops when the budget cannot cover the next step. Before every run the repo copy and the session transcript are put back as the build left them. Each row records how many tokens the first request read from cache and wrote to it, which shows whether the cache was in the state the scenario needs. Tests: `python3 bench/tests/test_sessions.py` (12, with a stand-in CLI).

Limits: headless runs use a 5-minute cache at $5 per million tokens written, where desktop sessions use a 1-hour cache at $8, so the dollar gap in real desktop use is about 1.6 times larger. The test shows what each choice costs, not how often a person makes the cheaper one. Two sessions is a small sample. The stale-session results in the report use `--scenarios stale --trials 5` (about two hours and $14).

## Dependent follow-up test

The session test's follow-up was self-contained. This one is not: the agent chooses a made-up name for a helper, is then given an unrelated job whose reply is pinned to one word, and the follow-up asks for the helper "using the name you picked earlier". The name is in neither the code, nor the user's words, nor the last answer. It is done four ways:

| Way | What the new session has |
|---|---|
| `resume` | The old session itself |
| `fresh-bare` | The script-built note only; the old transcript is removed from disk |
| `fresh-script` | The script-built note, which says where the old transcript is and to search it |
| `fresh-agent` | The note the agent wrote when turnwise's `warm_note` option reminded it |

The build runs with the plugin, so this is also the live check that the agent writes that note.

```bash
python3 bench/harness/dependent.py --budget 2
```

About $0.45 per trial, three trials by default. Expected: `fresh-bare` fails and the other three pass. Tests: `python3 bench/tests/test_dependent.py` (8).

**First version, kept in `bench/results/dependent/`.** It had three ways and did not isolate the choice: twice the agent's last answer named the helper ("the veritoxal helper is not added yet"), so the script-built note carried the name; once the note did not, and the fresh session went and found the name in the old transcript on disk by itself. That is where the transcript pointer in the note came from. It also exposed a bug: one of three builds got no reminder, because the first reminder was made to wait for 20k tokens of growth. The agent wrote a note both times it was reminded.

## Live check for adaptive trim

One prompt, a few cents. It reports whether Claude Code gave the model the shortened tool result.

```bash
python3 bench/harness/livecheck.py
```

## The tasks (version 3)

| Task | Kind | Repo at pinned tag | What makes it pass |
|---|---|---|---|
| `bugfix-small-tomli` | Bug fix | tomli 2.0.1 (1.3k lines) | The project's own tests pass |
| `bugfix-largefile-more-itertools` | Bug fix in a 4,656-line file | more-itertools 10.2.0 | The project's own tests pass |
| `feature-humanize-metric-v2` | Feature with tests | humanize 4.9.0 | The project's own tests for the feature pass |
| `question-click-option-sources` | Codebase question | click 8.1.7 (17.5k lines) | The answer names the function, the file and two of the sources, and no file changed |
| `refactor-itsdangerous-rename` | Rename across files | itsdangerous 2.1.2 | Old name gone, new name at all three sites, tests pass |

Three longer tasks, each with several independent problems in one session, are in a separate set:

| Task | What it contains |
|---|---|
| `long-more-itertools-three-bugs` | Three bugs in one 4,656-line file |
| `long-click-three-bugs` | Three bugs in click's parameter types |
| `long-humanize-feature-and-bug` | One bug and the `metric` feature |

```bash
python3 bench/harness/run.py --arm baseline turnwise --set long --runs 6 --budget 12 --results bench/results/long
```

They are longer than the pilot tasks but still not long: expect roughly 8 to 15 requests each, not the 30 or more a real working session reaches. No run has been made with them yet.

Each bug-fix or feature task starts from the real code with one change applied: a bug put in, or a feature removed along with its tests. Before checking, the harness restores the project's original tests, so editing the tests cannot make a task pass. The agent's copy has no git history, so the change cannot be found with `git diff`.

## What a run records

- `bench/results/summary.csv`: one row per run with pass/fail, cost, request count, tokens by billing category, model and Claude Code version.
- `bench/results/raw/<arm>/`: the full transcript and Claude Code's result for every run.
- A cost breakdown by driver for the arm, printed at the end and saved as `bench/results/cost_anatomy_<arm>.json`.

## How the runs are isolated

- Each task runs in a fresh copy of its repo in the system temp folder, deleted afterwards.
- Claude Code is started with `--setting-sources project --strict-mcp-config`, so your own plugins, settings and MCP servers are not loaded. Checked on 2.1.325: no MCP servers, and the only plugins are the five that ship inside Claude Code, plus turnwise in the turnwise arms.
- The agent may use Read, Edit, Write, Grep, Glob, Bash and Task (subagents) inside that copy. Other tools are refused. **Bash is not sandboxed**, so it runs with your user's permissions like any Claude Code session.
- The `turnwise` arms use a temporary settings folder. Your own turnwise settings are not read or changed.

## Limits to keep in mind

- **Five tasks, one run each, is a pilot.** It shows the shape of the cost and whether the harness works. It cannot support a savings claim; that needs the full task set, three runs per task and confidence intervals.
- **These are well-known repos.** The model may recognise them, which makes the tasks easier than private code.
- **Put-in bugs are simpler than real ones.** They are one-line changes with a clear symptom in the prompt.
- **The question check is keyword-based.** It can pass a vague answer that happens to use the right words. Read the answers in the raw results before trusting it.
- **A passing self-test does not prove a prompt is complete.** The first feature prompt gave the wrong prefix range, and the agent failed by following it exactly. That row (`feature-humanize-metric`, no `-v2`) in `summary.csv` is invalid and must be left out of any total. The self-test only shows the reference solution passes; whether the prompt says enough to reach it has to be read by a person.
- **The rename task is easy.** It measures the cost of a small multi-file change, not a real restructuring.
- **Cost is Claude Code's own `total_cost_usd`** at API list prices.
- **Two competitors have been run** (Ponytail and Caveman's voice plugin): see the [comparison results](../report/COMPARISON-RESULTS.md). Some tools need a setting to be active in headless runs; pass it with `--env ARM:KEY=VALUE`. Clear any first-run prompt a tool shows before measuring it.
- **The first pilot was not interleaved.** Its results are in `bench/results/summary.csv`; see the pilot report for what that means.
