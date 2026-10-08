# General system broker — Agent OS 0.5

The conversational agent uses general execution, filesystem and job-control tools to work across the Linux guest. Ling plans; Jev assesses exact command effects, request alignment and contextual authorization; the broker validates and applies those assessments. See [EFFECTS.md](EFFECTS.md) for the policy.

## Authority

Assessed commands run as **root**, in a transient systemd service. Activity directories under `/var/lib/agent-os-workspaces/<ID>` organize work and supply the default working directory. They are not sandboxes. The original explicit-command core retains separate workspaces under `/var/lib/agent-os-runtime/workspaces/<ID>` and runs under the restricted core identity.

The assistant service holds provider credentials under its own identity. Assessment runs under that identity rather than exposing credentials in tool arguments. However, broker-launched root commands are not restricted from credentials, private state, control sockets or other activities. Service identity separation is not a security boundary against an admitted root command. Effect assessment is probabilistic, and this single-user development guest is not a hardened multi-user system.

Commands use an absolute executable and an argument array. Shell syntax requires explicitly choosing `/bin/sh -c`. Model tools cannot supply systemd properties, execution identities or an approval UID. Working directories may be anywhere on the guest. The host Mac is a separate authority boundary.

## Execution and review

Routine actions execute automatically when assessment passes. Agent requests also require confident task alignment. Explicit current user instructions may cover exact harmful effects; otherwise uncovered harmful effects produce a review proposal. Uncertain, low-confidence, unavailable or malformed assessments require further inspection. After inspection, `request_confirmation` can create a proposal if uncertainty remains. Unknown command names are not automatically refused.

A proposal records exact argv, cwd, activity, lifetime, authority, requester identity and, when supplied, the SHA-256 and byte count of stdin. Review and control it locally:

```sh
agent-os-broker list
agent-os-broker poll JOB_ID
sudo agent-os-broker input JOB_ID
sudo agent-os-broker approve JOB_ID
agent-os-broker cancel JOB_ID
```

Approval requires UID 0 from Unix peer credentials, rather than a request field. The terminal offers locally handled approval replies. Root execution means a previously admitted root program also has administrative authority; peer credentials do not prove that a request came from a human. Approval binds the command arguments and working directory, not immutable copies of scripts or other external inputs. Inspect those inputs when reviewing a proposal.

Pending proposals survive restart without execution. Identical pending requests reuse one proposal. Already active identical noninteractive background requests reuse their job; new interactive terminal requests create separate sessions. Both paths match activity, normalized argv, resolved working directory, execution authority, foreground/background mode, deadline, stdin hash and terminal mode. A foreground job or a job with a different lifetime cannot satisfy a background retry. Different settings create a separate assessed operation; they do not extend an existing unit’s lifetime.

Commands may receive a single UTF-8 stdin payload of up to 64 KiB. Assessment receives the full input as untrusted data; authorization and retry identity bind its exact byte hash. Input is stored in private broker records and omitted from ordinary job views. The root-only `input` command exposes it for review. Input is fed concurrently with output draining, and closed afterward; this is not an interactive session.

## Jobs and direct controls

Four broker jobs may run concurrently. Each has a unique ID and systemd cgroup, a foreground deadline of at most 600 seconds or a background lifetime of at most 86400 seconds, a 256 MiB memory limit, a 64-task limit, and up to 256 KiB retained output. Output is drained after that cap. Poll returns byte offsets, exit codes and status. Cancellation stops the service cgroup, including ordinary descendants that start a new session. Cancellation received before launch prevents spawning the command.

Core and broker jobs share the terminal work list, tile picker and `agent-os jobs` output. Core jobs retain numeric IDs; broker surface bindings and CLI references use `broker:JOB_ID`. The work-list view includes live work and proposals across activities, including removed activities. Broker jobs record the originating conversation and core worker when launched by the assistant. This origin is descriptive metadata, not an authorization boundary. All active jobs and proposals remain listed even when older than the recent-history window.

**x** stops the selected core or broker job. **X**, or **Stop or reject any active work** in the actions menu, lists active core/broker work and proposals across activities. **Y** offers an explicit activity-wide stop; the CLI equivalent is `agent-os stop-activity ACTIVITY_ID`. It cancels core callers, stops broker cgroups, rejects pending proposals and waits for terminal job states before reporting success. It reports incomplete stops as errors. Each stop advances a durable activity generation, revoking queued assistant requests and commands still being assessed. A second revocation after core callers exit closes their startup race. New explicit requests can start work using the current generation.

Stopping one conversation worker does not implicitly stop its separate broker commands. Closing a tile retains work. Removing an activity defaults to retaining files and work; the removal menu also offers **Stop all work, then remove from sidebar**. Other activities and intentionally retained background work continue. An already sent provider request may finish before the assistant observes revocation; subsequent recorded steps and launches are rejected.

