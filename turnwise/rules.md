# turnwise: working rules for cost

Each request re-sends the whole conversation, and everything a tool returns is paid for when it enters the context. So cost follows the number of requests you make and the size of what you let in. These rules never justify skipping a check the task needs.

- **Fewer requests.** Decide what you need before you look. Send independent tool calls together in one message. Chain dependent shell steps in one command. Skip calls that only confirm what a tool result already told you, such as reading a file back after a successful edit.
- **Small results.** Ask for the part you need: search first, then read that line range. Cap command output with counts, `head`, `tail` or quiet flags. Don't read a file again unless it has changed.
- **Delegate bulk reading.** When a question needs more than about 10k tokens of reading and only the conclusion matters, give it to a subagent on a cheaper model, and ask it for file paths and line numbers with its conclusion. Never change this session's own model for that: a switch rebuilds the whole cache.
- **Lean output.** Change files with targeted edits, not rewrites. For the same change in many places, use one scripted command. Don't repeat in prose the code that is already in a tool call or diff, and don't recap what the user can see. Write normal, complete sentences.
- **Stop-loss.** After two failed attempts at the same fix, stop. State what you know, then re-plan or ask.
