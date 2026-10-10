//! Desktop shortcuts use XKB keysyms; printable application input passes through.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Shortcut {
    Cycle(bool),
    Maximize,
    Restore,
    Float,
    Close,
    Nudge { x: i32, y: i32, resize: bool },
    Undo,
    Pan { x: i32, y: i32 },
}
// XKB's standard Ctrl+Alt function-key level emits XF86Switch_VT_1..12.
// Normalize that level so desktop F8/F9/F10 and direct VT controls agree.
pub fn function_key(key: u32) -> u32 {
    if (0x1008fe01..=0x1008fe0c).contains(&key) {
        0xffbe + key - 0x1008fe01
    } else {
        key
    }
}
pub fn decode(ctrl: bool, alt: bool, shift: bool, key: u32) -> Option<Shortcut> {
    if !ctrl || !alt {
        return None;
    }
    match function_key(key) {
        0xff09 | 0xfe20 => Some(Shortcut::Cycle(shift || key == 0xfe20)), // Tab / ISO Left Tab
        0xffc7 => Some(Shortcut::Maximize),                               // F10
        0xffc6 => Some(Shortcut::Restore),                                // F9
        0xffc5 => Some(Shortcut::Float),                                  // F8
        0xffff => Some(Shortcut::Close),                                  // Delete
        0xff51 => Some(Shortcut::Nudge {
            x: -20,
            y: 0,
            resize: shift,
        }),
        0xff53 => Some(Shortcut::Nudge {
            x: 20,
            y: 0,
            resize: shift,
        }),
        0xff52 => Some(Shortcut::Nudge {
            x: 0,
            y: -20,
            resize: shift,
        }),
        0xff54 => Some(Shortcut::Nudge {
            x: 0,
            y: 20,
            resize: shift,
        }),
        0xff55 => Some(if shift {
            Shortcut::Pan { x: -1, y: 0 }
        } else {
            Shortcut::Pan { x: 0, y: -1 }
        }),
        0xff56 => Some(if shift {
            Shortcut::Pan { x: 1, y: 0 }
        } else {
            Shortcut::Pan { x: 0, y: 1 }
        }),
        0x7a | 0x5a => Some(Shortcut::Undo),
        _ => None,
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn shortcuts_require_both_modifiers_and_leave_typing_alone() {
        assert_eq!(decode(true, true, false, 0x1008fe08), Some(Shortcut::Float));
        assert_eq!(decode(true, true, false, 0x1008fe09), Some(Shortcut::Restore));
        assert_eq!(decode(true, true, false, 0x1008fe0a), Some(Shortcut::Maximize));
        assert_eq!(decode(false, true, false, 0x1008fe0a), None);
        assert_eq!(function_key(0x1008fe01), 0xffbe);
        assert_eq!(function_key(0x1008fe06), 0xffc3);
        assert_eq!(
            decode(true, true, false, 0xff09),
            Some(Shortcut::Cycle(false))
        );
        assert_eq!(
            decode(true, true, true, 0xfe20),
            Some(Shortcut::Cycle(true))
        );
        assert_eq!(
            decode(true, true, true, 0xff53),
            Some(Shortcut::Nudge {
                x: 20,
                y: 0,
                resize: true
            })
        );
        assert_eq!(decode(true, false, false, 0x7a), None);
        assert_eq!(decode(false, true, false, 0xffc7), None);
        assert_eq!(decode(true, true, false, 0x61), None);
    }
}
