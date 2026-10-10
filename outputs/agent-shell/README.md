# Agent OS 0.6 — interactive terminal sessions

**Windowing design:** The [native windowing specification](../agent-os-windowing-specification.md) defines the adopted graphical architecture: native component catalog, surface documents, source bindings, broker action references and revisioned tiled/floating workspaces. The experimental desktop is packaged with this runtime; graphical guest qualification remains in progress.

A full Debian-based Linux VM with persistent activities, a terminal interface, and a Gateway agent that can use general Linux execution and filesystem tools. Jev assesses actions, selects relevant context, advises on recovery, checks completion and reviews learning; Ling plans and reasons. See [the decision layer](JEV.md). Versioned memory and reusable skills persist across activities. Offline English voice input and transcript review are implemented; see [VOICE.md](VOICE.md). The graphical desktop remains under development.

## Open and use

Open **Open Agent.command** on the Mac, or enter `agent-os` after connecting to the VM. The terminal now has resizable, persistent tiles and light/dark themes: see [terminal controls](TERMINAL.md). Create/select an activity, then press **a** to ask. Press **R** to create an interactive terminal and **I** to review approval or attach; **Ctrl-]** detaches while work continues. Press **i** for the explicit disk-inspection shortcut, **r** for an explicit legacy command, the view menu for core job history, and **q** to leave. Tab switches tiles; F6 focuses the activity list; arrows and PgUp/PgDn scroll output. Press v or s to split, +/− to resize, z to maximize, and Space for all actions.

Try “Inspect the network interfaces and default route,” “What services have failed?” or “Create a notes file in this activity and read it back.” The agent discovers and uses installed tools rather than matching those requests to subsystem-specific intent categories.

[The broker guide](BROKER.md) describes the general tools, activity workspaces, administrator proposals, isolation, execution limits, recovery and remaining UI work.

## Model setup

Inside the Linux terminal:

```sh
sudo agent-os-configure
agent-os providers
```

Hidden prompts save credentials only inside the VM. Conversation uses the Gateway key; autonomous action assessment uses the Jev key. Unavailable assessment requires review rather than silently allowing actions. Existing keys are preserved by installation.

The Gateway supports verified free models or explicitly configured paid models. The development VM uses inclusionai/ling-3.0-flash; no automatic paid fallback is used. Free-provider rate limits are reported explicitly. Questions, selected command output and file contents requested through agent tools may be sent to the model provider. Credentials are held by the assistant service, but admitted root commands can access private guest state. This is effect assessment, not filesystem isolation.

## Scriptable commands

```sh
agent-os create "System investigation"
agent-os ask 12 "Inspect the default route"
agent-os jobs 12
agent-os logs 28 --follow
agent-os disk 12
agent-os report 12
agent-os run 12 -- uname -a
agent-os history 12
agent-os stop 28
```

Replace IDs with those returned on your machine. `ask` and `disk` return a core job ID. General execution may also create broker job IDs, shown in the output. Broker jobs have their own lifecycle; stopping the conversation does not necessarily stop a launched broker job. Press X to stop a broker job directly, or use the broker CLI described in the guide.

## Persistence and boundaries

The Rust core retains activities, explicit jobs, logs and history. A separate assistant service owns credentials and conversation/tool traces. A root broker launches each assessed general command in a supervised systemd service with OS-level authority. Activities organize work and supply a default directory; they are not filesystem sandboxes. Harmful effects require matching user authorization, including explicit instructions already given in context. The original explicit-command core remains for recovery and compatibility, with its earlier shared-identity limitations.

The terminal and future desktop can use the same service boundaries. This is a single-user development OS; it is not a multi-user policy system. General execution is broader than a diagnostic menu, but it does not promise automatic rollback for arbitrary programs or unrestricted root access.

## Build and validation

