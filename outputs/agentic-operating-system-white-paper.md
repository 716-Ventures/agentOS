# An Operating System Built Around Intelligence

**Architecture update · September 18, 2026:** The [native windowing specification v0.1](agent-os-windowing-specification.md) is the authoritative graphical design. agentOS adopts typed declarative native surfaces, live source bindings, explicit action references and atomic workspace transactions, inspired by json-render's composition model. No JavaScript or webview shell is adopted. This paper explains the rationale; the specification defines the contracts. The graphical implementation remains future work.

*Founding vision, architectural direction, and development strategy*

**Working white paper · Version 0.4 · September 17, 2026**

*Revision 0.4 makes a complete bootable Linux distribution in a full VM the initial system target. Terminal-first describes its user interface, not reduced system scope. See the [terminal-first release plan](terminal-first-release-plan.md) and [Jev assessment](jev-review-and-integration-plan.md).*

## Abstract

This project proposes a Linux-based operating system in which intelligence participates throughout the system, from interpreting input to managing the user's environment. Its desktop manager is an agent: it understands the workspace, responds to intent, preserves continuity, and coordinates the presentation of work. Voice is a first-class interaction path, integrated with pointing, selection, typing, and direct manipulation.

The product is intended to be highly usable and beautiful. macOS supplies a benchmark for coherence, responsiveness, and craft, while the new system develops its own interaction model and visual identity. Familiar desktop conventions remain available where they serve the experience, but they are open to reconsideration.

The proposed implementation preserves Linux and established open-source infrastructure while developing an original environment model, agent runtime, multimodal input system, and custom desktop. Development begins with a bootable Linux distribution in a full VM, integrates the agent shell and voice into that system, and subsequently adds a custom graphical environment using the same core. This paper distinguishes the founder's principles from proposed engineering decisions that must be validated through implementation.

## 1. The founding intent

The project's direction comes from five explicit principles expressed by its founder:

> “An OS that has AI at every level.”

> “A highly usable and beautiful operating system.”

> “Use macOS as a good bar for this, while not copying it.”

> “An OS that is rethought from the ground up.”

> “Voice should be a first class path for interaction with the OS.”

These principles culminate in a specific architectural ambition:

> “Ideally the desktop manager should BE an agent.”

Together, they establish the project's identity. Intelligence must shape how the operating system receives input, represents activity, manages space, and acts. Beauty and usability have equal standing with technical capability. Reusing existing software is acceptable wherever it can be modified or integrated adequately to serve that purpose.

The founder has accepted the scale of the work. The development strategy should make that ambition achievable through successive proofs, without reducing the vision to a conventional desktop with an assistant attached.

## 2. Why rethink the operating system?

A desktop asks people to coordinate many separate systems: applications, documents, windows, folders, settings, and background processes. The user supplies much of the continuity between them. They remember which materials belong together, reconstruct arrangements, transfer information, and translate a desired outcome into commands for individual tools.

The project's hypothesis is that an operating system with shared contextual understanding can take on part of that coordination. It can connect a spoken intention to selected objects, preserve an activity across applications, and present useful results in a form the user can manipulate.

This opportunity reaches below any individual assistant interface. Input handling determines whether “this” can refer to an object selected while speaking. Workspace management determines whether an activity can be set aside and restored. Application interfaces determine whether the system can act on meaningful objects. Resource management determines whether background intelligence disrupts interactive work.

The goal is to make the computer a more capable environment for human intention while preserving the user's ability to act directly and understand what is happening.

## 3. Product principles and their consequences

### 3.1 Intelligence belongs at every layer

Every major layer should be designed with the possibility of contextual understanding and agent action. Intelligence may interpret, coordinate, diagnose, or adapt behavior, depending on the layer.

This does not prescribe a separate model for every subsystem. Nor does it require model inference in every execution path. It requires interfaces and architecture that allow intelligence to participate meaningfully throughout the system.

### 3.2 The desktop manager is an agent

The environment agent owns the responsibility for understanding and managing the interactive environment. In the first release it inhabits an agent shell; in the graphical release it serves as the desktop manager. It maintains context, receives multimodal intent, chooses appropriate actions, and observes their results.

Its responsibilities include composition, focus, continuity, and the relationship between activities. It can arrange a comparison, preserve a requested reference, or restore an earlier context. Its actions remain subject to explicit user constraints and enforceable permissions.

