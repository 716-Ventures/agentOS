# agentOS native windowing specification

**Version 0.1 · Adopted architecture · September 18, 2026**

This is the authoritative design for the future graphical environment. It supersedes earlier window-manager proposals where they conflict. It is a specification, not a claim that a native renderer, compositor, voice system, or the protocol below is implemented. The existing curses client and revisioned layout service remain the working terminal foundation; see [LAYOUT.md](agent-shell/LAYOUT.md).

## 1. Purpose and commitments

The desktop manager is an agent responsible for understanding intent and composing the environment around the person's work. It can research, act across the operating system, present results, and learn preferences. The operating system is its workspace. Activities organize continuity; they do not confine its execution to a directory.

We adopt the declarative composition model reviewed in json-render: typed component catalogs, stable element identities, native implementation registries, live bindings, explicit events, and incremental changes. We implement these ideas as an agentOS-native contract. No React, Next.js, JavaScript runtime, browser DOM, or webview is required for the system shell. A conventional browser application can still run on the OS.

Beauty, accessibility, and responsiveness are architectural requirements. The model composes a coherent, professionally designed vocabulary; it does not improvise widget behavior, visual tokens, or pointer handling. Voice, keyboard, pointer, and assistive input reach the same objects and actions. The interface must remain useful when inference is unavailable.

The existing authority policy carries through unchanged: carry out requested non-destructive work automatically; inspect uncertain effects; obtain authorization for harmful effects not already covered by the user's instruction. Root access or unfamiliar software alone is not a reason to ask permission. Presentation cannot grant authority or manufacture success.

## 2. System responsibilities

| Component | Owns | Must not own |
|---|---|---|
| Environment core | Persistent activities, object references, surface identities, versions, relationships, constraints, receipts | Copies of application data that silently compete with the source |
| Desktop agent | Contextual reasoning, research, task execution, surface composition and arrangement proposals | Frame timing, keyboard delivery, unverified execution state |
| Jev decision adapter | Bounded selection/ranking among supplied objects, components, arrangements and recovery choices | Open-ended planning, generated content, final authorization or structural correctness |
| Presentation service | Catalog negotiation, document validation, transactions, subscriptions, undo, interaction ownership | Arbitrary shell execution embedded in UI markup |
| Native renderer | Components, typography, layout within surfaces, local input/editing, selection, accessibility semantics | Inference on each keystroke or frame |
| Wayland compositor | Application surfaces, outputs, placement, focus, input dispatch, frame scheduling | Assuming pixels expose an application's semantic content |
| Existing action broker | Effect assessment, authorization, execution, supervision, observed results | Trusting a button label or model's safety claim |

Rust is the target language for the new presentation contract and native windowing implementation. A custom Wayland compositor remains the direction, with Smithay the candidate foundation. The native drawing/text toolkit is an implementation decision to validate against this contract. Existing Python services can communicate through the protocol; rewriting the entire agent is not a prerequisite.

The presentation service may initially share a process with the native shell. It is a logical authority boundary and testable interface, not a requirement to add a daemon for every responsibility. Compositor input and rendering must remain responsive independently of agent services.

## 3. Two related documents

**SurfaceDocument** describes the semantic contents of an agentOS-native surface: a stable root element, typed elements, their relationships, bindings and event references. Examples are a document view, a comparison, a progress view or a contextual set of controls. A surface is not inherently a chat transcript.

**WorkspaceDocument** describes the placement of surfaces: activities, outputs, tile trees, floating placement, visibility constraints and restore arrangements. It references native surfaces and conventional application windows by persistent environment identity. It does not contain those applications' widget trees.

Both documents are persistent, versioned and transactionally updated. A transaction can create a surface and place it atomically. Neither is the authoritative record of whether a Linux process is running or an operation succeeded.

### Shared identities and ownership

