# Agent OS experience direction

Design requirements derived from the founder's principles. The [native windowing specification](agent-os-windowing-specification.md) defines the adopted graphical architecture and normative interaction contracts. This document supplies experience context; no graphical desktop is installed.

## Quality bar

The environment should feel composed, responsive and dependable. macOS is a benchmark for coherence and craft, not a template for chrome, iconography or window behavior. An agentic OS should make ordinary work easier, with a distinct identity and equally good direct controls.

The current terminal client supports user-managed tiling, independent views, persistent shared layouts and light/dark themes. The agent and direct controls share revisioned layout operations; see [the implementation contract](agent-shell/LAYOUT.md). PTY-backed shell surfaces and the native graphical environment remain future work.

## Activities and surfaces

An activity groups a goal, its conversation, files, running work and layout. Within an activity, each surface has a clear purpose: conversation, command output, document, terminal session, application or inspected system object. A user can keep related surfaces visible together without losing the activity's context.

Conversation should be comfortable to read. Tool details and evidence remain available without overwhelming every answer. Long operation identifiers and internal implementation labels belong in inspectable details, not the primary visual hierarchy.

## Tiling behavior

Tiling is a layout mode, not an obligation to memorize a window manager's rules.

- Split the focused area horizontally or vertically, then select what it displays.
- Move focus spatially with visible focus feedback and keyboard controls.
- Resize adjacent tiles while enforcing usable minimum sizes.
- Move or swap surfaces without restarting their work.
- Maximize a surface temporarily, then restore the exact prior arrangement.
- Close a view independently from stopping its underlying process.
- Preserve layout per activity and adapt it when the available display changes.
- Keep a visible route to layout actions; shortcuts accelerate discoverable controls.

The terminal stage uses tiled text surfaces inside one terminal. The adopted graphical model combines native declarative surfaces and conventional application windows, with tiled and floating placement. Surface contents and workspace arrangement are separate revisioned documents. These are distinct implementations and must be labelled honestly. Live interactive shell panes require PTY/session support; displaying a command's log does not constitute a terminal session.

## Agent participation

The agent and direct controls should use the same layout operations and state. Requests such as “Put the logs beside this conversation” or “Focus on the document” should change the environment through that shared interface.

A layout request should reference stable surface identifiers and the current layout revision, so stale instructions cannot rearrange an unrelated activity. Layout changes should be reversible with a clear undo action. The agent should preserve manual arrangements unless the user requests a change or has explicitly enabled automatic arrangement. It must not take focus away while the user is typing.

Voice can invoke the same operations once voice input exists. Microphone state and interruption behavior remain explicit; voice is not a prerequisite for operating the environment.

## Visual and interaction direction

Use restrained color, strong legibility, precise spacing and a quiet hierarchy. The work takes visual priority over framing and status chrome. Focus, selection, running, waiting, blocked and failed states must be distinguishable without color alone.

Give each surface a concise title and consistent actions. Keep errors adjacent to the affected work, distinguish provider availability from local execution, and offer an actionable next step. Empty states teach the first useful interaction. Core controls remain usable when the model is slow or unavailable.

Terminal typography, rendering and animation are constrained by the host terminal. The graphical implementation must set its own type, contrast and motion system. Choose those treatments in the relevant surface design rather than pretending the terminal can validate the finished desktop's appearance.

## Acceptance criteria

A layout can be created, resized, rearranged, maximized and restored with direct controls. Focus remains visible. A narrow display preserves access to surfaces without destroying their arrangement. Changing activities restores their layouts. Closing a view does not unexpectedly stop work. A failed model request does not impair layout controls. Human and agent layout actions share state, revision checks and undo behavior.

The interface must be tested at small and large sizes, with long text, empty activities, multiple running jobs, unavailable providers and interrupted connections. Documentation should distinguish visual polish, implemented behavior and future desktop ambitions.

## GUI requirements confirmed by the founder — September 17, 2026

