// SPDX-License-Identifier: Apache-2.0
//! Merge device key transitions into one logical seat without premature release.
use std::collections::{BTreeMap, BTreeSet};

#[derive(Default)]
pub struct PhysicalKeys {
    devices: BTreeMap<String, BTreeSet<u32>>,
}

impl PhysicalKeys {
    fn held(&self, key: u32) -> bool {
        self.devices.values().any(|keys| keys.contains(&key))
    }

    /// Return whether the logical seat must receive this press or release.
    pub fn transition(&mut self, device: &str, key: u32, pressed: bool) -> bool {
        if pressed {
            let already_held = self.held(key);
            self.devices.entry(device.into()).or_default().insert(key) && !already_held
        } else {
            let removed = self
                .devices
                .get_mut(device)
                .is_some_and(|keys| keys.remove(&key));
            if self.devices.get(device).is_some_and(BTreeSet::is_empty) {
                self.devices.remove(device);
            }
            removed && !self.held(key)
        }
    }

    /// Release only keys whose last owning device disappeared.
    pub fn remove_device(&mut self, device: &str) -> Vec<u32> {
        self.devices
            .remove(device)
            .unwrap_or_default()
            .into_iter()
            .filter(|key| !self.held(*key))
            .collect()
    }

    pub fn is_empty(&self) -> bool {
        self.devices.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn overlapping_keys_have_one_seat_press_and_only_the_last_release() {
        let mut keys = PhysicalKeys::default();
        assert!(keys.transition("keyboard-a", 50, true));
        assert!(!keys.transition("keyboard-b", 50, true));
        assert!(!keys.transition("keyboard-a", 50, false));
        assert!(
            !keys.is_empty(),
            "The second physical Shift must still block synthetic strokes"
        );
        assert!(keys.transition("keyboard-b", 50, false));
        assert!(keys.is_empty());
    }

    #[test]
    fn repeated_press_and_unknown_release_do_not_change_another_owner() {
        let mut keys = PhysicalKeys::default();
        assert!(keys.transition("keyboard-a", 50, true));
        assert!(!keys.transition("keyboard-a", 50, true));
        assert!(!keys.transition("keyboard-b", 50, false));
        assert!(keys.remove_device("unknown").is_empty());
        assert!(!keys.is_empty());
        assert!(keys.transition("keyboard-a", 50, false));
        assert!(!keys.transition("keyboard-a", 50, false));
        assert!(keys.is_empty());
    }

    #[test]
    fn removing_a_device_releases_only_its_unshared_keys() {
        let mut keys = PhysicalKeys::default();
        assert!(keys.transition("keyboard-a", 50, true));
        assert!(keys.transition("keyboard-a", 38, true));
        assert!(!keys.transition("keyboard-b", 50, true));
        assert!(keys.transition("keyboard-b", 56, true));
        assert_eq!(keys.remove_device("keyboard-a"), vec![38]);
        assert!(!keys.is_empty());
        assert_eq!(keys.remove_device("keyboard-b"), vec![50, 56]);
        assert!(keys.is_empty());
        assert!(
            keys.transition("keyboard-a", 50, true),
            "A reused device ID starts without stale owners"
        );
    }

    #[test]
    fn unrelated_keys_are_forwarded_independently_of_total_seat_count() {
        let mut keys = PhysicalKeys::default();
        assert!(keys.transition("keyboard-a", 50, true));
        assert!(keys.transition("keyboard-b", 38, true));
        assert!(keys.transition("keyboard-b", 38, false));
        assert!(!keys.is_empty());
        assert!(keys.transition("keyboard-a", 50, false));
        assert!(keys.is_empty());
    }
}
