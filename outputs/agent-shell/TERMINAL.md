# Tiled terminal environment

**Future desktop:** The [native windowing specification](../agent-os-windowing-specification.md) adopts the terminal's shared-control principles and extends them to typed native surfaces and graphical workspace composition. This guide describes the terminal implementation only.

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
| **i** / **x** | Disk-inspection shortcut / stop selected core or broker job |
| **X** | Choose active work or a proposal to stop across activities |
| **Y** | Stop all work in this activity, with confirmation |
| **q** | Leave the client; jobs continue |

The input line supports arrow keys, Home/End (or Ctrl-A/Ctrl-E), Backspace/Delete, Ctrl-U, Enter to submit and Escape to cancel. Questions can extend beyond the visible width.

Each activity restores its splits, tile contents and view modes when reopened. On narrow terminals the rail hides; if all tiles cannot fit, the focused tile fills the available area. Tab still accesses the other tiles, and widening the terminal restores the arrangement. The shared layout service stores arrangements and the last 20 undo snapshots in `/var/lib/agent-os-layout/state.sqlite3`. Existing `layouts-v1.json` arrangements are imported once per activity. Theme, sidebar and scroll preferences remain in `~/.local/state/agent-os/layout-client.json`.

Tiles display conversations and job output. Interactive PTY jobs use full-screen attachment through the host terminal’s emulator; **I** attaches the selected terminal job. Explicit commands retain the existing core's permissions; agent commands use the separate system broker. **x** stops the job bound to the selected tile. **o** offers core and broker jobs in this activity; the work-list view includes retained live work across activities. **X** chooses any active job or pending proposal to stop, including work in a removed activity. **Y** stops all work in the current activity and rejects its proposals. Stopping one conversation worker retains its separate broker commands unless you explicitly stop them or the activity. The removal dialog offers either retention or stopping all work before removal.

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

## Direct work controls

Press **X** or choose **Stop or reject any active work** in the actions menu.
The menu lists active core and broker jobs and pending proposals across activities,
including removed activities. **x** stops the selected tile's job. **Y** offers an
activity-wide stop with confirmation. These controls work without a model.

`agent-os jobs [ACTIVITY_ID]` lists both supervisors with source, activity and origin.
`agent-os logs broker:JOB_ID --follow` observes broker output; numeric core job
references still work. `agent-os stop broker:JOB_ID` stops one broker job, and
`agent-os stop-activity ACTIVITY_ID` stops core/broker activity work and rejects
pending proposals. A stop reports success after job states settle; incomplete
stops produce an error. New explicit requests can start work afterward.


## Interactive terminals

Press **R** and enter an absolute command such as `/bin/bash` to create a supervised terminal in the current activity. **I** reviews any pending approval with the exact command and its interactive root authority; after approving, press **I** again to attach. **o** can reopen an existing terminal job. These controls work without model inference. Original **r** commands remain noninteractive core jobs.

While attached, keyboard input—including arrows, function keys, Unicode, Ctrl-C and Ctrl-D—goes to the application. Terminal size changes reach its controlling PTY. **Ctrl-]** detaches and returns to the dashboard; the program keeps running. Use **x**, **X** or **Y** after detaching to stop work. Ctrl-C has ordinary terminal behavior: it signals the foreground process and may leave an interactive shell running. Closing a tile or leaving the dashboard retains the session.

From the ordinary guest shell:

```sh
agent-os terminal 12 -- /bin/bash
# If approval_required, review the returned command and approve its exact ID:
sudo agent-os-broker approve JOB_ID
agent-os attach broker:JOB_ID
agent-os stop broker:JOB_ID
```

Terminal sessions run with the broker’s root authority and existing resource/lifetime limits (24 hours by default). They accept human input with effects beyond their initial command; this is a direct local control, unavailable to the AI/core service identities. It is not a multi-user security boundary against admitted root programs. Attached programs emit native terminal escapes, as ordinary interactive programs do; tile/log views continue stripping process escapes.

One client controls input at a time. Clean detachment releases control immediately; after a lost connection its lease expires within 15 seconds and the display client is cleaned up. A private tmux server in the supervised job retains the current normal/alternate terminal screen, cursor, colors, Unicode cells and application modes. Every attachment creates a fresh display client at the current terminal size, restoring the screen without asking the application to redraw. If the display transport falls behind its bounded buffer, it also creates a fresh display instead of replaying a partial escape sequence. The command, including an editor’s unsaved buffer, continues running throughout. tmux shortcuts and its status bar are disabled.

Screen state is live job state, not unlimited scrollback or a disk checkpoint. Raw job logs still retain the first 256 KiB, independently of screen rendering, and live display continues after that cap. The broker retains at most 32 recently finished transport records; completed jobs expose their saved logs rather than reopening a dead terminal. Broker/VM restarts interrupt sessions and preserve their job records/logs without replaying commands.

`tests/terminal_screen_guest.py` verifies screen restoration after heavy output, colors/Unicode/cursor modes, connection loss, detached resize, an actual vi editing session, exact raw logs and command exit status. `tests/terminal_guest.py` checks real controlling PTYs, prompts, Unicode, resize, Ctrl-C, reconnect, output beyond the saved-log cap, cancellation and restart. `tests/interactive_terminal.py` exercises dashboard creation/approval/attachment, return to the dashboard, CLI reconnection and a full-screen curses application over real SSH.
