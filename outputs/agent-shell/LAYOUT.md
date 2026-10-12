# Shared layout milestone — Agent OS 0.5

**Graphical successor:** [Native windowing specification](../agent-os-windowing-specification.md). The API below remains the supported terminal layout contract. Separate surface-content and workspace documents, catalog discovery, live bindings and atomic cross-document transactions are implemented by the [native presentation service](PRESENTATION.md). See [current qualification](../implementation-status.md) for verified behavior and remaining work.

The terminal and agent operate on the same persistent activity layout. This guide describes the original terminal service; the integrated runtime also includes a GTK native renderer and a Wayland compositor with nested and direct-display sessions.

## Architecture

`agent-os-layout.service` runs as `agentos-layout`, with a Unix socket at `/run/agent-os-layout/api.sock`. SQLite stores stable surface IDs, split trees, focus, maximization, monotonic revisions, an event log and up to 20 undo snapshots per activity. Surface kinds currently represent terminal views only. Closing a surface never cancels work.

Clients send newline-delimited JSON with `op` and `activity`. Operations are `ensure`, `snapshot`, `apply`, `events`, and `editing`. Apply requires `expected_revision` and an `action` object. Actions are split, close, focus, zoom, restore, resize, swap, bind, view and undo. Failed or stale actions do not mutate state. Undo restores a saved arrangement including its content bindings; jobs themselves continue independently.

The terminal polls for revisions every 600 ms. Direct input controls use the same apply contract as the agent. Rendering, terminal-size adaptation, themes, sidebar visibility and scroll position stay in the client. Legacy arrangements import only when an activity has no shared layout yet; the original file remains available.

The assistant exposes `layout_snapshot` and `layout_change` to the Gateway model, scoped to the current activity. Snapshot supplies bindable core and broker jobs, and dispatch rejects bindings to jobs outside the activity. Core bindings retain positive integer IDs; broker bindings use `broker:JOB_ID`. Both persist through layout restart and undo and display output through their own supervisor.

## Interaction authority

Linux peer credentials identify requests from the AI service account; a request cannot nominate its own actor. A terminal editor renews a three-second input lease. Agent mutations are rejected during that lease; human controls remain available. Disconnected clients stop renewing it. Leases are transient and lost on service restart; clients renew them on the next poll. This is a single-user prototype: authenticated local group members share layout access, not a multiuser authorization boundary.

The reasoning model chooses requested arrangements; deterministic service code validates and applies them. There is no model in the rendering loop. If the model is unavailable, tiling still works. If the layout service is unavailable, an open terminal retains its last rendered arrangement and retries; changes require reconnection.

## Verification

- `tests/layout_test.py`: durable undo, revision conflicts, import-once, stable identity swaps, six-surface limit, atomic rejection and input leases.
- `tests/layout_guest.py`: real Unix socket, agent peer identity, typing rejection, two-client snapshots, stale revision rejection and service restart with undo.
- `tests/terminal_pty.py`: actual SSH terminal sessions, commands, nested splits, resizing, swapping, undo, themes, input editing, compact rendering and reopen.
- `tests/layout_terminal.py`: external agent-identity changes appear in a running terminal; typing blocks those changes.

The live Gateway model called layout_snapshot successfully in this deployment. Its next inference returned HTTP 429, so a complete natural-language layout change has not yet been verified against the live free model. No paid fallback was used.

## Implemented native extension

The native presentation service preserves activities, revisions, undo and existing terminal operations while using SurfaceDocument for typed content and WorkspaceDocument for tiled/floating placement. Field- and geometry-aware interaction leases protect local work. Catalog negotiation, source subscriptions, atomic transactions, output handling and application reconciliation are implemented, alongside native window controls, pointer input, accessibility and explicit interactive PTY attachment. The current API and six-tile terminal projection remain supported. The [native shell guide](../native-shell/README.md) describes session controls; the [implementation status](../implementation-status.md) distinguishes VM verification from outstanding physical-device, live-provider and reference-conformance qualification.
