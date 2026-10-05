# General system broker — Agent OS 0.5

The conversational agent uses general execution, filesystem and job-control tools to work across the Linux guest. Ling plans; Jev assesses exact command effects, request alignment and contextual authorization; the broker validates and applies those assessments. See [EFFECTS.md](EFFECTS.md) for the policy.

## Authority

Assessed commands run as **root**, in a transient systemd service. Activity directories under `/var/lib/agent-os-workspaces/<ID>` organize work and supply the default working directory. They are not sandboxes. The original explicit-command core retains separate workspaces under `/var/lib/agent-os-runtime/workspaces/<ID>` and runs under the restricted core identity.

The assistant service holds provider credentials under its own identity. Assessment runs under that identity rather than exposing credentials in tool arguments. However, broker-launched root commands are not restricted from credentials, private state, control sockets or other activities. Service identity separation is not a security boundary against an admitted root command. Effect assessment is probabilistic, and this single-user development guest is not a hardened multi-user system.

Commands use an absolute executable and an argument array. Shell syntax requires explicitly choosing `/bin/sh -c`. Model tools cannot supply systemd properties, execution identities or an approval UID. Working directories may be anywhere on the guest. The host Mac is a separate authority boundary.

## Execution and review

Routine actions execute automatically when assessment passes. Agent requests also require confident task alignment. Explicit current user instructions may cover exact harmful effects; otherwise uncovered harmful effects produce a review proposal. Uncertain, low-confidence, unavailable or malformed assessments require further inspection. After inspection, `request_confirmation` can create a proposal if uncertainty remains. Unknown command names are not automatically refused.

A proposal records exact argv, cwd, activity, lifetime, authority and requester identity. Review and control it locally:

```sh
agent-os-broker list
agent-os-broker poll JOB_ID
sudo agent-os-broker approve JOB_ID
agent-os-broker cancel JOB_ID
```

Approval requires UID 0 from Unix peer credentials, rather than a request field. The terminal offers locally handled approval replies. Root execution means a previously admitted root program also has administrative authority; peer credentials do not prove that a request came from a human. Approval binds the command arguments and working directory, not immutable copies of scripts or other external inputs. Inspect those inputs when reviewing a proposal.

Pending proposals survive restart without execution. Identical pending requests reuse one proposal. Already active identical background requests reuse their job. Both paths match activity, normalized argv, resolved working directory, execution authority, foreground/background mode and deadline. A foreground job or a job with a different lifetime cannot satisfy a background retry. Different settings create a separate assessed operation; they do not extend an existing unit’s lifetime.

## Jobs and direct controls

Four broker jobs may run concurrently. Each has a unique ID and systemd cgroup, a foreground deadline of at most 600 seconds or a background lifetime of at most 86400 seconds, a 256 MiB memory limit, a 64-task limit, and up to 256 KiB retained output. Output is drained after that cap. Poll returns byte offsets, exit codes and status. Cancellation stops the service cgroup, including ordinary descendants that start a new session. Cancellation received before launch prevents spawning the command.

In the terminal, **x** stops the selected core job. **X**, or **Stop or reject a broker job** in the Space actions menu, lists active broker jobs and pending proposals in the current activity. Selecting one directly cancels or rejects it without inference. Stopping a conversation worker does not implicitly cancel the separate broker jobs it launched. Closing a tile or removing an activity also leaves work running.

Broker records/logs live under `/var/lib/agent-os-broker`; conversations and traces live under `/var/lib/agent-os-ai`. Before accepting requests after restart, the broker stops unfinished units and checks systemd’s active state, process IDs and cgroup task count. It marks a job interrupted only after confirming the unit is stopped, records its completion time, and never replays it. If stopping or verification fails, recovery fails and the API remains unavailable rather than reporting that live work ended. Pending proposals retain their identities and remain unexecuted. Inspect recovery failures with `journalctl -u agent-os-broker`. Core jobs, broker jobs and layout bindings remain distinct identities. PTY attachment, interactive stdin, continuous subscriptions and a unified job projection are future work.

## Guarded files and recovery

File tools read regular UTF-8 files up to 64 KiB. The assistant collects every broker output page before parsing the file result, preserving full content and the hash. Byte-offset polling retains incomplete UTF-8 suffixes for the next page so Unicode characters are not corrupted at chunk boundaries. Helper output uses UTF-8 with JSON escapes for undecodable filename bytes. If JSON escaping expands a result past the 256 KiB broker output cap, or the result is incomplete/malformed, the tool returns an explicit error rather than claiming it returned a complete file. Writes require the current content hash or literal `missing` for creation. Replacements preserve previous bytes under `/var/lib/agent-os-file-backups`, use atomic replacement, and preserve the original owner and permission bits. Guarded writers serialize per resolved path, so two writers cannot both replace the same revision. Non-regular files are rejected without waiting for FIFO input. Failed replacements remove temporary files.

Arbitrary programs do not participate in those locks and can still race a guarded edit. Backups are prior content, not full metadata snapshots or automatic rollback. Arbitrary commands have no automatic recovery. System-wide snapshots and transactional configuration changes remain future work.

## Validation

Run the local Python unit suite and Rust tests described in [README.md](README.md). The Rust suite covers persistence, stale mutation rejection, reversible activity removal and restart reconciliation; Linux additionally exercises command results and cancellation.

`tests/broker_integration.py` must run inside a provisioned development guest. It exercises real root execution, OS-wide and cross-activity access, guarded files/backups, exit codes, output caps, deadlines, cgroup cancellation and root-only proposal approval. It may approve its documented harmless fixtures, write test files and create activities. It does not read credentials. `tests/broker_restart_guest.py` additionally restarts the broker around a root command with a detached child, checks both processes are gone, preserves an unapproved proposal, and verifies a second restart does not replay work or change retained evidence. It stops only its own fixtures, but restarting the broker also interrupts any other active broker work; run it on an idle development guest. Historical reports from the removed activity sandbox are not evidence of the current authority policy.

`tests/broker_reuse_guest.py` verifies distinct foreground/background units, distinct lifetimes and their actual systemd deadlines, and reuse of an identical background retry without another launch. It approves only its harmless sleep fixtures and cancels them afterward.

`tests/file_result_guest.py` checks complete ASCII, CJK and emoji content and hashes through real broker output and the assistant dispatcher. It uses explicit provider fixtures and approves only its harmless file reads; it does not test live model inference.

Live model quality is evaluated separately. The retained Jev action set is a small regression sample, not a calibrated safety guarantee. Local tests do not establish systemd behavior or live provider quality.