These requirements supersede any earlier assumption of conventional desktop chrome. The founder has specified a calm, welcoming, beautiful graphical environment, with both light and dark appearances. Neither appearance is a secondary treatment. The revised GUI direction includes a minimal system bar showing date/time, the signed-in user and an agent-status icon. There is no dock.

Mouse and keyboard remain first-class ways to use the environment, for accessibility and personal preference. Voice is first-class without becoming mandatory. Essential navigation, instruction, correction, cancellation and recovery must be reachable through direct controls.

The GUI includes a smart launcher designed as an agentic interaction surface from the beginning. It can be invoked through voice, keyboard or mouse. Its role extends beyond opening applications: it interprets an intention in the context of selected objects and current work, requests clarification when needed, and initiates supported actions through the shared system interfaces.

The system must provide clear visible feedback while receiving spoken or typed instructions. Input reception, interpretation and execution must be visibly distinguishable. Feedback must accurately reflect the current state; an animation alone must not imply that the microphone is listening or an action has completed.

### Proposed launcher and feedback behavior

The following are design proposals, not additional founder decisions:

- Provide a discoverable on-screen invocation control as well as a configurable keyboard shortcut and deliberate voice activation. Its placement and form are still open; the minimal system bar and lack of a dock must not make other entry points invisible.
- Use a shared interaction surface for all input methods. Show recognized speech as editable text, show typed instructions as they are composed, and identify selected objects included as context.
- Distinguish ready, listening, composing, understanding, acting, clarification-needed, completed, stopped and failed states with concise text and consistent visual cues. Do not rely solely on color, sound, or motion.
- Clearly separate composing an instruction from submitting it. Ordinary typing must not silently authorize execution. Voice submission and turn-ending behavior require deliberate design and testing.
- Keep correction, dismiss and stop controls available in context. Show completion or failure where the result belongs; the launcher need not remain open after work moves into the environment.
- Let the interaction surface expand when needed for clarification, review or a result, then return attention to the work. Do not make a permanent chat panel the default center of the desktop.
- Share hierarchy, semantics and interaction across light and dark appearances while tuning contrast and surface separation independently. Follow system appearance preferences and provide a manual override. Exact colors, typography and materials remain open.

### Remaining visual decisions

The launcher invocation control, spatial placement, dimensions, transitions, voice activation method, type system, palette and material treatment remain to be explored. The system bar is intentionally limited to date/time, signed-in identity and agent status; there is no dock. The September 18 adopted windowing specification now includes graphical tiling and floating placement; this supersedes the earlier undecided GUI layout model.


## Agent Monitor — confirmed refinement

The agent-status entry in the system bar opens a real application window, not a dropdown or popover. It has independent focus, placement, resizing and close behavior. Closing the monitor does not stop agents. Mouse, keyboard and voice should all be able to open it.

The window shows agents in use, their work, model/provider and token consumption. Session and per-agent usage distinguish input from output. Reported costs may be shown when available; missing cost or usage is marked unavailable, never presented as zero. Estimated values must be labelled separately from provider-reported measurements. Agent status is conveyed by text as well as visual indicators.

The dark concept in `gui-concepts/dark-agent-monitor.png` illustrates these requirements with sample agents and usage. It is not live telemetry or an implemented app. Detailed activity inspection and stop controls are proposed monitor interactions; stopping an agent is distinct from dismissing its window.

### System bar visual correction — confirmed

The bar has no background color, tint, blur or backing strip: items sit directly over the wallpaper. The signed-in name is plain text at the left, without an avatar or preceding icon. Agent status is on the right, followed by date/time as the last, rightmost item. The center stays empty. See `gui-concepts/dark-agent-monitor-v2.png`.

The top-bar Agent Monitor entry is the plain clickable text “Agents”, without a redundant icon or dot. Date/time remains the final item on the right. Current concept: `gui-concepts/dark-agent-monitor-v3.png`.
