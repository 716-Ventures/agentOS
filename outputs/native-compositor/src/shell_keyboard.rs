//! A private, bounded input path for the host-selected renderer.
//! Each request completes its press/release sequence in one event-loop turn.
use crate::Smallvil;
use serde_json::{json, Value};
use smithay::{
    backend::input::{KeyState, Keycode},
    desktop::layer_map_for_output,
    reexports::wayland_server::Resource,
};

fn stroke(code: u64, modifiers: u64) -> Result<Vec<u32>, &'static str> {
    // XKB keycodes include the evdev offset of eight. Modifier keys belong to
    // the atomic chord, never to a separately held virtual key.
    if !(9..=255).contains(&code)
        || [37, 50, 62, 64, 105, 108, 118, 133, 134].contains(&code)
        || modifiers & !29 != 0
    {
        return Err("Unsupported keyboard stroke");
    }
    let mut keys = Vec::new();
    for (mask, key) in [(1, 50), (4, 37), (8, 64), (16, 118)] {
        if modifiers & mask != 0 {
            keys.push(key);
        }
    }
    keys.push(code as u32);
    Ok(keys)
}

pub fn handle(state: &mut Smallvil, peer: Option<u32>, value: &Value) -> Value {
    let result = (|| -> Result<Value, String> {
        let (pid, start) = state
            .shell_identity
            .as_ref()
            .ok_or("Trusted renderer unavailable")?;
        if peer != Some(*pid) {
            return Err("Trusted renderer required".into());
        }
        let stat = std::fs::read_to_string(format!("/proc/{pid}/stat"))
            .map_err(|_| "Trusted renderer exited")?;
        if stat
            .rsplit_once(')')
            .and_then(|(_, tail)| tail.split_whitespace().next())
            .is_some_and(|state| matches!(state, "Z" | "X"))
        {
            return Err("Trusted renderer exited".into());
        }
        if stat
            .rsplit_once(')')
            .and_then(|(_, tail)| tail.split_whitespace().nth(19))
            != Some(start.as_str())
        {
            return Err("Trusted renderer identity changed".into());
        }
        let keyboard = state.seat.get_keyboard().ok_or("Keyboard unavailable")?;
        if keyboard
            .current_focus()
            .as_ref()
            .is_some_and(|surface| crate::system_shell::is_bar(state, surface))
        {
            if let Some(surface) = state.shell_return_focus.take().filter(Resource::is_alive) {
                keyboard.set_focus(
                    state,
                    Some(surface),
                    smithay::utils::SERIAL_COUNTER.next_serial(),
                );
            } else {
                state.applied_focus = None;
                state.arrange();
            }
        }
        if value["op"] == "keyboard.restore_focus" {
            return Ok(json!({}));
        }
        if state.direct_active == Some(false) {
            return Err("Display is inactive".into());
        }
        let mapped = state.space.outputs().any(|output| {
            layer_map_for_output(output).layers().any(|layer| {
                layer.namespace() == "agentos-keyboard"
                    && smithay::backend::renderer::utils::with_renderer_surface_state(
                        layer.wl_surface(),
                        |surface| surface.buffer().is_some(),
                    )
                    .unwrap_or(false)
            })
        });
        if !mapped {
            return Err("On-screen keyboard is hidden".into());
        }
        if !state.physical_keys.is_empty() || !keyboard.pressed_keys().is_empty() {
            return Err("Release physical keys before using the on-screen keyboard".into());
        }
        let target = keyboard
            .current_focus()
            .filter(Resource::is_alive)
            .ok_or("Select a field or application first")?;
        if crate::system_shell::is_bar(state, &target)
            || crate::system_shell::is_keyboard(state, &target)
        {
            return Err("Select a field or application first".into());
        }
        let keys = stroke(
            value["keycode"].as_u64().ok_or("Keycode required")?,
            value["modifiers"].as_u64().ok_or("Modifiers required")?,
        )?;
        let mut now = libc::timespec {
            tv_sec: 0,
            tv_nsec: 0,
        };
        if unsafe { libc::clock_gettime(libc::CLOCK_MONOTONIC, &mut now) } != 0 {
            return Err("Input clock unavailable".into());
        }
        let time = (now.tv_sec as u64 * 1000 + now.tv_nsec as u64 / 1_000_000) as u32;
        for code in &keys {
            state.process_keyboard(Keycode::new(*code), KeyState::Pressed, time);
        }
        for code in keys.iter().rev() {
            state.process_keyboard(Keycode::new(*code), KeyState::Released, time);
        }
        Ok(json!({"target":format!("{:?}",target.id())}))
    })();
    match result {
        Ok(value) => json!({"ok":true,"result":value}),
        Err(error) => json!({"ok":false,"error":error}),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn chords_are_bounded_and_never_duplicate_a_held_modifier() {
        assert_eq!(stroke(38, 29), Ok(vec![50, 37, 64, 118, 38]));
        assert_eq!(stroke(38, 0), Ok(vec![38]));
        for code in [0, 8, 37, 50, 62, 64, 105, 108, 118, 133, 134, 256, u64::MAX] {
            assert!(stroke(code, 0).is_err());
        }
        for mask in [2, 32, 255, u64::MAX] {
            assert!(stroke(38, mask).is_err());
        }
    }
}