Follow [Rebuild and verify agentOS](../vm-foundation/REPRODUCING.md) for a clean guest and the complete acceptance path. Run `python3 deploy.py` from this directory to update a running selected guest. Deployment packages Git-tracked runtime files with their current contents; add new source files to Git first. Ignored files and generated artifacts stay on the host and required build outputs are recreated in the guest. `install.sh` installs the captured snapshot dependencies, builds with Cargo.lock, stages a complete release and activates it with a durable recovery journal. Credentials and user activity data are preserved; unfinished work is interrupted rather than replayed. Recovery from the ordinary shell is `sudo python3 /usr/local/lib/agent-os/install-recovery.py --recover`.

- `tests/terminal_screen_guest.py`: screen restoration after heavy output and connection loss, detached resizing, vi buffer/mode preservation, raw logs and command exit status.
- `tests/terminal_sessions_test.py`: bounded raw transport, controller leases, backpressure and service-identity separation.
- `tests/terminal_guest.py` and `tests/interactive_terminal.py`: real controlling PTYs, prompts, signals, resizing, reconnect, full-screen curses and dashboard controls.
- `tests/installation_test.py`: release staging, integrity, preflight validation, recovery journal and authenticated dependency-source scope.
- `tests/installation_guest.py`: forced interruption and recovery, configuration/state preservation and reboot persistence probes.
- `tests/agent_test.py`: tool-loop contract and validation tests with explicit fixtures.
- `tests/providers_test.py`: provider/price checks, including the retained optional Jev adapter.
- `tests/work_lifecycle_guest.py`: unified work visibility, origin links, activity stop, detached children, retained background work and durable stop generations; run as root in an idle guest.
- `tests/work_lifecycle_terminal.py`: real SSH terminal picker, broker output and direct job/activity stop controls.
- `tests/broker_integration.py`: real guest execution, OS authority, file recovery, deadlines, cancellation and administrator approval.
- `tests/broker_restart_guest.py`: verified shutdown of root commands and detached children on broker restart, proposal persistence, completion times and no replay.
- `tests/broker_reuse_guest.py`: matching background retries, foreground/background separation and real systemd lifetime settings.
- `tests/write_transport_guest.py`: bounded stdin delivery for full-size guarded writes, exact hashes, backups, stale revisions and pipe behavior; run as root in the guest with provider fixtures.
- `tests/file_result_guest.py`: complete large file results and hashes across broker output pages, including Unicode, through the assistant dispatcher with provider fixtures.
- `broker-verification.json`: broker integration and restart results.
- `verification.json`: original activity/supervisor milestone checks.
- `disk-verification.json` and `agent-verification.json`: earlier disk and model-loop checks.

Live general-agent testing successfully inspected interfaces, routing and DNS using ordinary Linux commands. A file-creation attempt exposed unclear creation-precondition handling, which was improved; a later live retry was blocked by HTTP 429. Direct broker file creation/read/update/backup tests pass. Provider availability and answer quality remain separate from broker correctness.

Shared layout milestone: see [LAYOUT.md](LAYOUT.md) for the service contract, migration and verification.

Tool protocol recovery: assistant answers containing tool-call markup are rejected
and retried at most twice through the normal API tool channel. Markup in answer
text is never parsed into executable actions. At the action budget, the model is
explicitly asked for an honest partial-progress report with tools disabled;
existing job evidence is retained to avoid starting duplicate work. Historical
malformed replies are replaced with a diagnostic in conversation view and are
not fed back as successful assistant instructions. Raw job logs remain intact.
Regression coverage includes malformed output, bounded failures, final-budget
recovery, preserved running-job evidence, and historical conversation rendering.

Empty/unreadable Gateway responses now enter the same bounded recovery budget as
leaked tool markup, preserving prior tool results. Final summary requests omit
tool definitions entirely. Failures after two recovery attempts remain explicit.
Validated with 47 unit tests and a successful live continuation of the existing
Node setup activity: existing installation jobs were inspected and Node, npm,
Git, and GCC versions were measured without reinstalling packages.

Current runtime policy: [EFFECTS.md](EFFECTS.md). Durable memory, skill revisions and inspection commands: [LEARNING.md](LEARNING.md). The command allowlist and server-specific workaround have been removed.

OS-authority update: the Linux guest is the agent’s workspace. Broker commands use root authority by default; activity directories are organizational, not a sandbox. Jev assesses both effects and alignment with the current request. See EFFECTS.md.

