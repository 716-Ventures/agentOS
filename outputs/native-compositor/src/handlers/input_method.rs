//! Input methods are privileged; global visibility is restricted in Service::start.
//! Popup handling adapted from Smithay Anvil v0.6.0 (MIT); see LICENSE-SMITHAY.
use crate::Smallvil;
use smithay::{
    desktop::{PopupKind, PopupManager},
    reexports::wayland_server::protocol::wl_surface::WlSurface,
    utils::{Logical, Rectangle},
    wayland::input_method::{InputMethodHandler, PopupSurface},
};

impl InputMethodHandler for Smallvil {
    fn new_popup(&mut self, surface: PopupSurface) {
        if let Err(error) = self.popups.track_popup(PopupKind::from(surface)) {
            eprintln!("Input method popup unavailable: {error}");
        }
    }
    fn dismiss_popup(&mut self, surface: PopupSurface) {
        if let Some(parent) = surface.get_parent().map(|parent| parent.surface.clone()) {
            let _ = PopupManager::dismiss_popup(&parent, &PopupKind::from(surface));
        }
    }
    fn popup_repositioned(&mut self, _: PopupSurface) {}
    fn parent_geometry(&self, parent: &WlSurface) -> Rectangle<i32, Logical> {
        self.space
            .elements()
            .find_map(|window| {
                (window.toplevel().map(|t| t.wl_surface()) == Some(parent))
                    .then(|| window.geometry())
            })
            .unwrap_or_default()
    }
}
smithay::delegate_text_input_manager!(Smallvil);
smithay::delegate_input_method_manager!(Smallvil);
