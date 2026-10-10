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
}
pub fn decode(ctrl: bool, alt: bool, shift: bool, key: u32) -> Option<Shortcut> {
    if !ctrl || !alt {
        return None;
    }
    match key {
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
        0x7a | 0x5a => Some(Shortcut::Undo),
        _ => None,
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn shortcuts_require_both_modifiers_and_leave_typing_alone() {
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
