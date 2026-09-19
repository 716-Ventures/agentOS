# Agent OS 0.4 — general system broker

**Windowing design:** The [native windowing specification](../agent-os-windowing-specification.md) defines the adopted graphical architecture: native component catalog, surface documents, source bindings, broker action references and revisioned tiled/floating workspaces. It is planned implementation, not a graphical feature of this release.

A full Debian-based Linux VM with persistent activities, a terminal interface, and a Gateway agent that can use general Linux execution and filesystem tools. Jev assesses actions, selects relevant context, advises on recovery, checks completion and reviews learning; Ling plans and reasons. See [the decision layer](JEV.md). Versioned memory and reusable skills persist across activities. Voice and the graphical desktop are future work.

## Open and use

Open **Open Agent.command** on the Mac, or enter `agent-os` after connecting to the VM. The terminal now has resizable, persistent tiles and light/dark themes: see [terminal controls](TERMINAL.md). Create/select an activity, then press **a** to ask. Press **d** for the explicit disk-inspection shortcut, **r** for an explicit legacy command, **h** for core job history, and **q** to leave. Tab switches tiles; [ and ] change activities; arrows and PgUp/PgDn scroll output. Press v or s to split, +/− to resize, z to maximize, and Space for all actions.

Try “Inspect the network interfaces and default route,” “What services have failed?” or “Create a notes file in this activity and read it back.” The agent discovers and uses installed tools rather than matching those requests to subsystem-specific intent categories.

[The broker guide](BROKER.md) describes the general tools, activity workspaces, administrator proposals, isolation, execution limits, recovery and remaining UI work.

## Model setup

Inside the Linux terminal:

```sh
sudo agent-os-configure
agent-os providers
```

Hidden prompts save credentials only inside the VM. Conversation uses the Gateway key; autonomous action assessment uses the Jev key. Unavailable assessment requires review rather than silently allowing actions. Existing keys are preserved by installation.

The Gateway supports verified free models or explicitly configured paid models. The development VM uses inclusionai/ling-3.0-flash; no automatic paid fallback is used. Free-provider rate limits are reported explicitly. Questions, selected command output and file contents requested through agent tools may be sent to the model provider. Credentials and private service state are excluded from normal execution.

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

Replace IDs with those returned on your machine. `ask` and `disk` return a core job ID. General execution may also create broker job IDs, shown in the output. Broker jobs have their own lifecycle; stopping the conversation does not necessarily stop a launched broker job. Ask the agent to stop it or use the broker CLI described in the guide.

## Persistence and boundaries

The Rust core retains activities, explicit jobs, logs and history. A separate assistant service owns credentials and conversation/tool traces. A root broker launches each assessed general command in a supervised systemd service with OS-level authority. Activities organize work and supply a default directory; they are not filesystem sandboxes. Harmful effects require matching user authorization, including explicit instructions already given in context. The original explicit-command core remains for recovery and compatibility, with its earlier shared-identity limitations.

The terminal and future desktop can use the same service boundaries. This is a single-user development OS; it is not a multi-user policy system. General execution is broader than a diagnostic menu, but it does not promise automatic rollback for arbitrary programs or unrestricted root access.

## Build and validation

Run `python3 deploy.py` from this directory on the Mac to copy source and build/install inside the running guest. The installer preserves credentials and user activity data. It restarts the core, assistant and broker; unfinished work is interrupted rather than replayed.

- `tests/agent_test.py`: tool-loop contract and validation tests with explicit fixtures.
- `tests/providers_test.py`: provider/price checks, including the retained optional Jev adapter.
- `tests/broker_integration.py`: real guest execution, isolation, file recovery, deadlines, cancellation and administrator approval.
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
