# Agent OS design system

## Native graphical direction

The [native windowing specification](outputs/agent-os-windowing-specification.md) is authoritative for the future desktop. The agent composes stable typed elements and workspace arrangements; native components own visual quality, accessibility and immediate interaction. Live bindings reflect authoritative system state. Atomic revisioned updates preserve focus, selection and drafts. Tiling and floating placement share the same environment model; direct controls stay available without inference.

Both light and dark appearances, a minimal system bar, no dock, the contextual voice/keyboard/pointer launcher and an independent Agent Monitor remain requirements. Generated surfaces use the native token system and component vocabulary, never arbitrary model-generated styling or executable UI code. The native typography, materials and renderer need implementation and visual validation.

The following sections document the **implemented terminal** design. Terminal palette indices and the six-tile limit do not constrain the graphical specification.

## Surface and intent

The implemented surface is a curses terminal client, not a graphical desktop. It is intended for sustained work in a host terminal alongside other applications. The existing cyan identity is retained in a restrained dark theme; a light theme supports bright environments and user preference. Both are direct controls, independent of model availability.

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