The compositor supplies reliable rendering and input mechanisms. The agent supplies contextual management. Separating those mechanisms allows the desktop to remain responsive while its agent reasons.

### 3.3 Voice is a first-class interaction path

Voice must be present in the original interaction architecture and early functional prototypes. Speech can refer to selection, pointing, visible content, and recent actions. Users can correct an instruction, interrupt work, and switch input methods without restarting their interaction.

First-class voice also requires clear microphone state, deliberate control over listening, and useful behavior in shared or quiet environments. Essential functions must remain accessible when speaking is impossible or undesirable. Spoken input does not obligate spoken output: the most appropriate response may be a visual change.

### 3.4 Beauty and usability are foundational

The environment should feel coherent, legible, responsive, and carefully composed. Typography, motion, sound, spatial behavior, accessibility, and error recovery belong to the product architecture from the beginning.

An intelligent system that is confusing, visually crude, or difficult to control fails the founding intent. Likewise, a polished interface that leaves intelligence peripheral fails it. Both qualities must be developed together.

### 3.5 macOS is a quality benchmark

macOS provides a reference point for everyday usability and integrated craft. The project should establish comparable expectations for interaction consistency, display behavior, application switching, peripheral use, and system settings.

Its dock, menu structure, window controls, and visual materials are not predetermined requirements. The new environment must earn its own forms through the interactions it supports.

### 3.6 Reconsider conventions; reuse infrastructure

Rethinking the experience does not require rewriting mature hardware support or every application. Linux and open-source components provide a foundation on which to build original behavior.

Reuse decisions should consider architectural fit, ability to modify, licensing, upstream health, and maintenance burden. Forks are appropriate when necessary for the experience; extensions and adapters are preferable when they provide sufficient control.

## 4. The interaction model

The core interaction cycle is:

**Multimodal input → grounded intent → authorized action → persistent state → interactive presentation.**

“Grounded” means that an instruction refers to actual objects and current state. A document has an identity; a selected passage has a location; an arrangement has a revision. The system resolves these references before executing an action.

Consider a person comparing renovation estimates. They select two documents while saying, “Compare these.” The environment presents them together. They point to a cost breakdown and say, “Keep this visible.” That request becomes a constraint on subsequent arrangements. They resize an image manually, and the system respects the new choice. Later, “Put this aside” preserves the activity for return.

This example illustrates a broader principle: speech, selection, and spatial manipulation communicate within the same interaction. The user should not have to restate context already established through another input method.

The environment needs a stable vocabulary of interactive forms—documents, collections, comparisons, timelines, and canvases. Agents can compose these forms according to the activity. Stable components and behavior make the environment learnable even when its composition changes.

Persistent activities connect related objects, tools, and history. They are an internal foundation for continuity, not a requirement that every user action begin with formal task creation. A person should be able to open an image or listen to music immediately.

## 5. Proposed architecture

The following architecture is a working proposal. It expresses the principles above, but individual technologies remain subject to validation.

| Layer | Responsibility |
|---|---|
| Multimodal input | Capture speech and direct interaction with timing and context |
| Environment core | Maintain object identity, selection, relationships, constraints, and revisions |
| Desktop agent | Combine fast semantic decisions and extended reasoning to manage the environment through explicit actions |
| Presentation and compositor | Render the environment and deliver immediate input behavior |
| Action broker | Validate authority and execute operations through trusted interfaces |
| Application integration | Expose meaningful application objects and supported actions |
| Context and persistence | Preserve activities, history, provenance, and recoverable state |
| Model gateway | Route decision, reasoning, and speech workloads; manage availability, versions, deadlines, and budgets |
| Linux system services | Supply hardware, processes, storage, networking, and recovery mechanisms |

### 5.1 The environment core

The core maintains authoritative state for the environment. Each object has an identity, content reference, capabilities, activity membership, and presentation state. User instructions such as “keep this visible” become explicit constraints.

The renderer and agent consume appropriate views of this shared state. Application-owned content remains authoritative in its source application; adapters expose references and revisions rather than silently creating competing copies.

### 5.2 The agent's action interface

The agent acts through operations such as presenting objects, arranging comparisons, preserving visibility, setting aside activities, and restoring arrangements. Operations identify actual objects, state their preconditions, and return observable results.

