# Tiled terminal environment

The installed terminal client now supports up to six independent tiles per activity, a quieter conversation view, light/dark themes, editable input, and persistent layouts.

Exit the old client with **q**, then run `agent-os` again. No VM restart is needed.

| Control | Action |
|---|---|
| **a** / **r** | Ask Agent / run a command in the focused tile |
| **v** / **s** | Split side by side / split top and bottom |
| **Tab** / click | Move focus through tiles and the activities column |
| **+** / **−** | Grow / shrink the focused tile at its nearest split |
| **z** | Maximize the tile / restore the arrangement |
| **m** | Swap the focused surface with the next tile |
| **w** | Close the focused tile; its work continues |
| **u** | Undo the last structural layout change in this session |
| **o** | Choose existing work for this tile |
| **t** | Choose conversation, full output, history or work-list view |
| **↑/↓**, **PgUp/PgDn**, **e** | Scroll / page / follow the end |
| **[** / **]** | Previous / next activity |
| **n** / **b** | New activity / toggle activity rail |
| **T** | Switch light and dark themes |
| **Space** / **?** | Open the actions menu |
| **d** / **x** | Disk-inspection shortcut / stop selected core job |
| **q** | Leave the client; jobs continue |

The input line supports arrow keys, Home/End (or Ctrl-A/Ctrl-E), Backspace/Delete, Ctrl-U, Enter to submit and Escape to cancel. Questions can extend beyond the visible width.

Each activity restores its splits, tile contents and view modes when reopened. On narrow terminals the rail hides; if all tiles cannot fit, the focused tile fills the available area. Tab still accesses the other tiles, and widening the terminal restores the arrangement. The shared layout service stores arrangements and the last 20 undo snapshots in `/var/lib/agent-os-layout/state.sqlite3`. Existing `layouts-v1.json` arrangements are imported once per activity. Theme, sidebar and scroll preferences remain in `~/.local/state/agent-os/layout-client.json`.

These tiles display conversations and job output. They are not interactive PTY shell sessions. Explicit commands retain the existing core's permissions; agent commands use the separate system broker. **x** stops the selected core/conversation job, not every broker job it may have launched. Use the broker controls for those jobs.

Validation included real commands inside the Linux VM, both split orientations, resize, swap/undo, maximize/restore, long Unicode input with cancellation, narrow/wide terminal resizing, light/dark themes, actions-menu access and reopening the saved layout. Four layout/Unicode unit tests also pass. Preview PNGs render the actual captured SSH terminal grid using a host monospace font.


The agent now has `layout_snapshot` and `layout_change` tools. Try asking: “Split this activity side by side and show history in the new tile.” Both keyboard controls and agent requests update the same revisioned state. An active input editor blocks agent layout changes. Closing a tile keeps its job running. Free-model rate limits can still interrupt natural-language requests; direct controls remain available.


## Conversation and approval

Press Enter or `a` to reply in the selected tile. Conversation view keeps the activity’s latest 20 exchanges visible; PgUp/PgDn scroll through them. Tiles in the same activity share conversation context. The assistant retains up to 20 exchanges, bounded by the existing context-size limit.

Pending administrator operations appear with their exact command and operation ID. Reply `approved` when there is one pending proposal, or `approve FULL_OPERATION_ID` when there are several. The terminal binds that reply to proposals present when the reply editor opened and rechecks the selected operation before using local administrator authority. The model has no approval tool. A new proposal appearing mid-reply cannot inherit an earlier approval.

The result status remains visible even if the model is rate-limited. After approval the agent is asked to poll the existing operation and continue, not create another installation proposal. Local approval uses `sudo -n`; the development VM already grants its developer account passwordless sudo. Other deployments require an appropriate local authorization setup and show an error if approval is unavailable.

Verified with `tests/conversation_test.py` and an actual SSH PTY in `tests/conversation_terminal.py`: harmless administrator printf proposal, typed approval, successful execution, live agent follow-up and a second message retained in the same tile.


## Remove activities

