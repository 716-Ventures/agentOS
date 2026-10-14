# Agent OS design system

## Native graphical direction

The [native windowing specification](outputs/agent-os-windowing-specification.md) is authoritative for the desktop. The agent composes stable typed elements and workspace arrangements; native components own visual quality, accessibility and immediate interaction. Live bindings reflect authoritative system state. Atomic revisioned updates preserve focus, selection and drafts. Tiling and floating placement share the same environment model; direct controls stay available without inference.

The native desktop implements both light and dark appearances, the approved alpine wallpaper, a transparent system bar, no dock, a contextual launcher and an independent floating Agent Monitor. Commissioner supplies desktop chrome typography. Generated surfaces use 716 UI native components and validated typed documents. The monitor preserves the workspace beneath it and exposes actual agent jobs, model/provider usage, request progress, cancellation and activity history. Missing provider usage is shown as unknown; example agents and token counts from the concepts are not production data.

Desktop verification includes actual composed Wayland scenes in both appearances, launcher draft retention, native input and core lifecycle checks, plus separate synthetic monitor previews for populated, narrow and enlarged-text states. The standalone library owns reusable component conformance; desktop visual verification does not establish complete shadcn parity.

The following sections document the **implemented terminal** design. Terminal palette indices and the six-tile limit do not constrain the graphical specification.

## Desktop refinement standard