- IDs are opaque, stable and assigned or reserved by the core. Models reference supplied IDs; unknown IDs are rejected unless explicitly created in the same transaction.
- An `ObjectRef` includes object ID, source authority and optional source revision. Sensitive or large contents stay behind the reference until needed.
- An activity groups work and views. A surface has one placement in an activity's workspace; a second view of the same object gets a distinct surface ID. Cross-activity object references are explicit and authorized.
- A native surface retains its ID across revisions and restarts. A conventional application's live Wayland handle is ephemeral; the core associates it with a persistent record and reconciles it after reconnect.
- Element IDs persist through reordering and compatible changes. Replacing an input with a different component is a replacement, never a way to silently reuse its edited value.
- The service derives actor identity from authenticated transport credentials. Client-supplied `actor`, labels, document text and component props cannot assert human authorization.

## 4. Catalog and native registry

The catalog advertises supported component names and versions, typed props, named slots, allowed child relationships, supported bindings, emitted event payloads, accessibility requirements and resource limits. The native registry maps those declarations to tested implementations. Catalog discovery and validation are local operations.

Initial generic vocabulary:

| Family | Examples and purpose |
|---|---|
| Structure | Stack, row, split, scroll region, tabs, section; consistent layout and grouping |
| Reading | Text, rich text, heading, image, document reference; selectable, readable content |
| Structured information | List, table, key/value group, bounded chart; comparison and inspection |
| Interaction | Button, link, text field, choice, toggle; native focus and editing behavior |
| Work state | Progress, status, result, error with recovery action; source-backed lifecycle |
| Embedded views | Document editor, PTY session, application reference; dedicated native hosts |

These are component families to implement progressively, not a claim that every component ships in the first milestone. A server installer, browser installer or Node setup wizard is not a component type. The agent determines the task and uses general tools, then composes suitable controls from the same vocabulary.

Each catalog entry defines compatible presentation variants, density, minimum useful size, localization behavior and semantic roles. Exact colors, arbitrary fonts, raw shaders, executable code and unbounded expressions are not model props. Trusted native modules may extend the catalog through the normal software installation mechanism; a generated document cannot register executable components.

A conventional application is managed through compositor placement and any available application/accessibility adapter. It need not be rewritten in this vocabulary. An unsupported rich component has an explicit fallback representation with its primary information and available actions; it is never silently omitted.

### Standalone component library — September 19 decision