Press `d` (uppercase `D` also works) or choose **Remove activity from sidebar** in the Space actions menu. Confirm the selected activity’s name or cancel. Removal retains files, conversation history, layouts and existing jobs; it does not cancel running work. New core jobs cannot start in a removed activity until it is restored.

Scriptable controls: `agent-os remove ID`, `agent-os removed` to list removed activities, and `agent-os restore ID` to restore one. Removing the final activity returns the terminal to its empty state; `n` creates a new activity.


Keyboard activity navigation: **F6** toggles between activities and work; **Left Arrow** focuses activities. **Up/Down** selects an activity, **Home/End** selects the first/last, and **Enter**, **Right Arrow**, or **Escape** returns to work. The focused list has an accent heading and navigation hints. At narrow widths focusing activities reveals the list. **d** removes the selected activity after confirmation; **i** inspects disk usage. Restart an already-open client with `q`, then `agent-os`, to load updated keyboard bindings.


An empty workspace accepts **Enter / a** directly: submitting the first question creates a Conversation activity and sends it to the agent. **n** only creates an activity label; its prompt explicitly says it does not send a message. The broker socket uses the existing `agentos` group so older console sessions can read proposals without refreshing supplementary groups. System approval still requires UID 0.


## Conversation presentation

Routine tool calls, broker IDs, logs and provider errors are summarized as short, friendly progress updates. The latest update is shown instead of a growing execution transcript. Answers are explicitly delimited from technical output. Full output retains commands and diagnostic details.

Approvals describe recognized package operations in plain language, with administrator access stated. Other operations retain their exact command so their scope is reviewable. Multiple pending actions are numbered: reply `approve 1` or `approve 2`; the number maps to the immutable proposal captured when the reply opened. Full IDs remain supported for scripts and older instructions. Final answers are instructed to report the outcome naturally, without internal IDs or timestamps unless requested.


## Provider availability

Gateway rate limits are reported as AI-service unavailability, not a busy local agent. On HTTP 429 the conversational provider retries once when the supplied numeric retry delay is at most ten seconds, then tries `poolside/laguna-s-2.1-free`. Both selected and fallback models must pass the live zero-pricing guard. Tool execution is not replayed by this retry logic. Non-rate-limit errors do not trigger retries. The fallback was itself rate-limited during live verification on September 17; successful fallback inference is not yet verified. Vercel’s error identified a free-tier request limit and provided no Retry-After header. Paid usage remains disabled.


The current VM now uses the explicitly authorized paid model `inclusionai/ling-3.0-flash`. Only that exact model is authorized for paid usage in provider configuration. It retains bounded rate-limit retries and does not switch models on exhaustion. Unapproved models still require the zero-pricing guard. Provider keys remain in the protected guest configuration.


## Selecting and copying text

Mouse reporting is off by default so the host terminal can select text with a drag and copy with its normal shortcut (Command-C in macOS Terminal). Press **M** to enable clickable in-app mouse controls; press **M** again to return to native selection. Keyboard navigation works in either mode. The setting resets to text selection when the client opens.


HTTP(S) URLs in tile content are underlined and emitted as OSC 8 terminal hyperlinks. Opening them is handled by the host terminal, preserving native selection and avoiding an attempt to launch a browser inside the Linux guest. Use the terminal’s link gesture (typically Command-click; macOS Terminal may require Command-double-click on the visible URL). Terminal hyperlink support varies. Only validated HTTP(S) targets are emitted; process-supplied terminal escapes remain stripped.


Routine assessed operations now run without approval, including system installations. Only destructive/disruptive proposals display approval controls. Unknown effects are returned to the agent for inspection. See [EFFECTS.md](EFFECTS.md) for supported operations and current limits.

## Models and usage

Press **p** for the live Models panel on the right of your work tiles, also available under Space → Models and usage.
It shows configured models and roles, measured requests and tokens, errors,
in-flight work, and latency. Esc returns to your work; arrows and Page Up / Down
scroll. `agent-os models` provides JSON. See [MODELS.md](MODELS.md) for accounting
and persistence details.