The quality reference is Apple's [macOS guidance](https://developer.apple.com/design/human-interface-guidelines/designing-for-macos/), [windows](https://developer.apple.com/design/human-interface-guidelines/windows), [toolbars](https://developer.apple.com/design/human-interface-guidelines/toolbars), and [focus and selection](https://developer.apple.com/design/human-interface-guidelines/focus-and-selection/). AppKit's [material implementation](https://developer.apple.com/documentation/appkit/nsvisualeffectview) distinguishes content, navigation, and transient surfaces. Apply that role-based discipline to GTK; translucent unblurred content is not a substitute for a material. Preserve the approved agentOS identity, typography, wallpaper, and absence of a dock.

The founder's target is 90% of native Apple desktop quality. Automated passes cannot establish that subjective comparison. Assess the complete user journey against these criteria, with no credit for unimplemented or unobserved behavior:

| Area | Required evidence |
| --- | --- |
| Typography | Crisp Retina text; consistent hierarchy, readable secondary text, useful enlarged-text layouts |
| Window craft | Coherent active/inactive chrome, usable pointer targets, accurate control names, drag/resize/maximize/restore behavior |
| Controls | Consistent appearance and geometry; visible focus, hover, pressed, disabled, selection and error states |
| Composition | Content takes priority; secondary actions stay compact; narrow windows and larger text keep tasks reachable |
| Navigation | Common tasks reachable by mouse and keyboard without agent inference; clear dismissal and return paths |
| Continuity | Unsent requests and document drafts survive dismissal, activity changes, and recovery |
| Feedback | Real progress and usage; errors offer recovery; missing telemetry stays unknown |
| Accessibility | Named actionable controls, logical keyboard traversal, non-color status, retained selection, reduced-motion preference |
| Responsiveness | Actual guest input journeys and latency measurements; distinguish guest presentation from Mac-screen latency |
| Integration | Dark/light composition, ordinary applications, clipboard, file operations, setup and first-run behavior |

The current refinement introduces a dedicated categorized Desktop settings window and a username desktop menu, compact request and document actions, consistent desktop button/input/focus styles, larger chrome hit areas, state-correct maximize/restore names, responsive Monitor headers, separately persisted Welcome dismissal, named native dropdowns, and percentage-based text sizing. Agent Monitor retains quick keyboard/zoom access; full desktop preferences and workspace controls live in Settings. Local Terminal and Setup use native VTE windows with shared chrome, live appearance/text sizing, clipboard actions, and owned shell cleanup. Successful document creation/import and terminal startup dismiss the launcher while preserving its unsent request. Desktop controls receive their opening geometry before registration, and committed focus stays above overlapping windows through layout reconciliation. The desktop still has two functional window controls; minimize is not implemented, and no decorative minimize button is shown. Behind-window blur/vibrancy and final Mac-screen latency are not established by the existing guest tests. These limitations must remain explicit when assessing the target.


The refinement also protects running local Terminal work with an accessible close confirmation and restores input on Cancel/Escape. Launcher dismissal waits for committed Terminal focus. Agent Monitor uses a compact utility header and native spacing around its details; Welcome keeps its actions outside scrolling prose and adapts to large text. GTK 4 window shadows use the actual window node with stable active/inactive extents. Close/maximize glyphs use dark ink on their colored discs, with muted ink on inactive controls. Explicit synthetic previews cover both themes and hover/activation styles; real guest input separately qualifies behavior. CI includes initial 300% text and a short-window Terminal confirmation.

The transparent system bar uses a crop-aware black tint to keep its white text legible over the approved wallpaper. The image remains visible; this is a contrast treatment and does not claim backdrop blur or vibrancy. Its inert background neither takes focus nor adds input targets.

Settings uses committed workspace focus when opened from the desktop menu or Monitor. Appearance rows and zoom actions wrap at enlarged text sizes; the category sidebar scrolls without breaking category names. Native Tab navigation must reveal offscreen categories and controls. Window titles follow the text-size preference.

Voice review hands focus to a dedicated floating window before dismissing the launcher. Recording failures show recovery guidance, diagnostic Details and Dismiss; transcript review remains editable and disables Send for blank or oversized text without truncating edits. Dismiss and Discard return to the preserved launcher draft with typing focus. Concise actions and a readable field viewport fit above the on-screen keyboard at 300% text. Private transport fixtures qualify these states without using a microphone, provider, or fabricated production agent telemetry.

Guest profiling removed repeated immutable history copying and unchanged recovery-draft serialization. Recovery still writes changes atomically and retries failed writes. Current measurements and their exact revisions belong in `outputs/vm-foundation/runtime/fresh-verification/desktop-refinement-verification.json`; they do not establish a percentage of native macOS quality or final host-display latency.

## Reusable component foundation

[716 UI](https://github.com/716-Ventures/716-ui) is the standalone public native component library, to be consumed by agentOS through versioned releases. The desktop consumes a pinned versioned release of this library. shadcn is the reference for corresponding component visuals, interaction and motion. Pin a concrete upstream style/theme/revision and verify parity in a standalone component gallery. The library owns reusable controls and tokens; agentOS owns desktop composition and system behavior. See the [library boundary](outputs/agent-os-windowing-specification.md#standalone-component-library--september-19-decision).

## Surface and intent

The following legacy surface is the curses terminal client. It is intended for sustained work in a host terminal alongside other applications. The existing cyan identity is retained in a restrained dark theme; a light theme supports bright environments and user preference. Both are direct controls, independent of model availability.

## Palette

Use semantic roles rather than decorative color. The implementation uses xterm indexed colors because that is the actual rendering target; it does not use CSS.

| Role | Dark foreground / background | Light foreground / background |
|---|---|---|
| Body | 252 / 233 | 235 / 255 |
| Secondary text | 245 / 233 | 240 / 255 |
| Focus/action | 117 / 233 | 24 / 255 |
| Dividers | 240 / 233 | 247 / 255 |
| Selected item | 255 / 24 | 255 / 24 |
| Toolbar | 252 / 235 | 235 / 254 |
| Success | 151 / 233 | 22 / 255 |
| Failure | 210 / 233 | 124 / 255 |

On standard xterm palette values, body, secondary, focus and selected text exceed 4.5:1 contrast. Dividers carry no text. A terminal with fewer than 256 colors falls back to its palette and default background; host customization affects its actual contrast.

## Typography

The host terminal owns font family, size and line height. Hierarchy uses spacing, weight, a consistent pane-title line, and plain-language labels. Conversation prose wraps at at most 76 columns; command output uses available tile width. Unicode clipping and wrapping account for wide characters. ANSI and control sequences from job output are not executed.

## Composition

A compact application bar identifies the activity. The activity rail collapses on narrow displays and can be toggled manually. The work area supports nested side-by-side and stacked splits, up to six tiles. Tiles have independent work selection, view mode and scrolling. A visible toolbar and actions menu expose controls rather than relying on memorized shortcuts.

The focused tile has cyan framing and a numeric label. Inactive titles remain readable. Focus can move by Tab or pointer. A temporary maximized view preserves the underlying tree. When minimum tile sizes cannot fit, the focused tile is shown and Tab reaches the others without destroying the saved arrangement.

## Interaction and persistence

The layout service persists surface identities, selected work, view modes, focus and split ratios. Theme, sidebar and scrolling remain local client preferences. Closing a tile closes a view only. It does not terminate a process. Changing activity restores that activity's arrangement. Keyboard resizing adjusts the nearest split; swap moves the selected surface to the next position. Undo restores saved arrangements across sessions and service restarts.

The editable input line supports horizontal scrolling, Unicode input, cursor movement, Home/End, deletion and Escape cancellation. Conversation view retains the activity’s recent exchanges and opens a reply with Enter. Pending administrator proposals show exact commands and accept a locally handled approval reply. Full output remains available through the view menu. Model availability does not control tiling.

## Scope and verification

These are tiled conversation, command-output, history and work-list views. They are not PTY-backed interactive shell emulators. The agent and terminal share revisioned layout operations. Mouse-drag resizing and screen-reader-specific terminal behavior remain future work.

Verified through actual SSH PTY sessions at 140×40 and 50×24, plus layout/Unicode unit tests. Preview images are renders of the captured terminal cell grid, not graphical desktop mockups. No animated decoration is used. Color-independent labels, keyboard access and focus cues are implemented; formal accessibility conformance is not claimed.
