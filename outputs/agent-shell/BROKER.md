> Current authority model: the agent operates across the Linux guest with root authority. Activity isolation described in historical sections below has been removed; see EFFECTS.md for the current policy.

> Updated authority policy: see [EFFECTS.md](EFFECTS.md). Earlier descriptions below of every system operation requiring approval are superseded by that policy.

# General system broker — Agent OS 0.4

The conversational agent now uses general execution and filesystem primitives. It can discover and run installed Linux tools to investigate networking, services, processes, storage and applications without a custom routing category or tool for each subsystem. Jev now assesses actions at runtime; see EFFECTS.md for the current decision path.

## Use it

Open `agent-os`, select an activity, and press **a**. Examples:

- “Inspect the network interfaces and default route. Don't change settings.”
- “What services have failed?”
- “Create a notes file in this activity, then read it back.”
- “Run a process that prints a timestamp every second, and show its output.”

The Gateway model receives seven tools: `execute`, `job_output`, `stop_job`, `list_jobs`, `read_file`, `list_directory`, and `write_file`. Execution accepts an argument array; shell syntax requires explicitly choosing `/bin/sh -c`. An executable must have an absolute path. The model can discover commands and compose them. File editing uses whole-file replacement with an expected content hash, plus a saved previous version; a patch is a read/edit/write sequence using those primitives.

The **d** disk shortcut remains available, but Ask no longer depends on the earlier kernel/disk-specific tool pair.

## Authority and isolation

Normal execution uses one dedicated Linux account per activity (`agentos-w<ID>`). Workspace files live under `/var/lib/agent-os-workspaces/<ID>`, separate from the original explicit-command core workspace. This is shown as the working directory in every broker result. Files created with the new agent tools are in this new workspace; existing activity files are retained in their original locations.

Each process runs in a transient systemd service with a read-only system, a writable activity workspace, private temporary storage, no privilege escalation, no capabilities, protected devices/kernel settings, and a limited view of other users' processes. Provider credentials, assistant/core/broker state and control sockets are inaccessible. Activity directories are mode 0700 and have different owners. Outbound networking is available; its remote effects are not made read-only by filesystem isolation.

These boundaries permit broad inspection, not unrestricted access to every byte. Private homes, credentials, some logs, and administrative mutations require different authority. Filesystem and process restrictions are enforced by Linux, not by classifying command text. A command named `cat` does not receive special trust, and a shell does not bypass the sandbox.

The broker service is a small root authority boundary. It launches commands through systemd with fixed normal-execution properties. Model-supplied systemd properties, users, environment variables, working directories, and approval identities are not accepted.

## Administrator operations

`execute` with `scope: system` creates an immutable command proposal. It does not execute. Review locally:

```sh
sudo agent-os-broker list
sudo agent-os-broker poll JOB_ID
```

The record includes the exact argument array, purpose, authority, working directory, timeout, and requester identity. If you approve that operation:

```sh
sudo agent-os-broker approve JOB_ID
```

Reject or stop an operation with:

```sh
sudo agent-os-broker cancel JOB_ID
```

Approval is accepted only from UID 0 as reported by the Unix socket, not from a request field. Normal agent processes cannot reach that socket or become root. An approved system operation runs as root in `/` and grants real administrative authority; it is not the normal sandbox. Approval binds the command arguments, not the contents of external scripts or files that command may subsequently use. Review those inputs when relevant. Pending proposals survive restart and do not auto-execute.

## Execution and records

Four broker jobs may run concurrently. Each has a unique ID, separate systemd cgroup, a 1–600 second foreground deadline or a background lifetime up to 86400 seconds, a 256 MiB memory limit, a 64-task limit, and up to 256 KiB of retained output. Output is drained after that cap. Polling returns byte offsets, exit codes and final status. The agent initially waits up to eight seconds, then can poll or leave a background job running. Cancellation stops the service cgroup, including ordinary descendants that start a new session.

Broker records and logs are root-owned under `/var/lib/agent-os-broker`. Agent conversations and tool traces remain in `/var/lib/agent-os-ai`. Restart reconciliation stops unfinished broker units and marks them interrupted without replaying their commands.

The dashboard still supervises the conversation as a core job. **x** stops that conversation worker; a separately launched broker job can continue until its deadline. Stop those jobs by asking the agent, or with the broker CLI. Broker jobs currently appear in conversation output and `list_jobs`, not as separate dashboard rows. PTY attachment, interactive stdin, continuous subscriptions and a unified dashboard are not implemented yet; bounded commands such as log-following programs can be polled.

## Recovery

`write_file` checks the previous hash and preserves the old file in the activity's `.agent-backups` directory. A stale hash is rejected. Backups are workspace files, not tamper-proof snapshots. Concurrent arbitrary programs can still change workspace files; the hash is an optimistic check, not a filesystem transaction. Writes made through arbitrary commands and approved root operations have no automatic rollback. System-wide snapshots and transactional configuration changes remain future work.

## Validation

`tests/broker_integration.py` exercises real guest execution, networking-tool discovery, isolation, file edits/backups/stale hashes, cross-activity access denial, exit codes, output limits, deadlines, cgroup cancellation and local-root-only approval. `broker-verification.json` records results. `tests/agent_test.py` checks tool protocol validation and loop bounds using explicit fixtures. Live model tests are recorded separately; model output quality and free-provider quotas remain distinct from broker correctness.
