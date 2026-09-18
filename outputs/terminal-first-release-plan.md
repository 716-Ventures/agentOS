# Terminal-First Agentic OS: First Release Plan

**Accepted direction · September 17, 2026**

## Product decision

Our first usable release will be a terminal-first Linux environment whose shell is an agent. It will combine voice, typed intent, explicit commands, persistent activities, and supervised execution. The development target is a complete bootable Linux distribution running in a full virtual machine from the first system milestone. The terminal is its initial user interface. Component tests may run elsewhere, but a standalone CLI or container does not satisfy the system milestone.

The long-term product remains a beautiful, highly usable operating system with a custom agent desktop. The terminal client and future desktop will share the environment core. Intelligence at every layer remains the architectural goal; the first release exercises selected paths through input, activity management, files, processes, and system services.

## Full-system test environment

Build an ARM64 guest image for the Apple silicon development machine, with its own Linux kernel, init system, root filesystem, persistent virtual disk, networking, login, agent services, and terminal interface. Use a full VM host, initially evaluating UTM, rather than Docker or Apple Container as the operating-system test runtime. UTM supports running Linux VMs on macOS; select its backend after checking boot, console, storage, and microphone support. [UTM documentation](https://docs.getutm.app/)

Containers can assist image construction and isolated component tests. They do not substitute for booting the distribution or validating its lifecycle. Apple Container's VM-backed implementation does not make its ordinary container workload equivalent to this full guest setup.

The initial artifact can be a preinstalled bootable virtual disk plus a reproducible build definition and VM configuration. An installer ISO can follow; an installer is not required to test the complete installed system. Define a normal boot path through supported virtual firmware or a documented direct-kernel configuration, and test recovery separately.

Validate microphone capture inside the guest. A host audio bridge may support interim interaction testing, but must be identified as such and cannot count as verified native guest audio. VM validation also does not establish physical-hardware compatibility.

## Implementation status — September 17, 2026

M0 is implemented and verified on this Mac using QEMU with hardware acceleration. The Debian-based ARM64 guest boots through UEFI, runs systemd, supports SSH and serial-console login, reaches the network, and preserves data through reboot and a full shutdown/start cycle. No failed guest services were reported. M0.1 is also implemented: the Rust activity and job core, separate terminal dashboard, structured history, cancellation, and restart reconciliation. M1 now has an installed Gateway tool-using agent with real system-information and disk tools. Live Gateway tool calls have been exercised; Jev is reserved for bounded tasks outside the conversational path. Voice remains unimplemented.

See the [VM foundation and launch instructions](vm-foundation/README.md) and [verification evidence](vm-foundation/verification.json). See the [agent-shell implementation](agent-shell/README.md) and its [verification results](agent-shell/verification.json). M1 integration is in progress; see the agent-shell README for secure key setup.

## Current agent architecture — general system broker

Ask uses the Gateway model with general execution, filesystem and job-control tools, not subsystem-specific intent routing. The model can discover installed Linux utilities and combine them across domains. A root broker launches normal commands under separate per-activity accounts and systemd sandboxes; normal writes stay in the activity workspace. Exact administrative command proposals require local root approval before execution. Jev remains optional for future bounded evaluations.

See [the broker guide](agent-shell/BROKER.md) for implemented limits, command authority, persistence, recovery, and remaining UI/PTY work. Existing explicit-command activities and the disk shortcut remain available. This replaces the earlier plan to build one tool per subsystem.

## Subsequent complete workflow

The user creates an activity associated with a deliberately selected workspace and asks the shell to start a configured development service. They inspect live output, select a failure, and ask by voice, “Explain this.” They directly stop the job, inspect the recorded actions, and return to the activity after restarting the environment.

The model must receive the selected failure and relevant context, not an indiscriminate dump of the user's machine. A configured command provides an unambiguous first execution target. Support for agent-generated commands follows validation of execution and permission behavior.

## Release capabilities

| Area | Required behavior |
|---|---|
| Input | Typed requests, explicit command mode, push-to-talk voice, visible microphone state |
| Activities | Create, switch, set aside, restore; preserve workspace and relevant objects |
| Jobs | Start, inspect output, attach where supported, interrupt, and record exit status |
| Files | Scoped reads and inspectable edits with supported recovery |
| Agent | Route bounded requests, plan supported work, explain failures, report observed results |
| Jev | Optional bounded evaluations where measured value justifies its use |
| System integration | Read service health and resource use; narrowly authorized service actions |
| Persistence | Durable actions, results, revisions, and restart reconciliation |
| Recovery | Direct controls and conventional rescue shell remain available without models |

Voice belongs in the first usable release. Keyboard-only internal milestones are acceptable, but do not satisfy that release definition.

## Shared architecture

```text
Terminal client / future graphical client
                  ↓
Input events + explicit user controls
                  ↓
Environment core: activities, objects, jobs, revisions
                  ↓
Agent: Gateway reasoning and tool loop + optional bounded Jev evaluations
                  ↓
Action broker: scope, authority, validation, execution record
                  ↓
File / process / system-service adapters
```

Rust remains the proposed core language and SQLite the proposed persistence layer. Select the terminal UI library after a focused check of rendering, selection, accessibility, and terminal compatibility. The core API must be independent of that library.

Keep provider credentials in a trusted backend. Store model and question versions with decision records. Treat terminal output and file content as untrusted evidence. Sanitize application output so terminal control sequences cannot impersonate shell controls or permission UI.

## Interaction contract

- The user always knows whether input will become a request, an explicit command, or stdin for an attached process. Never silently reinterpret an explicit command as a model request.
- Keyboard and visible stop controls act locally. Voice interruption also exists, but cannot be the sole dependable cancellation path.
- Selection and focus carry timestamps and object IDs so a delayed transcript cannot silently refer to a newer selection.
- Descriptive progress comes from observed execution state. Proposed work and completed work have distinct representations.
- The terminal provides navigable activities, job status, output, and action history. It must remain useful without relying exclusively on color or animation.
- Confidence can determine whether to resolve ambiguity or escalate reasoning. It does not create permissions.
- File scope must be enforced by execution mechanisms. A working directory alone does not sandbox a subprocess.

## Implementation milestones

### M0 — Bootable distribution foundation

Choose and pin an upstream Linux base, create a reproducible ARM64 bootable disk image, and boot it in a full VM. Include the kernel, init system, user account and login, persistent storage, networking, service logs, and a rescue shell. Define where agent services and state belong before integrating their implementation. No installation onto physical disks is required.

Acceptance: start the VM from a powered-off state, reach login through the guest console, inspect the guest kernel and init system, access the network, create persistent data, reboot, and verify that data remains. Record the image build identity. This foundation is not yet a usable agent release.

### M0.1 — Core contracts and first executable inside the distribution

Define Activity, ObjectRef, Job, InputEvent, ActionProposal, ActionResult, and workspace revisions. Implement persistent activity creation and restoration, plus explicit configured-job execution. A minimal terminal client lists activities and jobs and exposes direct cancellation.

Acceptance: create an activity, launch a harmless fixture job, observe output and exit status, cancel its process group, restart, and retrieve accurate history. Tests cover cancellation, persistence, and stale action rejection. This is an engineering foundation, not yet the usable agent release.

### M1 — Agent decisions and inspectable execution

Add replaceable Jev and reasoning-provider interfaces. Build replay cases for intent routing and references to jobs, output, and files. Validate proposals against current state and execution authority. Start with observation mode, then enable supported reversible operations.

Acceptance: supported requests reach the right operation; unsupported or ambiguous requests do not execute guesses; provider errors leave direct controls functional. No actual integration is claimed until authenticated calls are tested.

### M2 — Voice and shared control

Add microphone capture, deliberate activation, transcription, and grounding in selected output and job focus. Validate audio permissions and device availability in the target Linux environment. Refine the terminal layout and manual takeover behavior.

Acceptance: complete the first workflow through mixed voice and keyboard interaction, interrupt work, correct a reference, and continue after model failure. Measure whole-interaction latency and correction burden.

### M3 — Linux daily use

Add scoped file changes, activity resumption, system status, resource limits, and narrowly defined service operations. Separate the UI lifetime from job supervision. On restart, identify jobs using reliable runtime identity and reconcile them; never trust a recycled PID or automatically replay an uncertain external action.

Acceptance: use the environment for real work over repeated sessions with clear recovery from crashes, network outages, and permission denial. Record shortcomings before expanding the action set.

### M4 — Integrated terminal-first release image

Promote the development image into a reproducible integrated release. Complete first-run setup, guest audio, updates, recovery, and service integration. Test the chosen update mechanism and data migration behavior. Add an installer when needed for distribution beyond the VM. No existing physical disks are modified as part of planning.

Acceptance: boot, configure network and microphone, complete the first workflow, reboot, restore activity context, and recover from a broken agent service without inference.

## Validation boundaries

The terminal release tests whether an agent can coordinate useful work across system layers. It cannot establish graphical usability, arbitrary GUI application control, compositor performance, or the final visual identity. Those remain explicit requirements for the subsequent desktop release.

M0 and M0.1 are complete for the development VM; M1 adapters and a disk-inspection workflow are installed, with initial authenticated Gateway tool calls verified and broader quality evaluation next. Agent features will be integrated and tested inside this image. M1 can be designed with fixtures while account configuration is pending, but measured Jev performance and behavior require real API evaluation. Live speech requires testing on the selected Linux audio stack. The current Mac can support portable development; Linux integration must be exercised in Linux.