Layout machinery calculates positions from constraints and available space. The agent composes two related documents: SurfaceDocument describes typed native content, and WorkspaceDocument places native and conventional application surfaces in tiled or floating arrangements. A versioned catalog and native registry establish consistent components, accessibility and visual behavior. Live bindings reflect source-owned state; event references dispatch through trusted host handlers and the existing action broker. Atomic revisioned transactions preserve interaction ownership and provide presentation undo without claiming to undo system actions. See the [native specification](agent-os-windowing-specification.md) for schemas, lifecycle and acceptance criteria.

### 5.3 Immediate behavior and deliberative behavior

Pointer movement, typing, dragging, and cancellation use immediate execution paths. Contextual composition and interpretation may require inference.

Workspace revisions prevent a delayed agent response from overwriting newer human actions. If the user moves an object while the agent plans an arrangement, the action must be revalidated against the changed state. Direct intervention takes priority.

This distinction preserves the desktop agent's managerial role while giving it reliable execution machinery.

The revised proposal adds a fast semantic decision path between immediate controls and extended reasoning. It handles bounded judgments such as the intended operation, the object being referred to, or which known presentation mode fits an activity. A reasoning model handles open-ended planning and generation. Both serve the same desktop agent and share state and action contracts.

This enables frequent contextual decisions throughout the environment without requiring every interaction to enter a long reasoning cycle. Explicit local controls, especially cancellation, remain available independently of inference.

### 5.4 Linux and the compositor

The initial direction is to retain an upstream-compatible Linux kernel and implement intelligence primarily through user-space services. Kernel modifications should follow demonstrated requirements.

A custom Wayland compositor is the proposed foundation for the Linux environment. Wayland places display-server and compositing responsibilities with the compositor. Smithay provides Rust building blocks for implementing one; it is a candidate foundation, not a complete desktop product.[1][2]

The compositor can identify and manipulate application surfaces, but understanding their contents requires application integration. A surface alone does not reveal a document's semantic structure.

### 5.5 Application integration

Integration should prefer structured application interfaces, followed by existing APIs or command-line interfaces, accessibility support, and visual interaction where necessary. AT-SPI offers interfaces for accessible application objects, with coverage dependent on the application.[3]

Applications developed for this system could expose an explicit contract for current objects, available actions, permissions, and results. Conventional applications remain useful, with progressively richer integration where feasible.

### 5.6 Models and system resources

A model gateway should support replaceable local and remote inference backends. Transcription, retrieval, and reasoning may use different models. Selection must follow measured quality, latency, memory use, and privacy requirements on target hardware.

Model unavailability should produce a defined reduction in capability. Existing content, direct manipulation, and essential system controls must remain usable. Background inference must be managed so that it does not compromise the interactive environment.

### 5.7 Jev for bounded semantic decisions

TypeSafe Jev evaluates supplied state using predefined answer spaces. It is a candidate for the desktop agent's fast decision path. It accepts textual state; raw voice and visual inputs therefore need separate processing before their relevant evidence can reach this component.[7]

For the future graphical integration, the environment core will assemble a versioned snapshot of a spoken instruction, timestamped interaction events, candidate objects, and existing constraints. Jev will evaluate narrow questions. The core will validate the resulting action as a whole, including object existence, compatible arguments, permissions, and state freshness. A model's confidence will never grant authority.

The decision interface must include unresolved and unsupported outcomes. Candidate generation matters: choosing from an incomplete list can produce a confident but incorrect answer. Ambiguity should lead to a restrained interaction, such as highlighting alternatives, or escalation to another reasoning step.

We will use event-triggered evaluation with bounded requests and cancellation. We will not make rendering, dragging, or keyboard delivery depend on a hosted decision service. Changes in inferred intent must not cause repeated rearrangement; direct user choices and persistent layout constraints govern subsequent behavior.

Jev is integrated in the current terminal agent loop; see [the implementation guide](agent-shell/JEV.md). Its future graphical roles still require measured action accuracy, latency, uncertainty behavior, and correction burden. Local deployment, data handling, account limits, and current model limitations require verification. The adapter must remain replaceable.

## 6. Agency, trust, and recovery

The agent works across the operating system through a broker that enforces authority outside the model. Requested non-destructive work proceeds automatically. Potentially harmful effects require authorization unless the user's existing instruction already covers them. Presentation and model confidence cannot expand that authorization.

