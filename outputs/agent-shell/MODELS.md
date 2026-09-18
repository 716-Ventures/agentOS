# Models and measured usage

Press **p** in the terminal, or choose **Models and usage** from Space / Actions.
The panel opens to the right of the work tiles and updates automatically. Tab returns focus to work while keeping the panel open; p closes it and restores the workspace width. Arrow keys and Page Up / Down scroll; Esc returns
to the same work. `agent-os models` returns the same snapshot as JSON.

The view separates configured models and their roles from measured requests.
Configured means credentials are present, not that the provider is currently
reachable. Jev's selected alias and most recently served version are shown
separately. Historical model rows remain after a configuration change.

Telemetry begins when this version is installed. Each actual inference HTTP
attempt is counted, including retries and additional tool-planning rounds.
Catalog lookups, status views, and skipped/cached Jev advisories do not count.
Counters include responses, errors, HTTP 429s, in-flight attempts, interrupted
attempts recovered after restart, provider-reported input/output/total tokens,
and the last attempt's latency and timestamp. Response counts are transport
results, not claims that the model's answer was valid or a system task succeeded.
Missing usage stays unknown, with coverage reported for each token counter.
No estimated prices, billing totals, or credit balances are presented.

The assistant persists aggregate counters in its private state directory and
atomically publishes a credential-free, group-readable snapshot under
`/run/agent-os-ai/model-usage.json`. This keeps the panel available during a
long-running agent turn without queuing behind the assistant's request socket.
Telemetry records no prompts, tool arguments, credentials, or response content.
Failures to record telemetry do not block inference. Reopening the terminal
loads the updated client; restarting the assistant retains usage history.

Validation: 39 unit tests; actual Gateway and Jev requests; developer-user access
to the published snapshot; SSH PTY checks at 140 and 50 columns, scrolling, light
and dark themes, and returning to the existing conversation without new work.
