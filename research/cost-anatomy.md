# Cost anatomy: where the money goes in real sessions

Measured 2026-11-14 with [cost_anatomy.py](../turnwise/scripts/cost_anatomy.py) on every Claude Code transcript on this machine. The raw per-session output is not published, because it names private projects.

```bash
python3 turnwise/scripts/cost_anatomy.py
```

## Sample, and its limits

- 7 sessions, 309 API requests, 128 user prompts, **$25.07** at API list price.
- Prices from the [official pricing page](https://platform.claude.com/docs/en/about-claude/pricing) on 2026-11-14 ($ per million tokens: input / 5-minute cache write / 1-hour cache write / cache read / output). Opus 5.5: 4 / 5 / 8 / 0.20 / 20. Sonnet 5.5: 2 / 2.50 / 4 / 0.10 / 10. Fable 5.2: 8 / 10 / 16 / 0.20 / 40. Haiku 5.5: 0.10 / 0.125 / 0.20 / 0.01 / 0.50.
- **This is one person's desktop-app usage: research, writing, some coding.** It has only 15 `Read` calls and no `Grep` loop of any size. It says little about long autonomous coding runs. The read-discipline and failure-loop questions cannot be answered from it.
- Forked and resumed sessions repeat earlier requests in their transcripts. The script counts each request once.
- Tool-result sizes are estimated at 4 characters per token. Billed totals use the exact usage fields.

## Spend by billing category

| Category | Tokens | $ | Share |
|---|---:|---:|---:|
| Cache writes | 1,590,470 | 11.57 | **46%** |
| Cache reads | 43,541,841 | 7.30 | **29%** |
| Output | 323,447 | 6.04 | **24%** |
| Uncached input | 816 | 0.00 | 0% |

Claude Code writes its cache at the 1-hour rate here (99% of write tokens), which is 2× the input price. Reads are 0.05× on Opus 5.5. So one token entering the context costs as much as 40 later requests re-reading it.

## Spend by driver

| Driver | $ | Share | How it was measured |
|---|---:|---:|---|
| New content written to cache as the conversation grows | 5.82 | 23% | Cache writes on requests where the earlier prefix was still cached |
| Fixed prefix re-read on every request | ~4.3–5.2 | 17–21% | The session's opening context (system prompt, tool schemas, memory) × number of requests. Median opening context: **74,119 tokens** before any work. The range is because forked sessions overstate the opening size |
| Cache rebuilt after an idle gap | 2.92 | 12% | 5 requests where a prefix already in context was written again after a pause. Every gap was over 2 hours |
| Cache rebuilt after a model switch | 1.65 | 7% | 3 requests, same test, different model from the previous request |
| Conversation history re-read | ~2.2–3.0 | 9–12% | Cache reads beyond the fixed prefix |
| Output: tool-call arguments (edits, file writes, commands) | ~2.9 | ~12% | Non-thinking output split by character count |
| Output: thinking | ~1.5 | ~6% | `thinking_tokens` from usage |
| Output: visible prose | ~1.6 | ~6% | Same split |
| First request of each session | 1.25 | 5% | Cache write on request 1 |

Tool results specifically (a subset of the first and fifth rows): $2.12, **8%** of spend. Bash is 55% of that, Read/Grep/Glob 10%, web search and MCP tools the rest.

Other figures: 2.4 requests per user prompt overall (1.6 to 4.7 by session). Median context per request was 99k to 145k tokens. 71% of spend was on Opus 5.5, 17% Sonnet 5.5, 12% Fable 5.2. No file was read twice unchanged. One whole-file read exceeded 2,000 tokens.

## What the data says about the six hypotheses

| # | Hypothesis | Verdict on this sample |
|---|---|---|
| 1 | Number of turns drives cost | **Supported, for a different reason than assumed.** Each request re-reads a 74k-token prefix. That fixed toll is 17–21% of spend. Re-reading the conversation itself is only 9–12% |
| 2 | Persistent context is paid for every turn | **Mostly refuted at current prices.** The carry cost is small because reads are 0.05×. What costs money is the first write at 2×. Keeping content out of context still pays, but through the write, not the carry |
| 3 | Cache breaks | **Supported. Largest clearly avoidable item: 18%.** Idle expiry 12%, model switches 7% |
| 4 | Wasted exploration | **Not measurable here.** Too few reads. Needs coding-task runs |
| 5 | Expensive model on cheap work | **Not measurable here.** Opus is 71% of spend, but nothing in a transcript says which requests were easy |
| 6 | Output is the smallest lever | **Refuted.** Output is 24%. Visible prose, the part a terse-voice skill touches, is about 6%. Tool-call arguments are about 12% |

## Two findings that change the design

**Model switching is expensive.** Changing model mid-session rewrote 56k to 117k tokens each time. The brief's "model routing" mechanism would cause exactly this if it meant switching the session's model. Routing has to happen through subagents, which have their own small context, never by switching the main session.

**Resuming a stale session is expensive.** Coming back to a 130k–170k-token session after the cache expired cost $0.27 to $1.08 per resume on Opus. Starting a new session with a short handoff note would have written about 74k tokens instead. No competitor addresses this as agent or user behaviour. Caveman 4.0 keeps the cache warm during pauses, which helps for short breaks and costs money for long ones.

## What is still unknown

The coding-agent picture: read and search waste, retry loops, and how much a 20-plus-turn autonomous run differs from this sample. The independent studies in [landscape.md](landscape.md) suggest cache traffic is about 80% of the bill there, against 75% here, so the shape is probably similar, but that is an inference. The benchmark's baseline arm will measure it directly, and the same script reads its transcripts.
