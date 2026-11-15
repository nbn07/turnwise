---
name: turnwise
description: Measure and reduce what Claude Code sessions cost. Shows where the money went (cache writes, cache reads, output, cache rebuilds after idle gaps or model switches), what fills the fixed prefix every request re-reads, writes a handoff note for starting a fresh session, and turns the turnwise guards on or off. Use whenever the user asks about token usage, cost, spend, their bill, why a session was expensive, cache misses, context size, which MCP servers or tools are costing them, whether to start a new session or keep going, or wants a handoff or summary to continue elsewhere, even if they don't say "turnwise".
---

# turnwise

The turnwise plugin already injects its working rules at the start of every session. This skill is the on-demand part: four scripts that read Claude Code's own transcripts. They are stdlib Python, make no model calls, and send nothing anywhere.

The scripts are in the plugin's `scripts/` folder, two levels above this file's base directory (`<base>/../../scripts/`). Run them with `python3`.

| The user wants | Run |
|---|---|
| Where the money went | `cost_anatomy.py` (all sessions on this machine) |
| What the fixed prefix is made of | `audit.py` (add `--model <id>` to price it for another model) |
| A handoff note for a new session | `handoff.py` (current project; writes `.turnwise/handoff.md`) |
| See or change settings | `config.py`, then e.g. `config.py guard on`, `config.py warm_note on` or `config.py trim on` |

## Reporting results

Lead with the largest avoidable cost and what to do about it, then the table. The scripts print more than most people want, so pick the lines that answer the question.

Keep these distinctions honest, because the numbers are easy to overstate:

- Billed totals come from exact usage fields. Tool-result sizes and prefix sizes are estimates at 4 characters per token. Say which is which.
- Prices are API list prices. On a subscription plan the dollars are a proxy for usage, not a charge.
- The audit shows which tool groups were never called in the recorded sessions. That is evidence, not proof, that one is safe to turn off. The user decides; the script changes nothing.
- A cache rebuild after an idle gap is only avoidable by starting a fresh session. Whether that is worth losing the old context is the user's call, so give both prices.

## The guards

- **Stale-session guard** (off by default): when a prompt arrives after the cache has expired and the session is large, it stops the prompt once, writes a handoff note, and shows the cost of resuming against starting fresh. Sending the prompt again resumes. Offer to turn it on when the report shows rebuilds after idle gaps.
- **Warm-cache handoff note** (off by default): in a large session whose cache is still warm, a reminder asks you to keep `.turnwise/handoff.md` up to date. When you see that reminder, write the note as it describes, with the exact first line it gives, because the script uses that line to recognise the note and keep it. Offer this option together with the guard: the guard is far more useful when a good note already exists.
- **Model-switch warning** (on by default): stops a mid-session model change once and shows what rebuilding the cache will cost.

- **Adaptive trim** (off by default): shortens large, noisy Bash and MCP results and saves the full text under `.turnwise/full/`. Offer it when the report shows large tool results. If a result in the conversation ends with a `[turnwise: shortened …]` line and the missing part matters, read the file it names.

Change them only when the user asks.
