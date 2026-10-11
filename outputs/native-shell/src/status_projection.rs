//! Adapt bounded host observations to the released StatusView contract.
use super::ui;
use std::borrow::Cow;

const MAX_BYTES: usize = 65_536;
const TRUNCATED: &str = "\n… (display truncated)";

fn literal(value: &str) -> Cow<'_, str> {
    if value.len() <= MAX_BYTES && !value.contains('\0') {
        return Cow::Borrowed(value);
    }
    let mut text = String::with_capacity(value.len().min(MAX_BYTES));
    for character in value.chars() {
        let character = if character == '\0' { '␀' } else { character };
        if text.len() + character.len_utf8() > MAX_BYTES {
            while text.len() > MAX_BYTES - TRUNCATED.len() {
                text.pop();
            }
            text.push_str(TRUNCATED);
            return Cow::Owned(text);
        }
        text.push(character);
    }
    Cow::Owned(text)
}

pub fn update(view: &ui::StatusView, value: &str) {
    view.reconcile(&literal(value))
        .expect("Normalized status must satisfy the pinned StatusView text contract");
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn host_observations_preserve_unicode_and_bound_display_without_nul() {
        assert!(matches!(literal("λ 日本語"), Cow::Borrowed(_)));
        assert_eq!(literal("before\0after"), "before␀after");
        assert_eq!(literal(&"x".repeat(MAX_BYTES)).len(), MAX_BYTES);
        for raw in ["日本語".repeat(30_000), "\0".repeat(MAX_BYTES)] {
            let text = literal(&raw);
            assert!(text.len() <= MAX_BYTES && !text.contains('\0'));
            assert!(text.ends_with(TRUNCATED));
            assert!(text.is_char_boundary(text.len() - TRUNCATED.len()));
        }
    }
}
