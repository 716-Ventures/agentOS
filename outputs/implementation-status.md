# Implementation and qualification status

The full scope remains both `terminal-first-release-plan.md` and `agent-os-windowing-specification.md`. No milestone below constitutes completion of that scope.

Implemented and verified in the UTM guest before the native work: terminal activity/work lifecycle, broker/files/knowledge/shared terminal layouts, interactive terminals, immutable runtime staging/recovery, offline English voice capture and deliberate review, grounding and cancellation. The latest complete reproduction report is in the fresh-verification VM runtime directory. Physical speech, listening, accents/noise and subjective correction quality are not established by fixture audio.

Implemented with ARM64 Linux CI: Rust native presentation validators, journal, receipts, subscriptions, leases/drafts, compensating undo, scoped job inspect/stop callbacks; versioned public GTK component library and native renderer; nested Smithay compositor rendering native and conventional clients with revisioned placement/focus/undo. Native work has not yet been deployed/qualified in UTM because the host is locked.

New runtime work: compatible code rollback with crash recovery, release-specific unit activation and state-format guards; first-run network/audio/provider checks. Host tests cover these changes; the real guest rollback/SIGKILL probe has been added to reproduction and awaits execution.

Remaining implementation/qualification:

- Consume one reusable typed component catalog in the core and renderer; finish multiline/form reconciliation, draft commit/discard and callback parameter contracts.
- Connect shared WorkspaceDocument state to compositor placement and registered conventional/native identities. Complete split/resize/move/maximize/restore/close/undo, constraints, manual takeover and persistent restart reconciliation through the shared authority.
- Complete actual output/scaling/work-area discovery, removed-output recovery, native session/display ownership and graphical guest installation.
- Finish terminal projection, source paging/virtualized collections, bounded reconnect/shutdown and source availability handling.
- Finish broker approval and interactive terminal controls in the native environment; preserve direct controls during provider/network failure.
- Exercise actual dynamic agent requests, grounded Jev candidate decisions and unresolved references; measure latency, corrections and model usage without claiming fixture decisions are live quality evidence.
- Validate keyboard, pointer, voice and screen-reader workflows, selection/IME/clipboard/undo/context menus, long text, small displays, light/dark/text scale and reduced motion.
- Verify 716 UI reference appearance, state transitions and motion against its pinned shadcn profile; early releases remain experimental.
- Complete first-run session wiring, integrated VM image/export, secret-free release preparation, update distribution and migration qualification, guest audio and full repeated cold-boot/recovery checks.

All authorized changes are committed/pushed as development proceeds. Test apps, private displays and VMs must be closed after verification. Public 716 UI source remains separate from private agentOS source, VM state and credentials.