The reusable native component library is [716 UI](https://github.com/716-Ventures/716-ui), a standalone public repository under 716-Ventures with its own release lifecycle. Its initial repository contains specifications and release groundwork; native implementation remains future work. Original work uses Apache-2.0; incorporated or adapted upstream material retains the required license notices. agentOS consumes versioned releases rather than maintaining a private fork of the component implementations.

shadcn is the visual and interaction reference for corresponding components, including states and animations. Before implementation, pin the reference source revision, style, theme, fonts, icons and underlying interaction primitives. Record each component's appearance, keyboard/pointer behavior, focus management, accessibility semantics and motion—including interruption and reduced-motion behavior—in a reproducible parity specification. Validate native implementations against reference scenarios and captures, not just static screenshots.

The public library owns semantic design tokens, reusable native controls, component state machines, animation behavior, accessibility integration, typed component metadata, documentation, a standalone gallery and visual/interaction regression tests. It must be usable without agentOS, an agent, Jev, provider credentials or a network connection. Rust remains the implementation direction; the native renderer choice remains open.

agentOS owns activities, workspace placement, the compositor, system authority, broker integration, agent orchestration and OS-specific views. Its presentation registry adapts library components to SurfaceDocument, bindings and action references. The library emits typed application events; it does not execute privileged commands or prescribe an application's authorization policy. Window-management behavior remains in this specification; a reusable split-view control may live in the library without taking over desktop placement.

Develop the public repository independently of the private OS history. Publish reusable source and deliberately public examples, with no VM state, account configuration or credentials. Establish a changelog, supported platform matrix and versioned APIs; mark early releases experimental until their native interaction and accessibility requirements are verified. Select one renderer for the first implementation rather than promising an untested universal backend abstraction.

## 5. Surface contract

Protocol v1 uses UTF-8 JSON over local authenticated IPC, independent of any programming language. IDs and component versions are strings; revisions are unsigned integers. Documents use a flat element map and an ordered list of child IDs per named slot.

Required envelope: `protocol`, `catalog_revision`, `surface_id`, `activity_id`, `revision`, `title`, `root`, `elements`, `bindings`, `actions`. Element fields are `type`, `props`, `slots` and `events`. Type includes its major component version, for example `Text@1`. Unspecified optional maps are empty. Unknown fields are rejected in v1 rather than ignored.

Illustrative valid shape, assuming the named catalog entries and references have been advertised:

```json
{
  "protocol": "agentos.presentation/1",
  "catalog_revision": "native-core/1",
  "surface_id": "surface-job-a",
  "activity_id": "activity-a",
  "revision": 0,
  "title": "Current work",
  "root": "content",
  "elements": {
    "content": {
      "type": "Stack@1",
      "props": {"spacing": "normal"},
      "slots": {"children": ["heading", "status", "details"]}
    },
    "heading": {"type": "Text@1", "props": {"text": "Current work", "role": "heading"}},
    "status": {"type": "Status@1", "props": {"value": {"binding": "job-status"}}},
    "details": {
      "type": "Button@1",
      "props": {"label": "Show details"},
      "events": {"activate": {"action": "inspect-job"}}
    }
  },
  "bindings": {
    "job-status": {"source": "job:a", "path": "/status", "access": "read"}
  },
  "actions": {
    "inspect-job": {"ref": "action:inspect-job-a"}
  }
}
```

Binding references are typed values accepted only by compatible props. A plain string containing binding syntax is still text. Source IDs and action references must resolve in the core for the authenticated principal; the example IDs are illustrative, not executable handles.

Structural validation requires one root, a reachable acyclic tree, one parent per child, valid slot types/cardinalities, no dangling references and supported versions. Reusable content uses shared object references, not multiply parented widget nodes. Document and binding strings are inert; links are activated through the host handler. Shell execution is never inferred from displayed text.

## 6. State and binding contract

Keep three classes of state separate:

1. **Authoritative domain state:** files, process/job lifecycle, installed software, agent activity and provider telemetry. The renderer subscribes to source-owned snapshots and events, with source revision, observed time and availability. Models cannot overwrite these through presentation patches.
2. **Persistent presentation state:** element identity, arrangement, titles, selected views and constraints. The presentation service validates and stores it.
3. **Immediate interaction state:** cursor, selection, scroll anchor, focus, IME composition, pointer capture and unsubmitted text. Native clients own it during interaction. Drafts that need recovery are stored separately from model-generated documents.

Bindings read typed paths from registered sources. Unknown, disconnected or stale values produce an explicit unavailable/stale state, not zero, empty success, or invented progress. Subscriptions deliver an initial snapshot and ordered revisions; a gap triggers resynchronization. Coalescing is allowed for display values, not for losing terminal job outcomes.

Two-way binding is allowed only to registered editable draft fields. Committing a draft to a document or system setting is an action with source revision preconditions. No arbitrary write-through to domain objects. A control remains responsive while a commit is pending and shows errors beside the affected field.

V1 allows typed literals, source-path bindings and a small set of validated predicates such as equality and presence. It does not evaluate arbitrary expressions or scripts. Collections use stable item keys and virtualization in the renderer. Large content is paged through source adapters rather than embedded in model context or a giant UI document.

## 7. Action and event contract

A component emits a named, typed event. The native host associates it with a core-issued action reference, authenticates the caller, checks current revisions and resolves any user-edited parameters. Presentation operations go to the presentation service; file/process/system operations go through the existing broker. Conventional app actions use their registered adapter.

Action references bind an operation, target, parameter schema, issuer and validity conditions. They are scoped and revocable, and are not transferable approval tokens. Events include an idempotency key so double clicks and retries cannot repeat an operation accidentally. Identical accepted keys return the existing receipt; reuse with changed contents is rejected. Timeouts are reconciled through that receipt before retrying.

An event receipt reports accepted, running, awaiting user, succeeded, failed, cancelled or unknown, with evidence references as applicable. The model may explain a receipt but may not turn its own prose into a successful system status. Closing a surface has no implicit process-stop or file-delete effect.

Approval, when necessary, is host-owned UI showing the concrete effects and affected objects. The broker considers the actual user instruction and its scope; it must not ask for a second magic-word confirmation for an already authorized action. A changed target or materially broader harmful effect requires renewed review. Ordinary layout changes need no approval ceremony. Layout undo never claims to undo a command, installation or file deletion.

Generated content cannot impersonate the trusted approval region. Page text, logs, saved memory, inferred preferences and model-generated button labels are evidence/content, never fresh user authorization. External account sign-in remains an explicit interaction with that account's authentication flow.

## 8. Workspace, tiling and focus

Adopt tiling as a first-class graphical layout capability alongside floating windows. A workspace contains per-output tile trees and floating placements, references the surfaces it presents, and records persistent constraints. Tile nodes are leaves or ordered splits with an axis and normalized ratios. Floating rectangles use logical display coordinates. The compositor owns conversion to output scale and physical pixels.

WorkspaceDocument requires `protocol`, `workspace_id`, `activity_id`, `revision`, `outputs`, `constraints` and `focus`. Each output entry contains a tile tree (or null), ordered floating placements and an optional maximized surface. A leaf references one `surface_id`; a split specifies `axis`, `ratios` and `children`. An output key refers to an advertised output identity. Constraints are typed records with target IDs, provenance (explicit request, direct manipulation or inferred preference) and strength. Explicit constraints take precedence over inferred preferences. Focus references an existing surface and optional element, or is null.

Illustrative single-output arrangement; the referenced output and surfaces must exist:

```json
{
  "protocol": "agentos.presentation/1",
  "workspace_id": "workspace-a",
  "activity_id": "activity-a",
  "revision": 4,
  "outputs": {
    "output-a": {
      "tiles": {
        "kind": "split",
        "axis": "horizontal",
        "ratios": [0.6, 0.4],
        "children": [
          {"kind": "leaf", "surface_id": "surface-document-a"},
          {"kind": "leaf", "surface_id": "surface-job-a"}
        ]
      },
      "floating": [],
      "maximized": null
    }
  },
  "constraints": [],
  "focus": {"surface_id": "surface-document-a", "element_id": null}
}
```

A surface appears at most once across all tile and floating placements in the document. Ratios are finite, positive and sum to one; axis is horizontal or vertical. A floating entry contains `surface_id` and finite logical `x`, `y`, `width`, `height`, with positive dimensions. Its array order determines back-to-front stacking within the ordinary window layer. Trusted system overlays occupy separate host-owned layers that documents cannot nominate.

The layout solver enforces minimum sizes, output work areas and pinned placements. The agent normally requests relationships—beside, stacked, visible, set aside—rather than guessing pixel coordinates. The native window controls expose split, move, resize, swap, maximize, restore, close-view and undo with pointer and keyboard equivalents. Voice invokes the same operations.

Human placement becomes a constraint until the user changes it or requests a conflicting arrangement. A direct request to arrange the workspace may replace relevant manual constraints; proactive arrangement must respect them. If constraints cannot be satisfied, preserve the current layout and return a conflict describing which constraint prevents the requested change. Never shrink content below usability to make an apparently successful layout.

When space is insufficient, use accessible tabs or an overview of preserved surfaces; retain the preferred arrangement for a larger display. Disconnecting an output moves its visible surfaces onto an available output without losing restore placement. Reconnection offers restoration without interrupting active input. Output scale, rotation, virtual keyboards and screen magnification are part of available-space calculation.

Opening results does not steal focus. Explicit user requests to focus or open for interaction may focus the target; background discoveries update their surface or a restrained notification. A temporary maximized view preserves the complete arrangement. Closing a native view with unsaved edits preserves its draft or asks about discarding it; application-owned close behavior must respect the application's own unsaved-work flow.

The system bar remains minimal: date/time, signed-in identity and agent status. No dock. The agent-status entry opens an independent Agent Monitor window. The contextual launcher is temporary and supports voice, typing and selected-object context. Activities organize work without forcing the user to create one before opening a file.

## 9. Revisioned transactions and incremental composition

Logical API v1:

| Operation | Result |
|---|---|
| `catalog.get` | Catalog revision, schemas, versions and limits |
| `presentation.snapshot` | Documents and revisions visible to the caller |
| `presentation.subscribe` | Snapshot then ordered committed changes; resumable event cursor |
| `presentation.apply` | Atomic commit receipt or structured rejection |
| `presentation.undo` | A new compensating presentation transaction |
| `interaction.begin/renew/end` | Native interaction ownership, bound to authenticated session |
| `action.invoke/status` | Execute or reconcile a registered action through the relevant authority |

`presentation.apply` carries `protocol`, `request_id`, `expected_revisions` for every affected document, `catalog_revision` and an ordered `operations` array. Operations create/close surfaces, put/remove elements, set props, replace slot children, attach/detach bindings and actions, and set workspace layout/constraints/focus. Explicit typed operations replace arbitrary JSON-pointer writes into server-owned fields. Whole-document replacement goes through the same validation and ownership checks.

For example, a complete update to an existing Text element uses:

```json
{
  "protocol": "agentos.presentation/1",
  "request_id": "update-17",
  "expected_revisions": {"surface-job-a": 0},
  "catalog_revision": "native-core/1",
  "operations": [
    {"op": "element.set_props", "surface_id": "surface-job-a", "element_id": "heading", "props": {"text": "Work details", "role": "heading"}}
  ]
}
```

`element.set_props` replaces the complete props map of that element. An accepted response returns `request_id`, `status: committed`, the new `revisions` map and `event_cursor`. Rejected requests return `status: rejected` and a typed `error`, without advancing revisions. Creation assigns initial revision 0; each transaction increments each affected existing document once. Request IDs are deduplicated durably per authenticated principal using a payload digest; identical retries return the recorded receipt, while changed payloads with the same ID are rejected. This also covers a lost response after a successful commit.

Stage all operations, validate the resulting documents and cross-document references, then commit once and publish one coherent revision set. Rejection never partially changes the visible environment. A create expects the ID to be absent; an update expects the exact current revision. Errors include `stale_revision`, `interaction_conflict`, `invalid_document`, `unsupported_component`, `missing_reference`, `constraint_conflict`, `resource_limit` and `unauthorized`; responses contain safe actionable details and current revision numbers.

Streamed generation produces drafts. Commit only complete valid transactions: a heading and a status region may appear early, followed by a complete result section. Never expose malformed fragments or activate a half-generated control. A cancelled generation discards its uncommitted draft; already committed results remain available. A stale proposal is discarded or recomputed against a fresh snapshot, never blindly replayed.

Interaction ownership protects the fields and geometry under active editing, dragging, selection, IME composition or pointer capture. Unrelated status bindings continue updating. Conflicting agent mutations are rejected with a retryable conflict; the agent waits for an event or recomputes rather than polling aggressively. A direct human change also invalidates stale proposals via revisions. A lease timeout alone cannot authorize overwriting a recovered draft: the field's content revision still has to match.

Initial protocol budgets: at most 1 MiB per document, 2,048 elements per surface, tree depth 32, 128 operations and 4 MiB per transaction. Large data is referenced/paged. These are proposed defensive implementation defaults, not measured desktop capacity. Limits are advertised and negotiated; exceeding one returns a clear rejection and leaves the last good view intact. There is no six-window GUI limit inherited from the terminal.

## 10. Jev and the reasoning model

The reasoning model understands the request, gathers evidence, generates content, uses general OS tools and proposes composition. Jev receives bounded current candidates and explicit questions. Useful decision families include resolving “this window,” ranking relevant objects, selecting a suitable component family, choosing among solver-produced arrangements and assessing whether a proposed result answers the request.

For prepared compositions, the core supplies concrete component candidates with grounded props and valid action references. Jev can select membership and then choose arrangement among candidates consistent with that selection. Dependent choices require a later evaluation; independent answers are not assumed to form a valid tree. The reasoning model can create new content or retrieve missing objects when existing candidates are insufficient.

Every candidate set includes unresolved/none where appropriate. Deterministic code checks schemas, referential integrity, revisions, resource budgets, focus ownership and authority. Jev is probabilistic; typed output does not make its semantic judgment deterministic. No confidence threshold creates consent or proves a layout usable.

Evaluate on significant user intent and context changes, not pointer movement or each frame. Coalesce redundant events, cancel superseded requests, bound time/cost, and record decision purpose, model version, distributions, latency and outcome. Learn arrangement preferences from explicit choices and corrections without converting them into permission. Learning remains inspectable and reversible.

If Jev is unavailable, the reasoning model may still propose a document under the same deterministic validation. If all models are unavailable, existing views, live bindings and direct controls continue. No fallback silently changes the configured model or conceals billed work.

## 11. Usability and visual contract

The native registry owns a shared semantic token system: readable type, consistent spacing, focus, selection, borders, depth, motion and status. Both light and dark appearances receive independent contrast checks. Use restrained cyan identity where appropriate; the terminal's numeric palette does not define final GUI colors.

Text is selectable and copyable by default, links work through a native handler, and context menus expose common operations. Editing supports Unicode, IME, undo and platform clipboard behavior. Every interactive component supplies accessible name, role, value, state and actions to the platform accessibility bridge. Keyboard and assistive navigation follow semantic reading order independent of visual rearrangement. A focused element is never removed without a defined focus successor and preserved edit state.

Body text targets at least 4.5:1 contrast; large text and meaningful non-text controls target at least 3:1. Focus and statuses do not rely on color. Respect text scaling and reduced motion. Transitions explain spatial change and never delay direct input. Aim for presentation of local interaction feedback within 50 ms at p95 on the selected VM/hardware profile; separately measure rendering frame times under inference and job load. These are acceptance targets, not current measurements.

Progress communicates observed work in plain language, for example “Checking the installed packages.” It must distinguish researching, executing, waiting for external input, and completed work without exposing hidden reasoning or raw tool syntax. Technical logs remain available in details. Success requires observed results; failures identify what happened and a usable next action.

Voice shows microphone state, an editable transcript, submitted intent and referenced objects. Bind “this” to the selection snapshot associated with the utterance, not a later incidental selection. Uncertain referents can be highlighted for correction. Local stop, dismiss and keyboard operation remain available while speech or inference is slow.

## 12. Persistence, failure and compatibility

Persist documents, constraints, revisions, committed receipts and presentation undo history transactionally. Persist recoverable drafts separately with appropriate local access control. Never store provider keys or authentication secrets in documents. Renderer reconnect starts from a complete snapshot and reconciles local drafts; it does not replay system actions.

A renderer failure leaves jobs running. A presentation-service failure leaves the last valid scene visible where possible, with local input/recovery controls and truthful connection state. A compositor crash may disconnect applications; session recovery must explicitly reconcile survivors and lost clients. No claim of seamless compositor crash recovery is made.

On restore, reconcile domain references and application instances against actual state. Missing objects retain a recoverable placeholder with locate/reconnect/close-view actions. Reopening an activity never automatically reruns commands or relaunches unverified work. An undo restores presentation state only, subject to current constraints and interaction ownership; divergent or missing objects yield a conflict rather than destructive reconstruction.

Negotiate protocol major version and exact catalog revision before mutation. Unknown major versions are read-only or rejected with an upgrade explanation. Catalog migrations preserve an original snapshot and stable IDs where compatible. A missing component uses a registered fallback; an unsupported interactive component cannot dispatch its original action from a misleading substitute.

Conventional Wayland application compatibility is required for the graphical milestone. XWayland is a later compatibility decision. Semantic control of an application depends on its adapters/accessibility support, not on its mere appearance in the workspace.

## 13. Delivery sequence and acceptance

1. **Contract and headless core.** Implement typed Rust documents, catalog schemas, validators, transaction journal, receipts, subscriptions and replay tests. Adapt the existing layout API without changing running activities. No graphical capability claimed yet.
2. **Native surface renderer.** Render a small real catalog with selectable text, functioning links, forms, live job bindings, native input and accessibility. Exercise dynamic compositions from actual agent requests, not a task router. Use a nested graphical test session first.
3. **Workspace compositor.** Integrate native and conventional Wayland surfaces, tiled/floating placement, output changes, focus, undo and restart reconciliation. Validate within the full Linux VM before claiming OS integration.
4. **Agent composition and Jev.** Expose catalog/snapshot/transaction tools, grounded candidate selection and bounded incremental updates. Connect real requests to real broker work and source-backed results. Measure unwanted movement, correction rate, latency and model usage.
5. **Daily-use quality.** Complete voice, assistive interaction, text scaling, appearance, keyboard/pointer parity, application compatibility and recovery tests. Hardware/GPU support is an explicit qualification step beyond VM success.

Required evidence before calling the native windowing milestone usable:

- A user request produces appropriate native content and a useful arrangement; unfamiliar tasks can use general execution tools without adding task-specific UI code.
- Human and agent changes use the same revisions and transaction semantics. Stale replies, invalid trees, missing IDs and duplicate events produce no accidental changes or duplicate side effects.
- Typing, selection, IME composition and dragging survive concurrent generation, network delay and refresh. Agent work does not steal focus or erase a draft.
- Split, resize, move, maximize, restore, close-view and undo work without any model. A live application and native surface tile together.
- Changed job states update bound controls without an inference call. A job failure cannot remain visually marked succeeded by model text.
- Authorized routine work proceeds; already authorized harmful work is not gated again; genuinely broader harmful effects receive concrete review. Forged UI content cannot supply approval.
- Two clients, stream cancellation, provider outage, renderer/service restart, removed outputs, source disconnection and undo after divergence are exercised with recoverable outcomes.
- Keyboard-only, pointer, voice and screen-reader journeys cover launch, navigation, editing, correction and stop. Small displays, long text, light/dark appearance and text scaling are verified in native rendering.

The first implementation deliverable is the headless contract and its tests. The current six-tile terminal client remains a supported projection of the environment, not the specification of every future graphical surface.

## 14. Relationship to json-render and existing documents

The borrowed idea is a typed declarative interface between agent composition and host-controlled rendering. agentOS adds workspace placement, native input ownership, compositor/application integration, source authority, broker actions, persistent transactions and recovery. We are adopting the architectural model, not promising wire compatibility or taking a runtime dependency.

The reviewed [catalog](https://json-render.dev/docs/catalog), [bindings](https://json-render.dev/docs/data-binding), [streaming](https://json-render.dev/docs/streaming) and [source repository](https://github.com/vercel-labs/json-render) informed this design. Its [experimental Jev composition](https://json-render.dev/docs/jev) informed bounded candidate selection; we do not depend on that experimental API. Our atomic transactions and ownership rules are agentOS design requirements, not claims about upstream guarantees.

See the [white paper](agentic-operating-system-white-paper.md) for product rationale, [experience direction](agent-os-experience-design.md) for interaction principles, [terminal layout implementation](agent-shell/LAYOUT.md) for what exists, and [Jev guide](agent-shell/JEV.md) for currently integrated model responsibilities.
