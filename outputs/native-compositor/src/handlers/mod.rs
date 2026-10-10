mod compositor;
mod input_method;
mod xdg_shell;

use crate::Smallvil;

//
// Wl Seat
//

use smithay::input::{Seat, SeatHandler, SeatState};
use smithay::reexports::wayland_server::protocol::wl_surface::WlSurface;
use smithay::reexports::wayland_server::Resource;
use smithay::wayland::output::OutputHandler;
use smithay::wayland::selection::data_device::{
    set_data_device_focus, ClientDndGrabHandler, DataDeviceHandler, DataDeviceState,
    ServerDndGrabHandler,
};
use smithay::wayland::selection::primary_selection::{
    set_primary_focus, PrimarySelectionHandler, PrimarySelectionState,
};
use smithay::wayland::selection::SelectionHandler;
use smithay::{delegate_data_device, delegate_output, delegate_seat};

impl SeatHandler for Smallvil {
    type KeyboardFocus = WlSurface;
    type PointerFocus = WlSurface;
    type TouchFocus = WlSurface;

    fn seat_state(&mut self) -> &mut SeatState<Smallvil> {
        &mut self.seat_state
    }

    fn cursor_image(
        &mut self,
        _seat: &Seat<Self>,
        image: smithay::input::pointer::CursorImageStatus,
    ) {
        self.cursor_image = image;
    }

    fn focus_changed(&mut self, seat: &Seat<Self>, focused: Option<&WlSurface>) {
        let focus = focused.map(|s| format!("{:?}", s.id()));
        if focus
            .as_ref()
            .map(|id| self.policy.current.placements.contains_key(id))
            .unwrap_or(true)
            && self.policy.current.focus != focus
        {
            if self.applied_focus != focus {
                if let (Some(bridge), Some(runtime)) = (&self.bridge, focus.as_ref()) {
                    bridge.input(
                        runtime,
                        serde_json::json!({"kind":"focus","element_id":null}),
                    );
                }
            }
            self.policy.current.focus = focus;
            self.policy.current.revision += 1;
        }
        let dh = &self.display_handle;
        let client = focused.and_then(|s| dh.get_client(s.id()).ok());
        set_data_device_focus(dh, seat, client.clone());
        set_primary_focus(dh, seat, client);
    }
}

delegate_seat!(Smallvil);
smithay::delegate_relative_pointer!(Smallvil);

//
// Wl Data Device
//

impl SelectionHandler for Smallvil {
    type SelectionUserData = ();
}

impl DataDeviceHandler for Smallvil {
    fn data_device_state(&self) -> &DataDeviceState {
        &self.data_device_state
    }
}

impl ClientDndGrabHandler for Smallvil {
    fn started(
        &mut self,
        _source: Option<smithay::reexports::wayland_server::protocol::wl_data_source::WlDataSource>,
        icon: Option<WlSurface>,
        _seat: Seat<Self>,
    ) {
        self.drag_icon = icon;
    }
    fn dropped(&mut self, _target: Option<WlSurface>, _validated: bool, _seat: Seat<Self>) {
        self.drag_icon = None;
    }
}
impl ServerDndGrabHandler for Smallvil {}

delegate_data_device!(Smallvil);

impl PrimarySelectionHandler for Smallvil {
    fn primary_selection_state(&self) -> &PrimarySelectionState {
        &self.primary_selection_state
    }
}
smithay::delegate_primary_selection!(Smallvil);

//
// Wl Output & Xdg Output
//

impl OutputHandler for Smallvil {}
delegate_output!(Smallvil);
