# turnwise

A Claude Code plugin that shows where a session's money goes and warns you before the two most expensive avoidable moves: resuming a large session after its cache has expired, and switching models mid-session.

It is a session-cost guard and meter. It is not a general token saver, and the evidence below says why.

## What the evidence shows

| Claim | Evidence | Status |
|---|---|---|
| Starting fresh from a handoff note is far cheaper than resuming a stale session | Same follow-up bug fix in two sessions of 172k and 204k tokens: $0.09 fresh against about $1.00 resumed, all passing | Demonstrated, one trial per session. [Session results](../report/SESSION-RESULTS.md) |
| Staying on the same model beats switching to a cheaper one for a small job | Same small job in two sessions: $0.13–$0.16 staying against $0.45–$0.53 switching, all passing | Demonstrated, one trial per session |
| A fresh session can finish work that depends on an earlier decision | The agent picked a name the follow-up needed. Fresh sessions passed 3 of 3 with the agent's note, 3 of 3 with the script note pointing at the old transcript, and 0 of 3 with the script note alone | Demonstrated, three trials, one kind of dependency. [Dependent follow-up results](../report/DEPENDENT-RESULTS.md) |
| These rebuilds are a real share of spend | 12% (idle gaps) and 7% (model switches) of $25 across seven real desktop sessions | Measured on one person's usage. [Cost anatomy](../research/cost-anatomy.md) |
| The working rules make the agent quicker and terser | 9% fewer turns, 12% less output, 13% faster on five short coding tasks, 30 of 30 solved in both arms | Measured, arms interleaved. [Pilot results](../report/PILOT-RESULTS.md) |
| The working rules lower cost | It depends on the task. Two feature-writing tasks: −8% and −34%. Six other tasks (bug fixes, a question, a rename): no saving. Five short tasks together: −4.2%, interval −8.8% to +0.5% | **Not established as a general saving.** On the feature tasks the agent also switched from Read and Edit calls to shell scripts, which is cheaper but harder to review |
| How the rules compare with other tools | Eight short coding tasks, 100 interleaved runs, all solved by every arm. Cost per solved task against no plugin: turnwise −12.4%, Ponytail −5.7%, Caveman's voice plugin +11.6% | Measured on these tasks only. Most of the gap is the size of each plugin's opening context, which matters most on short sessions. Not a general ranking. [Comparison results](../report/COMPARISON-RESULTS.md) |

Things to keep in mind when reading the first two rows: the ratio is smaller in desktop sessions, which open with far more context than a headless run (roughly 2 to 1 for a 150k-token session); the follow-up tasks were self-contained; and the guard only informs, so the saving depends on taking its advice.

## What is in it

| Piece | What it does | Default |
|---|---|---|
| Working rules ([rules.md](rules.md), about 365 tokens) | Injected at session start. Batch tool calls, keep results small, delegate bulk reading to a cheaper subagent, edit instead of rewriting, stop after two failed attempts | On |
| Stale-session guard | When you send a prompt to a large session whose cache has expired, it stops the prompt once, writes a handoff note, and shows the price of resuming against starting fresh. Send again to resume | **Off** |
| Warm-cache handoff note | In a large session whose cache is still warm, asks the agent to keep `.turnwise/handoff.md` up to date (goal, what is done, decisions and why, next step). It asks again only after the context has grown by 20k tokens. If the session later goes stale, the script keeps that note and adds only what happened after it | **Off** |
| Model-switch warning | Stops a mid-session model change once and shows what rebuilding the cache will cost. Stays silent when that cost is under ten cents | On |
| Adaptive trim | Shortens large, noisy Bash and MCP results (repeated log lines, long JSON lists, long text) and saves the full text to `.turnwise/full/` for the agent to read back. File views, diffs, images and results under about 2k tokens are left alone | **Off** |
| `/turnwise` skill | Cost report, prefix audit, handoff note, settings | On request |