Broker records/logs live under `/var/lib/agent-os-broker`; conversations and traces live under `/var/lib/agent-os-ai`. Before accepting requests after restart, the broker stops unfinished units and checks systemd’s active state, process IDs and cgroup task count. It marks a job interrupted only after confirming the unit is stopped, records its completion time, and never replays it. If stopping or verification fails, recovery fails and the API remains unavailable rather than reporting that live work ended. Pending proposals retain their identities and remain unexecuted. Inspect recovery failures with `journalctl -u agent-os-broker`. Core and broker retain separate supervisors and native IDs; the terminal projects both into one work view. Interactive PTY jobs use the same supervisor and cancellation/restart rules; continuous subscriptions remain future work. See [interactive terminal controls](TERMINAL.md#interactive-terminals).

## Guarded files and recovery

File tools read regular UTF-8 files up to 64 KiB. The assistant collects every broker output page before parsing the file result, preserving full content and the hash. Byte-offset polling retains incomplete UTF-8 suffixes for the next page so Unicode characters are not corrupted at chunk boundaries. Helper output uses UTF-8 with JSON escapes for undecodable filename bytes. If JSON escaping expands a result past the 256 KiB broker output cap, or the result is incomplete/malformed, the tool returns an explicit error rather than claiming it returned a complete file. Write content travels over bounded stdin with a small argument descriptor, so the 32,000-character argument limit does not reduce the supported file size. The helper verifies the input hash before editing. Writes require the current content hash or literal `missing` for creation. Replacements preserve previous bytes under `/var/lib/agent-os-file-backups`, use atomic replacement, and preserve the original owner and permission bits. Guarded writers serialize per resolved path, so two writers cannot both replace the same revision. Non-regular files are rejected without waiting for FIFO input. Failed replacements remove temporary files.

Arbitrary programs do not participate in those locks and can still race a guarded edit. Backups are prior content, not full metadata snapshots or automatic rollback. Arbitrary commands have no automatic recovery. System-wide snapshots and transactional configuration changes remain future work.

## Validation

Run the local Python unit suite and Rust tests described in [README.md](README.md). The Rust suite covers persistence, stale mutation rejection, reversible activity removal and restart reconciliation; Linux additionally exercises command results and cancellation.

`tests/broker_integration.py` must run inside a provisioned development guest. It exercises real root execution, OS-wide and cross-activity access, guarded files/backups, exit codes, output caps, deadlines, cgroup cancellation and root-only proposal approval. It may approve its documented harmless fixtures, write test files and create activities. It does not read credentials. `tests/broker_restart_guest.py` additionally restarts the broker around a root command with a detached child, checks both processes are gone, preserves an unapproved proposal, and verifies a second restart does not replay work or change retained evidence. It stops only its own fixtures, but restarting the broker also interrupts any other active broker work; run it on an idle development guest. Historical reports from the removed activity sandbox are not evidence of the current authority policy.

`tests/broker_reuse_guest.py` verifies distinct foreground/background units, distinct lifetimes and their actual systemd deadlines, and reuse of an identical background retry without another launch. It approves only its harmless sleep fixtures and cancels them afterward.

`tests/file_result_guest.py` checks complete ASCII, CJK and emoji content and hashes through real broker output and the assistant dispatcher. It uses explicit provider fixtures and approves only its harmless file reads; it does not test live model inference.

`tests/write_transport_guest.py`, run as root in the development guest, verifies 64 KiB ASCII, emoji and NUL writes and empty input through the assistant and real broker, exact hashes, prior-content backups, stale revisions, mismatched input and size limits. It also checks output-before-input execution for pipe deadlocks. It approves only its harmless fixtures and uses provider fixtures.

`tests/work_lifecycle_guest.py`, run as root on an idle development guest, verifies combined visibility, removed activities, origin metadata, broker surface bindings, activity cancellation including detached children, retained work in another activity and generation persistence across broker restart. `tests/work_lifecycle_terminal.py` runs from the host and exercises the real SSH terminal picker and stop controls. Both use harmless fixtures and clean up their running work.

Live model quality is evaluated separately. The retained Jev action set is a small regression sample, not a calibrated safety guarantee. Local tests do not establish systemd behavior or live provider quality.


## PTY transport

A local human login may request `execute` with `terminal: true`, bounded `rows`/`cols` and a background lifetime. Stored `stdin` and terminal mode are mutually exclusive. A private tmux server gives the command a controlling terminal and retains its screen. A tmux control client, server, application and descendants run within the same supervised systemd cgroup. The broker decodes control-mode output into the existing raw command log, continuously draining after its cap, and records the application’s exit status rather than the display client’s status. Terminal creation follows normal assessment and explicit approval when needed. Assessment includes terminal mode. Service identities `agentos` and `agentos-ai` cannot create or control PTYs.

The local client uses `terminal_attach` to obtain an exclusive 15-second renewable controller token, then `terminal_read` (raw base64 display bytes, byte cursor and explicit screen-reset flag), `terminal_write` (at most 4096 raw bytes, returns accepted count), `terminal_resize`, and `terminal_detach`. Reads renew the lease. Sizes are bounded to 500 rows × 1000 columns. Writes use nonblocking backpressure rather than holding the broker lock while waiting for the command. Input is delivered only to running jobs; cancellation revokes further input. Each attachment starts a fresh display client, which renders the current screen and terminal modes; no old output tail is replayed. Display buffering is capped at 256 KiB; a stale cursor replaces that client and returns `reset: true` with a new cursor. The client cancels any unfinished escape sequence and clears its display before consuming this complete rendering. Detached or expired display clients are closed and reaped while the command continues; the recording client is excluded from window-size decisions so detaching preserves the last application size. Screen history is disabled. At most 32 finished transport records remain; completed jobs use saved logs. Tokens, screen state and transports do not survive service restart. Existing byte-offset text polling and persistent capped logs remain compatible.

The screen keeper is the Debian snapshot’s tmux package, with its upstream licenses retained. Its [control-mode protocol](https://github.com/tmux/tmux/wiki/Control-Mode) supplies raw pane output independently of display clients. Configuration and sockets live in the broker’s private state directory; ordinary users access the job only through the broker.
