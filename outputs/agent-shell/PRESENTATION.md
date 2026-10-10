# Native presentation contract

The Rust core now persists the initial `agentos.presentation/1` headless contract alongside activities. This is the foundation for the graphical implementation; it does not render windows. The curses layout service and existing activities continue independently.

`agent-os presentation request.json` (or `-` for stdin) sends JSON over the existing core Unix socket. The transport derives the caller's UID and process session from Linux `SO_PEERCRED` and process start time. Client actor labels cannot grant human input ownership. Model tools expose the catalog, activity-scoped snapshots and transactions through the same validator.

Implemented operations:

- `catalog.get`: exact `native-core/1` catalog, typed properties, slots, events and budgets.
- `presentation.snapshot`: complete committed documents and journal cursor.
- `presentation.apply`: atomic surface creation/replacement/closure, element edits, binding/action attachments and workspace placement. Exact revision preconditions cover every affected document; new documents expect null. Unknown fields/types, invalid trees, duplicate placements, unsupported output IDs and incompatible bindings are rejected.
- `presentation.subscribe`: initial snapshot, then ordered journal changes after a cursor. This initial implementation uses bounded polling batches, not a held stream. Deleted IDs are identified by null revisions in the receipt. A cursor ahead of the journal requires resynchronization.
- `presentation.undo`: a compensating transaction against an unchanged target. It preserves unrelated documents and rejects divergence. Undo never executes or reverses a Linux command.
- `interaction.begin/renew/end`, `draft.save/get`: process-bound editing leases and separately persisted recoverable text. Draft writes require their own revision. Expired leases do not discard drafts or permit an agent to overwrite them. Changes to an owned element or its location are rejected for other input sessions.
- `binding.snapshot`: current source-owned core job fields, observation time, source revision and explicit availability. Previously registered missing sources remain recoverable; their disappearance does not block unrelated presentation edits.
- `outputs.register`: trusted root compositor advertisement of logical work-area dimensions. An invalidating size change is rejected rather than silently clipping the current arrangement.

The initial catalog includes Stack, Row, Text, Status, Button, Link, TextField and Progress. Properties and strings are inert. Links allow HTTP(S) and mailto only. Read-only bindings currently cover core jobs in the same activity. Host-issued action references support core-job inspection and stopping through `action.issue`, `action.metadata`, `action.invoke/status` and `action.revoke`. Only authenticated native input can issue or invoke them; documents cannot mint executable callbacks. Issuance scopes a concrete job, activity and principal. Invocation requires the observed source revision and an idempotency key. Lost in-flight callbacks become unknown after restart and are reconciled from observed target state without replay. Progress bindings require a compatible numeric source; current core job adapters do not supply one.

A transaction can create a surface and place it in a workspace atomically. Splits require positive normalized ratios; floating rectangles must fit the advertised work area; each surface has one placement. Required output constraints are enforced. Agent peers cannot steal focus or remove human constraints. IDs remain retired after closure; undo restores them at a later revision, preventing old updates from matching a recycled identity.

SQLite commits documents, per-principal idempotent receipts, revisions, identity retirement and journal changes together with full durability. Identical retries return the saved receipt across restart; changed payloads with the same request ID fail. Existing activity removal keeps presentation data available for restoration and does not block other activities.

Still to implement against the full windowing specification: native 716 UI rendering and accessibility qualification, conventional application identities, compositor integration and output-removal restoration, broker/file action adapters, broker/source subscriptions, editable source drafts, catalog migrations and paged snapshots for very large workspaces. The current minimum-size solver enforces a basic 80×32 logical-unit floor, not measured per-component usability. The headless API is experimental until these paths are integrated and exercised.

Verification lives in Rust contract tests, `tests/presentation_client_test.py` and `tests/presentation_guest.py`. The Linux guest test authenticates real IPC peers, exercises two native clients and a forged agent actor, restarts an isolated core, recovers a Unicode draft, retries a committed request, resumes the journal and undoes a change. It does not simulate GUI, screen-reader or microphone acceptance.