Everything is Python standard library. No proxy, no account, no network calls, no model calls.

## Install

In Claude Code 2.1.275 or later:

```
/plugin marketplace add nbn07/turnwise
/plugin install turnwise@turnwise
```

Installing from the marketplace was tested on Claude Code 2.1.325 from the command line; installing through the desktop app has not been tested.

To try it for one session without installing:

```bash
claude --plugin-dir /path/to/turnwise
```

To remove it: `/plugin uninstall turnwise@turnwise`, then delete `~/.claude/turnwise/` (settings) and any `.turnwise/` folder in your projects (handoff notes and saved tool output).

Requires `python3` on your PATH. Windows has not been tested.

## Use

Ask in plain words ("where did my tokens go?", "what's in my prefix?") or run the scripts yourself:

```bash
python3 scripts/cost_anatomy.py
```

```bash
python3 scripts/audit.py
```

```bash
python3 scripts/handoff.py
```

```bash
python3 scripts/config.py guard on
```

```bash
python3 scripts/config.py trim on
```

```bash
python3 scripts/config.py warm_note on
```

## What has been checked, and what has not

| Item | State |
|---|---|
| Plugin loads; session-start and prompt hooks fire in Claude Code 2.1.325 | Observed |
| A blocked prompt makes no API request and costs $0 | Observed |
| Guard, end to end: the real CLI resumed a large idle session; the first prompt was blocked at $0 with the price message and a handoff note, the resend went through | Observed |
| All hooks and scripts: expected behaviour and failure cases | 83 automated tests, all passing (`python3 tests/test_turnwise.py`) |
| Adaptive trim: shortens logs, JSON and long text; leaves small results, file views, diffs and images alone; same input gives same output | Tested with sample results in the documented Bash result format |
| Adaptive trim inside a live session | Observed once on 2.1.325: a 16,089-character Bash result reached the model as 172 characters, the full text was saved, and the model still answered correctly. MCP results have not been checked live |
| Warm-cache note: reminder fires only in a large warm session, repeats only after growth; the script keeps the agent's note and adds later work | Automated tests; the real CLI ran the hook and accepted its output |
| Warm-cache note: the agent writes the note when reminded | Observed: five of five times it was reminded across two live runs, it wrote a note with the goal, the decision, where the code is and the next step. Its cost has not been measured |
| A fresh session can recover something the note leaves out | Observed: with a note that says where the old transcript is, fresh sessions found a missing detail there 3 of 3 times; with the transcript removed they failed 3 of 3 |
| Meter totals against Claude Code's own cost record | Within about 10% |
| The model receives the injected rules and works differently with them | Observed in the pilot: fewer requests, fewer reads, less output |
| Model-switch warning | Observed once on 2.1.325 in an interactive session: the first `/model` was stopped with the cost message and the second went through |
| A cost saving from the working rules | **Not established.** Pilot: −4.2%, interval −8.8% to +0.5% |
| The cost gap the stale-session guard and the model-switch warning point at | Demonstrated in the session test, one trial per session |
| A saving from the prefix audit or adaptive trim | **Not measured** |

## Limits

- The guards and the rule injection are Claude Code only. For other agents, paste [rules.md](rules.md) into the agent's rules file.
- Dollar figures use API list prices. On a subscription they are a proxy for usage.
- Tool-result and prefix sizes are estimated at 4 characters per token. Billed totals use exact usage fields.
- Adaptive trim is lossy. It collapses consecutive lines that differ only in their numbers, which can hide a table of numeric results. The full text is always saved, and the trimmed result says where.
- The script-built handoff note lists what was asked, which files changed and the last answer, and says where the old transcript is so a fresh session can search it. It does not itself capture reasoning. The warm-cache note option exists to cover that: the agent writes the reasoning while it is cheap to do so. That option costs a little on every reminder and has not been measured.
- Prices are hard-coded in `scripts/cost_anatomy.py` for four models, checked 2026-11-14.

## License

MIT
