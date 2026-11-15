# Landscape: token-cost tools for coding agents

Checked 2026-11-14; citations re-checked against the original pages on 2026-11-15 (see "Verification status" at the end). Star counts and README quotes come from the GitHub API on that date. "Vendor" means the number is the project's own; "independent" means someone else measured it. I read search-result summaries of the blog posts and the arXiv paper, not the full texts, so those rows are marked **summary only**.

## The brief's table was out of date

The brief describes Caveman as an output-only skill and RTK as a Bash-only proxy. Both were true early in 2026. Neither is true now. The two leaders have grown into multi-layer suites that already cover most of the "gaps" the brief planned to exploit.

| Tool | Stars | What it does today | Vendor claim | Independent result | Status of the brief's row |
|---|---:|---|---|---|---|
| [Caveman](https://github.com/juliusbrussee/caveman) v4.0 | 120.0k | Six parts: terse voice; "Read less" (compresses logs, JSON, CSV, test output); "Auto" (picks model and effort per request, needs a free account); "Blocks" (reusable scripts); cache keep-warm; web page compression | Voice: 63 → 20 tokens on one example. Read less: 33.2% fewer input tokens over 54 runs. Auto: 54% cheaper than Opus 5.5 at xhigh, 43.7% vs 44.3% solved, run half finished | JetBrains, 86 paired tasks: 8.5% fewer output tokens, no quality loss (p = 0.82) | **Corrected.** No longer output-only. Its own README says that against a plain "Answer concisely" baseline the voice cuts 3% more at the median, and the rules cost about 1,160 input tokens |
| [RTK](https://github.com/rtk-ai/rtk) | 86.6k | Bash output compressor by default. "Pipelines" add: compression of Read/Grep/Glob results (Claude Code), big file reads handed to a cheaper model, a proxy that trims API traffic without breaking the cache, terse output | "Up to 90% less command output". Best listed pipeline: 20.2% lower total cost in its author's benchmark | JetBrains: median task cost 7.6% **higher** at low effort, 0.1% higher at high effort. PointFive paper (below) | **Corrected.** Read/Grep/Glob are skipped only "out of the box". README now states that a 90% cut in command output is not a 90% cut in cost |
| [headroom](https://github.com/headroomlabs-ai/headroom) | 79.7k | Library, proxy and MCP server that compresses tool output, logs, files, RAG chunks | "20% fewer tokens for coding agents, 60–95% for JSON"; 21–57% on four agent scenarios | codepointer replay: fired on 45% of payloads, median 25% reduction when it fired (**summary only**) | Roughly confirmed. The "~50%" figure belongs to the separate headroom-desktop app |
| [pxpipe](https://github.com/teamchong/pxpipe) | 7.8k | Proxy that renders text context as images | 59–70% lower bill | None found | **Narrowed.** Its README says the headline holds for `claude-fable-5` only. Opus 5.5 and Fable 5.1/5.2 are "gist only", and Sonnet 5.5 and Haiku 5.5 are unsupported |
| [Ponytail](https://github.com/DietrichGebert/ponytail) v5 | 190.8k | Skill that makes the agent write only the code the task needs; cost band and dashboard | −53% code, −45% tokens, −26% cost, −41% time (39 tasks, Opus 5.5, 5 runs each) | JetBrains tested it on 80 paired tasks; I could not find the numbers. **Unverified** | **Corrected.** The brief's "~22% tokens" is an older version's figure |

### Newer or missing from the brief

| Tool | Stars | What it does | Claim (vendor, unverified) |
|---|---:|---|---|
| [claude-mem](https://github.com/thedotmack/claude-mem) | 117.1k | Captures a session, compresses it, injects relevant parts into later sessions | No cost figure checked |
| [context-mode](https://github.com/mksglu/context-mode) | 34.1k | Keeps tool output out of the context; sandbox plus local full-text search | "99% fewer bytes in context" |
| [Chisle](https://github.com/JayPokale/Chisle) | 1.0k | Terse prose + YAGNI code + tool-output compression in one package | Publishes the runs it loses |
| [token-optimizer-mcp](https://github.com/ooples/token-optimizer-mcp) | 0.6k | Tool-output compression, memory, quota pacing | Same SWE-bench tasks at 0.71× the cost |
| [tokenwar](https://github.com/oratelecom/tokenwar) | 0.07k | Installs six of the above as one stack | None |

## Independent evidence on what actually lowers the bill

- **PointFive, "Token Reduction Is Not Cost Reduction"** ([arXiv 2607.12161](https://arxiv.org/abs/2607.12161), July 2026, about 2,900 billed Claude Code runs; **summary only**). The most aggressive compression arm cut tool-output tokens by 38.4% and **raised** billed cost by 6.8% (95% CI +2.8% to +11.3%). Per-task token reduction barely predicted cost change (r = 0.15). Prompt-cache traffic was about 80% of the real bill. Compression made the agent take extra steps, and on a Go subset it lowered task completion. The authors recommend success-adjusted billed cost as the metric.
- **JetBrains** ([Caveman](https://blog.jetbrains.com/ai/2026/07/speak-to-ai-agents-like-cavemen-tosave-tokens/), [RTK](https://blog.jetbrains.com/ai/2026/07/rtk-claude-code-token-savings/), [Ponytail](https://blog.jetbrains.com/ai/2026/07/ponytail-skill-claude-tested/); **summary only**). Paired A/B on SkillsBench. Results are in the table above.
- **codepointer replay** ([post](https://codepointer.substack.com/p/cutting-llm-token-costs-with-rtk), June 2026; **summary only**, via [Capital & Compute](https://capitalandcompute.net/blog/claude-code-token-saving-tools-rtk-headroom-caveman/)). 614M tokens, $926 bill. RTK + headroom + Caveman together saved about $34 (3.7%). Output was about 29% of the bill. 78% of tool-output tokens came through native tools, almost all Read. A Hacker News summary gives RTK alone as $4.96.
- **Quesma** ([post](https://quesma.com/blog/does-rtk-make-ai-coding-cheaper/)): a $1,500 benchmark that reportedly found no saving from RTK. I saw the headline only. **Unverified.**

### A claim in the brief that does not hold

The brief says output is "reportedly only ~0.6–2.5% of total spend" ([Implicator](https://www.implicator.ai/caveman-claude-code-skill-cuts-output-20-your-bill-barely-notices-2/)). The codepointer replay puts output at about 29%, and my own measurement in [cost-anatomy.md](cost-anatomy.md) puts it at 24%. The low figure probably comes from older pricing, where cache reads cost 0.1× input. On the 5.5-generation models they cost 0.05×, which makes output a larger share. Treat output as a real lever, not a rounding error.

## What this means for turnwise

1. **"Covers what RTK and Caveman miss" is no longer a position.** Read/Grep compression, cheap-model reads, model routing and cache keep-warm all ship in one or both leaders.
2. **The open ground is behaviour, not compression.** Every tool above rewrites what the agent reads or says. None changes how the agent works: how many requests it makes, when a session is resumed or restarted, whether a model switch throws away the cache. The independent studies say compression often fails precisely because the agent's behaviour shifts to compensate.
3. **Honest measurement is itself a differentiator.** Vendors report token reduction on the surface they touch. The independent work all reports cost per task, and the numbers disagree with the vendors. A skill that ships with a billing-accurate meter and success-adjusted results stands apart.
4. **Zero install is a real edge.** The leaders now need a binary, a proxy, or an account. A plain skill file plus an optional stdlib script does not.
5. **Benchmark arms need updating.** Compare against Caveman 4.0 (voice only, and full suite), RTK default, and RTK with a pipeline. Ponytail and context-mode are larger than headroom by adoption or relevance and deserve arms too.

## Verification status (2026-11-15)

Each cited claim was checked against its original page where the page could be fetched.

| Source | Status | Notes |
|---|---|---|
| PointFive paper, arXiv 2607.12161 | **Confirmed from the paper** | 38.4% fewer delivered tool-output tokens and +6.8% billed cost are in the abstract. Cache creation and reads were about 87% of reconstructed cost (about 80% of the actual bill). 5,493 billed executions in total; the main campaign was 2,908 runs. The paper's wording for its metric is "success-adjusted end-to-end cost". The +2.8% to +11.3% interval was seen only in a summary of a part of the paper not read in full |
| codepointer replay | **Confirmed from the post** (now at codepointer.dev) | 614M tokens and $926.31 of baseline spend; the three tools saved 2.8%, 0.5% and 0.4%, 3.7% combined. The post gives percentages, so "$34" is a derived figure, not a quote. Its rtk and caveman figures were estimated, not replayed. Output was 29% of spend; 78% of tool-output tokens went through native tools; headroom fired on 45% of payloads with a median 25% reduction |
| JetBrains posts on Caveman, RTK and Ponytail | **Not verified** | All three pages refused automated fetching. The Caveman figures (86 paired tasks, 8.5% fewer output tokens, p = 0.82) also appear in Caveman's own README, which was read directly. The RTK figures (+7.6% and +0.1% cost) and anything about Ponytail rest on search summaries only. Read the posts yourself before repeating those numbers |
| Star counts and README quotes | Read directly through the GitHub API on 2026-11-14 | They change daily |