Content read from a document or website is evidence, not a source of new authority. Sensitive credentials should be handled through scoped services where possible.

The interface should expose meaningful activity and allow intervention without overwhelming the user with implementation details. Progress and access indicators should reflect actual execution records.

Cancellation, undo, and compensation need distinct semantics. Cancellation stops further work. Undo reverses a supported change. Compensation mitigates an action that cannot be reversed. The system must accurately represent these differences.

Memory should be inspectable and correctable, with source attribution, access scope, and retention behavior. Search indexes and inferred relationships must not silently replace authoritative data.

These are proposed engineering requirements for dependable agency. They support the founding usability principle by making system behavior understandable and controllable.

## 7. Development strategy

### Phase 0: Boot the full Linux distribution

Produce a reproducible ARM64 Linux disk image and boot it on the development Mac using a full virtual-machine host. The guest contains its own kernel, init system, root filesystem, login, networking, persistent storage, and rescue access. Verify cold boot, reboot, service lifecycle, and persistence before counting the system foundation as complete.

Docker and Apple Container may support builds or component tests; they are not the full-distribution acceptance environment. Terminal-first describes the first interface of the complete guest OS. An installer can follow a preinstalled VM disk image. See the release plan for VM selection and guest-audio validation.

### Phase 1: Define and implement the agent-shell core

Build a Rust environment core with persistent activities, files and results represented as objects, supervised jobs, explicit action contracts, and an execution record. A terminal client presents and manipulates this state. The client must not own the agent's durable state or execution authority.

Distinguish natural-language requests, explicit commands, and application input. Preserve a conventional shell escape path. Exact controls operate immediately, while semantic judgments and extended reasoning use their respective inference paths.

### Phase 2: Deliver voice and agent execution

Integrate deliberate microphone activation, transcription, timestamped text selection and job focus, and visible listening state. Voice must work in the intended Linux session, not merely in a development environment. A replaceable speech backend remains the proposed approach.[5]

Use the reasoning model for open-ended intent and planning; evaluate Jev for bounded candidate job or file reference selection and failure classification. Begin with synthetic or approved cases, compare against exact rules and a reasoning-model baseline, and validate complete actions before execution. Extended planning and generation use a separate provider interface. Providers do not receive credentials for tools they do not need.

### Phase 3: Prove daily usability on Linux

Use the agent shell for scoped file work, launching and supervising development services, understanding failures, and resuming activities. Present navigable activity state and results alongside interaction history. Voice, manual takeover, direct cancellation, and model failure behavior are release requirements.

Test restart and reboot explicitly. Restoring an activity restores its records and context; it does not automatically replay commands or resurrect processes. Reconcile observed process and service state before offering further actions.

### Phase 4: Complete the terminal-first operating-system release

Complete the bootable image established in Phase 0, initially for one virtual-machine profile and then selected hardware. Include login, network setup, audio and microphone setup, storage, updates, recovery, and an ordinary rescue shell. Privileged operations use the general system broker with the same effect-based authorization policy as other actions.

An image-based update system remains a candidate. bootc supports transactional OS updates and rollback; user data and database migrations require separate recovery policies.[6] Packaging follows demonstrated usefulness of the installed agent shell.

### Phase 5: Build the graphical environment

Implement the [native windowing specification](agent-os-windowing-specification.md): first a headless Rust presentation contract and transaction tests, then a native component renderer, followed by a nested compositor integrating native and conventional application surfaces. Smithay remains the candidate compositor foundation. Agent composition and Jev candidate evaluation use the established activity, object, job and broker interfaces. The earlier Tauri/webview shell proposal is superseded; the native drawing/text toolkit remains to be selected through validation.

The terminal release validates semantic input, execution, system integration, and continuity. It does not validate spatial composition, graphical application integration, pointer-and-voice interaction, or the full aesthetic ambition. These require dedicated graphical prototypes and acceptance tests.

## 8. How success will be evaluated

Evaluation must measure the experience as well as task completion.

| Dimension | Evidence to collect |
|---|---|
| Multimodal understanding | Correct references when speech and selection overlap; recovery from ambiguity |
| Shared control | No stale actions overwriting newer input; predictable interruption and takeover |
| Responsiveness | Input and voice latency under inference load; compositor frame timing in the graphical phase |
| Fast semantic decisions | End-to-end action accuracy, latency percentiles, autonomous coverage, probability calibration, and correction burden |
| Continuity | Accurate activity restoration, including constraints and unfinished work |
| Learnability | People complete unfamiliar activities without learning special prompt syntax |
| Accessibility | Essential interactions remain available across supported input and output needs |
| Craft | Consistent typography, motion, sound, layout, and state transitions |
| Reliability | Recovery from agent failure, restart, unavailable models, and partial operations |

