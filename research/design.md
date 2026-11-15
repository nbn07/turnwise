# turnwise: design (v1, revised after architecture review)

Based on [cost-anatomy.md](cost-anatomy.md) (7 sessions, $25.07) and [landscape.md](landscape.md). Nothing here is built yet. Every "expected saving" is an estimate from the measured shares and a stated assumption. The benchmark replaces these with measurements.

## Positioning

Every existing tool rewrites **content**: what the agent reads or says. turnwise changes **behaviour**: how many requests the agent makes, what it lets into the context, and when a session should be restarted instead of resumed. No proxy, no binary, no account.

## Review outcomes (2026-11-14)

The review raised three blocking questions. All three are answered.

| Question | Answer | Evidence | Still to confirm |
|---|---|---|---|
| How do the rules become active in every session? | **Ship as a Claude Code plugin.** A session-start hook injects the rules. A skill alone cannot do it: the docs say "full skill content only loads when invoked" and document no always-on option | [Skills docs](https://code.claude.com/docs/en/skills), quoted verbatim by the fetch | Nothing |
| Can a hook stop a prompt and show the user a message? | **Yes.** The prompt-submit hook receives `transcript_path` and `prompt`. Exit code 2, or `decision: "block"` with a `reason`, stops the prompt before it reaches the model and shows the reason to the user. Session start on resume also receives `seconds_since_last_response`, `context_tokens`, `prompt_cache_likely_expired` and `estimated_cache_write_usd`. Hooks named `PreModelSwitch` and `PostModelSwitch` exist, and the first can block | [Hooks docs](https://code.claude.com/docs/en/hooks) | **Tested live on 2.1.325.** Session-start and prompt hooks fire from a plugin; a blocked prompt cost $0 with no API request. The resume fields (`seconds_since_last_response` and the rest) did **not** appear in the input, so the guard computes them from the transcript. `PreModelSwitch` could not be triggered in a headless run and is still unobserved |
| Do transcripts show what the prefix is made of? | **Yes.** Each session records the system blocks and every tool definition with its full text. In the sample: system prompt about 34k characters, 51–57 tools about 124k–145k characters. Built-in tools are about 75k of that; MCP servers are 50k–70k | `api-request-shape` entries in the local transcripts | Nothing |

Three things the checks changed:

- **The prefix audit is worth less than estimated.** Only the MCP part can be turned off: roughly 12k–17k tokens of a 74k opening context. The estimate drops from 8–10% to 3–4%.
- **Model-switch protection can be enforced**, not just advised, if `PreModelSwitch` behaves as documented.
- **The handoff note can be free.** A script can build it from the transcript (requests made, files changed, last answer) with no model call. A model-written note cost more than it saved at the sample's rate of one stale resume per 26 prompts, unless it rides along in an answer the agent was writing anyway.

The meter was also checked against Claude Code's own cost record in the transcripts. Totals agree within about 10% ($25.07 against roughly $27). Per-session figures differ for forked sessions, and Claude Code counts a few background Haiku calls the meter does not see.

## Packaging

One plugin, `turnwise`, installed with one command and removed with one command. Nothing is written outside the plugin and a `.turnwise/` folder in the project, which the installer adds to `.git/info/exclude` so it never reaches a commit.

| Piece | Mechanism | Runtime token cost |
|---|---|---|
| Session-start hook that injects the rules (under 600 tokens) | 1, 2, 5, 6 | About $0.01 per session on Opus 5.5. It pays for itself by saving one request |
| Prompt-submit hook: stale-session guard. **Off by default** | 4 | Zero. It runs before any request |
| Model-switch hook | 3 | Zero |
| Skill `/turnwise`: report, audit, handoff, switch the guard on or off | 7, 8 | Only when invoked |
| Tool-result hook: adaptive trim. Off by default | 9 | Zero. It only removes tokens |
| `cost_anatomy.py`, stdlib only | 7, 8 | Zero. Runs outside the session |

For Codex, Cursor and Gemini CLI, only the rules transfer: paste them into the agent's rules file. The hooks are Claude Code only.

## Mechanisms

| # | Mechanism | Driver (measured share) | What it does | Expected saving | Confidence |
|---|---|---|---|---|---|
| 1 | **Request economy** | Prefix re-read (17–21%), history re-read (9–12%) | Batch independent tool calls. Chain dependent shell steps. Decide what to look for before looking. No confirm-only calls | 5–10% if requests per task fall 20–30% | Medium. Claude Code already tells the model to batch, so there may be little room |
| 2 | **Bounded intake** | Growth writes (23%); tool results are 8% here | Size results at the source: search before reading, line ranges, counts, `head`, quiet flags. Bulk exploration (over about 10k tokens expected, only the conclusion needed) goes to a cheaper-model subagent that must return file paths and line numbers with its conclusion | 2–4% here; unmeasured on coding runs | Low |
| 3 | **Route by subagent, never by switching** | Rebuilds after a model switch (7%) | Cheap work goes to subagents. The switch hook stops a mid-session model change once and shows what it will cost. Repeating the command goes through | Up to 4% | Medium if the hook works as documented |
| 4 | **Stale-session guard** | Rebuilds after an idle gap (12%) | When a prompt arrives after the cache has likely expired and the context is over a threshold (default 80k tokens), the hook stops it once, writes a handoff note from the transcript, and shows two prices: resume, or new session from the note. Sending again resumes. The cache lifetime is read from the transcript, not assumed | 4–8% | Medium |
| 5 | **Output economy** | Tool-call arguments (~12%), prose (~6%), thinking (~6%) | Edit instead of rewriting files. One scripted change instead of many identical edits. No code repeated in prose. No recaps. Normal grammar. The report shows the effort level in use; the user decides whether to change it | 2–4% | Medium |
| 6 | **Stop-loss** | Retry loops (unmeasured) | After two failed attempts at the same fix, stop and re-plan or ask | Unknown | Unmeasured |
| 7 | **Prefix audit** | Fixed prefix (74k tokens; 17–21%) | Lists each MCP server and tool with its size and its cost per request. The user decides what to disable | 3–4% | Medium |
| 8 | **Meter** | — | Billing-weighted breakdown by driver, cache breaks by cause, effort level | Enables the rest | Working |
| 9 | **Adaptive trim** (built, off by default, not yet seen live) | Large tool results: 28 of 410 results held 61% of all tool-result tokens, about 5% of spend | A hook on tool results. Results under about 2k tokens, file reads, diffs and failing commands pass through untouched. Larger logs, JSON and web or MCP results are cut to a head, a tail and a count of what was dropped, with the full text saved to a file the agent can read. Decided once per result and never revisited, so the cache is not disturbed. If the agent fetches the full text often for one kind of result, trimming stops for that kind | 2–3% on this sample; unmeasured on coding runs | Low to medium |

**Combined estimate.** Interactive use like the sample: 12–20% with the guard switched on. Headless coding tasks: 5–15% from mechanisms 1, 2, 5 and 6 only, and near zero is possible.

## Behaviour or compression, decided per result

Behaviour acts before a tool call, when the agent chooses what to ask for. Compression acts after it, on what came back. turnwise uses whichever fits the result.

| Result | Approach | Why |
|---|---|---|
| Code reads, symbol searches, config checks | Behaviour (mechanism 2) | The agent knows what it wants and can ask for less |
| Build, test and install logs; large JSON; web pages; MCP results | Trim (mechanism 9) | The agent cannot predict the size, and most of it is noise |
| Code about to be edited, diffs, error messages, stack traces | Neither | The agent needs the exact text |
| Anything under about 2k tokens | Neither | Too small to be worth the risk |

What the hooks documentation says (verbatim text, fetched 2026-11-14, not yet tried live):

- A `PostToolUse` hook receives `tool_input` and `tool_response` and can return `updatedToolOutput`, which "only changes what Claude sees" and "also works for built-in tools". For a built-in tool the replacement must match the tool's result shape or it is ignored. Only Bash's shape is documented (`stdout`, `stderr`, `interrupted`, `isImage`).
- A `PreToolUse` hook can rewrite a tool's input with `updatedInput`.
- Claude Code already limits Bash: a successful result over roughly 30,000 characters is saved to a file with a 2,000-character preview, and a failing one is cut to a head-and-tail excerpt of roughly 10,000 characters.

Consequences for the build:

- For Bash, the trim only adds value between about 8,000 and 30,000 characters. Above that, Claude Code already does the job.
- The larger opportunity is web and MCP results, which have no such built-in limit in the pages read. In the sample, web fetches were more than half of the large-result tokens.
- Result shapes for Read, Grep, WebFetch and WebSearch are undocumented, so v1 of the trim covers Bash and MCP tools only, and passes everything else through.
- Three deterministic trims, no more: repeated or long log lines, long JSON arrays (keep the first items and the count), and long text (head and tail). No per-command filters; that is RTK's ground.

## Handoff note

Two sources, by design (added after the session test):

- **Written by the agent while the cache is warm** (option `warm_note`, off by default). In a session over the threshold, the prompt hook adds a short reminder asking the agent to keep the note current: goal, what is done, decisions and why, what is not done, next step, under 200 words. It asks again only after the context has grown by 20k tokens. This is the better note, and it is cheap only while the cache is warm.
- **Built by the script** when the guard fires or on request. If an agent-written note for the same session exists, the script keeps it and adds only what was asked and changed after it. Otherwise it builds the whole note from the transcript.

Why both: asking the agent for a note after the cache has expired costs a full rebuild, which is the cost the guard exists to avoid. The script covers that case for free, and the agent's note covers the reasoning the script cannot see.

Unmeasured: whether the agent reliably writes the note when reminded, and what each reminder costs (expected: about one extra request).

Details of the script-built note:

- Path: `.turnwise/handoff.md`. Overwritten each time, never appended. First line holds the timestamp and the session it came from.
- Built by script from the transcript: the user's requests in order, files created or changed, and the agent's last answer. Capped at about 600 tokens.
- A new session reads it only when the user asks to continue. The guard's message states the note's age.
- Risk: a fresh session knows less than the old one. Track B scores the follow-up task for correctness, not only cost.

## Kill criteria

Decided on the dev split, before the test split is touched.

- A rule stays only if removing it raises cost per solved task by at least 2%, with a 95% interval that excludes zero, and success rate does not fall.
- A hook mechanism stays only if it cuts its Track B scenario's cost by at least 10% and the follow-up task still passes.
- If the full rule set shows no saving on Track A, the rules are cut to whatever the ablation supports, and the headline claim comes from Track B.
- Adaptive trim stays only if removing it raises cost per solved task by at least 2%, and the agent re-fetches the full text for fewer than one in five trimmed results.
- Subagent delegation has its own ablation. If it raises requests per task or lowers success, it is removed.

## Benchmark

- **Track A, tasks:** as in the brief. Cost per solved task at equal success rate. Tests 1, 2, 5, 6, 9.
- **Track B, sessions:** replays of real events found in transcripts (a resume after expiry, a mid-session model switch, a heavy prefix), fixed before any tuning. Tests 3, 4, 7. Caveman's keep-warm is included as a competitor on the resume scenario.
- **Arms:** baseline; Caveman 4.0 voice-only and full; RTK default and with a pipeline; Ponytail; context-mode; turnwise; turnwise + RTK; ablations.
- **Before either track:** a 5-task baseline with no tool, to learn whether mechanisms 1 and 5 have room to work.

## Changes from the brief

| Brief | Change | Why |
|---|---|---|
| A skill | A plugin that contains a skill | Rules must be active from the first request; a skill body loads only when invoked |
| Model routing rubric | Subagents only, with a hook on model switches | A mid-session switch rewrote 56k–117k tokens each time |
| "Know when to `/compact`" | Script-built handoff note and a new session | After expiry, compaction re-processes the whole context at full input price |
| Session read ledger | One line in the rules | Zero re-reads of unchanged files in the sample |
| Warnings for editing memory files or toggling tools | Dropped | Every cache break in 309 requests was an idle gap or a model switch |
| "Output is the smallest lever" | Output economy aimed at tool-call arguments | Output is 24% of spend; arguments are twice the prose |

## Risks that remain

- **The claim may be narrow.** Caveman's Auto claims 54% and Ponytail 26%. turnwise may not beat them on Track A. The report will say whichever is true.
- **One user's seven sessions.** The drivers may differ for heavy coding use.
- **Hook behaviour is documented, not yet observed.** If a hook does not behave as described, its mechanism falls back to advice in the rules, and its estimate falls with it.
- **The guard interrupts the user.** It is off by default, has a threshold, and never blocks the same prompt twice.