## Hardening validation

Run from the repository root:

```sh
python3 -m unittest discover -s outputs/agent-shell/tests -p '*_test.py'
cargo test --locked --manifest-path outputs/agent-shell/Cargo.toml
```

The local suite covers effect/authorization gates, launch cancellation, protocol
validation, truthful broker restart recovery, guarded-write concurrency, conversation recovery and layout behavior.
Rust tests cover persistence, revisions, activity removal and restart reconciliation;
two additional execution/cancellation tests run on Linux.

Guest acceptance requires a provisioned VM: deploy, run `cargo test --locked` in
`/home/developer/agent-os-source`, then the core, broker and layout integration
scripts. These tests create activities/files and the core integration script
restarts its service. Historical verification reports do not substitute for a
fresh run of the current source. Acoustic voice qualification, native graphics, release updates and
formal accessibility validation remain outside this runtime hardening scope.

The initial Rust native presentation contract is implemented and tested headlessly. See [PRESENTATION.md](PRESENTATION.md) for operations, guarantees and remaining graphical integration work.


Signed runtime updates use Ed25519 and OpenSSL 3. Provision a public PEM trust key explicitly at `/etc/agent-os/update-signing-key.pem`; the installer never generates or trusts a distribution key automatically. Keep the private key outside the runtime and VM image. On a build guest, `sudo agent-os-update --export-bundle /path/runtime.tar.gz --signing-key /secure/private.pem` exports the current immutable release; `--release-id ID` selects another staged release. The bundle includes only integrity-manifested runtime files and license notices, with deterministic archive metadata. User data, provider credentials, voice model binaries and private keys are excluded.

On the receiving ARM64 Linux guest, `sudo agent-os-update --stage-bundle /path/runtime.tar.gz` checks the configured signature, payload hashes, architecture, installed dependency versions, voice asset identity and current state contract. `--trusted-key /path/public.pem` explicitly selects another provisioned trust anchor. Staging does not stop services or activate code. Activate the printed release ID with `sudo agent-os-update --activate ID`; existing recovery and compatible rollback remain available. Dependency/voice changes must be installed separately, and incompatible state formats require a migration. Key distribution, rotation, revocation and downloadable release publication remain deployment work.

Shared terminal views (`agent-os views ACTIVITY` or **g** in the dashboard) include a `recover` control for locally retained edits. Recovery copies text into the matching field's draft under an interaction lease; it does not commit view text. Open that field and enter `:draft` to keep the recovered text, then choose Save, Keep or Discard. Completed multiline input is retained locally between lines, including when input is interrupted.

File metadata sources (`file:<opaque identity>`) are published only by the broker after a successful assessed file-helper read, listing or guarded write. They expose the path, file kind, size, permissions, modification time and observation time, plus display strings. No file contents or write input enter the source registry. Observations are stored privately before publication and replayed on broker restart; identity is stable for one activity and path. These report the last completed observation, not a continuously watched filesystem. Missing paths are observations; inaccessible metadata and disconnected producers are unavailable. Use `source.list` for paged activity-scoped discovery.

`state.page` reads `activities` or `jobs` newest-first with a numeric `before_id`, optional job `activity_id` and a 1–128 item limit. Each response stays within 1 MiB; `expected_revision` rejects mixed revisions with `resync_required`. `job.get` retrieves one work record. The native monitor uses paged activity-scoped history; `agent-os jobs [ACTIVITY] --all` reads complete core history. The ordinary snapshot retains its recent-work behavior.

Human hosts use `action.ensure_sources` with up to 64 already registered `broker:`/`file:` source IDs in one activity. It returns stable, user-owned broker inspect/stop/output callbacks and read-only file observation inspection. Defaults retain revocation. Invocation requires current source and (for presented events) surface revisions, and persists a receipt before dispatch. Broker adapters recheck the actual broker job activity/revision under its lock; no operation can provide argv, a different target, approval or input-inspection authority. File inspection returns last-observed metadata, not fresh filesystem contents. Lost callback receipts are reconciled without replaying effects.
