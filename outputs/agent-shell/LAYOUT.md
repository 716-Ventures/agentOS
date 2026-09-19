# Shared layout milestone — Agent OS 0.5

**Graphical successor:** [Native windowing specification v0.1](../agent-os-windowing-specification.md). The API below remains the implemented terminal contract. The new specification defines separate surface-content and workspace documents, catalog discovery, live bindings and atomic cross-document transactions; those extensions are not yet implemented.

The terminal and agent now operate on the same persistent activity layout. This is the presentation control foundation for a future graphical shell; no graphical compositor is installed by this milestone.

## Architecture

`agent-os-layout.service` runs as `agentos-layout`, with a Unix socket at `/run/agent-os-layout/api.sock`. SQLite stores stable surface IDs, split trees, focus, maximization, monotonic revisions, an event log and up to 20 undo snapshots per activity. Surface kinds currently represent terminal views only. Closing a surface never cancels work.

Clients send newline-delimited JSON with `op` and `activity`. Operations are `ensure`, `snapshot`, `apply`, `events`, and `editing`. Apply requires `expected_revision` and an `action` object. Actions are split, close, focus, zoom, restore, resize, swap, bind, view and undo. Failed or stale actions do not mutate state. Undo restores a saved arrangement including its content bindings; jobs themselves continue independently.

The terminal polls for revisions every 600 ms. Direct input controls use the same apply contract as the agent. Rendering, terminal-size adaptation, themes, sidebar visibility and scroll position stay in the client. Legacy arrangements import only when an activity has no shared layout yet; the original file remains available.

The assistant exposes `layout_snapshot` and `layout_change` to the Gateway model, scoped to the current activity. Snapshot supplies bindable core jobs, and dispatch rejects bindings to jobs outside the activity. Broker job identifiers are not yet bindable as independent terminal surfaces.

## Interaction authority

Linux peer credentials identify requests from the AI service account; a request cannot nominate its own actor. A terminal editor renews a three-second input lease. Agent mutations are rejected during that lease; human controls remain available. Disconnected clients stop renewing it. Leases are transient and lost on service restart; clients renew them on the next poll. This is a single-user prototype: authenticated local group members share layout access, not a multiuser authorization boundary.

The reasoning model chooses requested arrangements; deterministic service code validates and applies them. There is no model in the rendering loop. If the model is unavailable, tiling still works. If the layout service is unavailable, an open terminal retains its last rendered arrangement and retries; changes require reconnection.

## Verification

- `tests/layout_test.py`: durable undo, revision conflicts, import-once, stable identity swaps, six-surface limit, atomic rejection and input leases.
- `tests/layout_guest.py`: real Unix socket, agent peer identity, typing rejection, two-client snapshots, stale revision rejection and service restart with undo.
- `tests/terminal_pty.py`: actual SSH terminal sessions, commands, nested splits, resizing, swapping, undo, themes, input editing, compact rendering and reopen.
- `tests/layout_terminal.py`: external agent-identity changes appear in a running terminal; typing blocks those changes.

The live Gateway model called layout_snapshot successfully in this deployment. Its next inference returned HTTP 429, so a complete natural-language layout change has not yet been verified against the live free model. No paid fallback was used.

## Next architectural extension

Evolve the shared layout service through an adapter to the adopted native presentation contract. Preserve stable surface IDs, activities, revisions, undo and existing terminal operations. Introduce SurfaceDocument for typed content and WorkspaceDocument for tiled/floating placement; extend three-second editing leases into field- and geometry-aware interaction ownership. The current API and six-tile terminal projection remain supported. The graphical service must add catalog negotiation, source subscriptions, atomic transactions, output handling and application reconciliation. Window lifetime, pointer input, accessibility, interactive PTYs and voice remain unimplemented graphical milestones.
