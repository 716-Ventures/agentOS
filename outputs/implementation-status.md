# Implementation and qualification status

The full scope remains both `terminal-first-release-plan.md` and `agent-os-windowing-specification.md`. No milestone below constitutes completion of that scope.

Implemented and verified in the UTM guest before the native work: terminal activity/work lifecycle, broker/files/knowledge/shared terminal layouts, interactive terminals, immutable runtime staging/recovery, offline English voice capture and deliberate review, grounding and cancellation. The latest complete reproduction report is in the fresh-verification VM runtime directory. Physical speech, listening, accents/noise and subjective correction quality are not established by fixture audio.

Implemented with ARM64 Linux CI: Rust native presentation validators, journal, receipts, subscriptions, leases/drafts, compensating undo, scoped job inspect/stop callbacks; versioned public GTK component library and native renderer; nested Smithay compositor rendering native and conventional clients with revisioned placement/focus/undo. Native work has not yet been deployed/qualified in UTM because the host is locked.

New runtime work: compatible code rollback with crash recovery, release-specific unit activation and state-format guards; first-run network/audio/provider checks. Host tests cover these changes; the real guest rollback/SIGKILL probe has been added to reproduction and awaits execution.

Remaining implementation/qualification:

- Extend registered source adapters and qualify form/callback workflows. Typed bounded output callbacks, literal/local-field parameters, submit events and stale-form guards are implemented. The core and renderer now consume the same released typed catalog; multiline editing and atomic draft commit/discard are implemented.
- Complete output recovery and restart reconciliation. Measured client minimum sizes and a preserved-layout overview pass ARM64 Linux integration checks. Pointer grabs now use leases/local previews/final commits, manual geometry is protected, and compositor keyboard controls are implemented; physical input journeys still await UTM qualification. Shared WorkspaceDocument projection, authenticated native/conventional identities, activity visibility, typed direct controls, native close/undo with draft retention and journal undo pass ARM64 Linux CI.
- Complete actual output/scaling/work-area discovery, removed-output recovery, direct display ownership and graphical guest qualification. Graphical packaging, session launcher, release bindings and rollback are implemented; full lifecycle and real ELF staging checks are added to CI.
- Complete document paging/virtualized collections and file/conventional source adapters. Broker sources now have typed registered paths, service-owned monotonic observations, paged discovery and explicit backend availability; Linux restart/outage integration checks are added. Shared terminal projection and lease-owned forms/callbacks are implemented, with a real IPC integration probe. Terminal recovery restores matching local edits into revision-guarded drafts, preserves completed multiline input on interruption and adapts paging to terminal dimensions. Native output paging, bounded worker shutdown and private local draft recovery are implemented.
- Qualify native broker review/approval, rejection, conventional terminal attachment and offline rescue terminal controls in the guest. Implemented UI/backend paths await full system verification.
- Exercise actual dynamic agent requests, grounded Jev candidate decisions and unresolved references; measure latency, corrections and model usage without claiming fixture decisions are live quality evidence.
- Validate keyboard, pointer, voice and screen-reader workflows, selection/IME/clipboard/undo/context menus, long text, small displays, light/dark/text scale and reduced motion.
- Verify 716 UI reference appearance, state transitions and motion against its pinned shadcn profile; early releases remain experimental.
- Complete integrated VM image/export, secret-free release preparation, update distribution and migration qualification, guest audio and full repeated cold-boot/recovery checks. Native first-run guidance and bounded Ed25519 runtime export/verification/staging are implemented; key provisioning/distribution and migration across state formats remain deployment work.

All authorized changes are committed/pushed as development proceeds. Test apps, private displays and VMs must be closed after verification. Public 716 UI source remains separate from private agentOS source, VM state and credentials.