Performance budgets and usability thresholds should be established on the first target hardware and revised from observed behavior. A scripted demonstration is insufficient evidence of general usability.

Fast-path thresholds must be established per decision family using held-out evidence. Evaluate the complete interaction, including transcription and candidate retrieval. Test delayed, failed, and rate-limited requests; stale results must never overwrite newer direct interaction. Type correctness and semantic correctness are separate requirements.

## 9. Open decisions

The founding principles are established. Several product and engineering decisions remain open:

- The initial audience and the everyday activities used to guide design.
- The visual language and stable spatial conventions of the environment.
- How much proactive rearrangement users want, and how those preferences are expressed.
- Default voice activation, conversational-session behavior, and spoken feedback.
- The capability baseline available entirely offline.
- Native drawing/text toolkit and supported hardware. The current distribution is Debian ARM64; the graphical contract is adopted, while compositor integration remains to be implemented.
- The application integration contract and extent of compatibility with existing software.
- Whether Jev meets the fast-path acceptance criteria, and which capabilities remain available when its service is unavailable.

These decisions should be resolved through prototypes and evidence. They should not quietly weaken the defining commitments.

## 10. The commitment

This project will explore an operating system whose intelligence begins at input and extends through the environment and its services. The desktop agent will have a real role in managing that environment. Voice will be designed into the interaction model. Beauty, accessibility, responsiveness, and usability will guide the architecture throughout development.

The first proof is a usable terminal environment in which a person and an agent share control through voice, typed intent, and direct commands. This is a delivery sequence, not a reduction of the long-term usability and beauty requirements. The long-term objective is an original Linux-based operating system that makes that relationship dependable, coherent, and useful across everyday computing.

## Technical references

The sources below establish capabilities of proposed building blocks. They do not demonstrate or validate the complete system envisioned in this paper.

1. [Wayland architecture](https://wayland.freedesktop.org/architecture.html).
2. [Smithay compositor framework](https://github.com/Smithay/smithay/) and [Anvil reference implementation](https://github.com/Smithay/smithay/blob/master/anvil/README.md).
3. [AT-SPI accessible object interfaces](https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/class.Accessible.html).
4. [json-render catalog](https://json-render.dev/docs/catalog), [state bindings](https://json-render.dev/docs/data-binding), and [experimental Jev composition](https://json-render.dev/docs/jev), architectural references for the native specification; no runtime dependency adopted.
5. [whisper.cpp](https://github.com/ggml-org/whisper.cpp).
6. [bootc upgrades and rollback](https://bootc.dev/bootc/upgrades.html).
7. [TypeSafe System One](https://docs.typesafe.ai/concepts/system-one), [state and input support](https://docs.typesafe.ai/concepts/state), and [confidence semantics](https://docs.typesafe.ai/confidence). Reviewed September 17, 2026. See the companion review for the full Jev source list.


## GUI direction addendum — September 17, 2026

The founder specifies a calm, welcoming and beautiful GUI, with equally considered light and dark appearances. The latest refinement introduces a minimal system bar with date/time, signed-in identity and an agent-status entry. That entry opens a separate Agent Monitor application window showing agents and their usage, not a dropdown. There is no dock. Voice, keyboard and mouse must all provide first-class access for accessibility and personal choice.

An agentic smart launcher is a central interaction mechanism. It interprets intentions in the context of current work rather than merely searching for applications. The system must provide clear visible feedback while the user speaks or types instructions, distinguishing input reception from interpretation and actual execution. Detailed launcher form, invocation placement and visual materials remain open.

These decisions supersede earlier open-ended references to conventional desktop chrome. The September 18 native windowing specification adopts graphical tiling alongside floating placement, superseding the earlier undecided graphical layout model. See [the experience design brief](agent-os-experience-design.md) for confirmed requirements and separately labelled interaction proposals. Earlier Jev routing proposals are also superseded by the Gateway tool-using agent and general system broker; Jev is optional for bounded evaluations.
