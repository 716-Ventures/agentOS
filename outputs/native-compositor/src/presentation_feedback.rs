//! Frame-scoped Wayland presentation receipts, collected from actual render states.
//! Uses Smithay's Anvil helpers (MIT); see LICENSE-SMITHAY.
use crate::Smallvil;
use smithay::{
    backend::renderer::element::{default_primary_scanout_output_compare, RenderElementStates},
    desktop::utils::{
        surface_presentation_feedback_flags_from_states, surface_primary_scanout_output,
        take_presentation_feedback_surface_tree, update_surface_primary_scanout_output,
        with_surfaces_surface_tree, OutputPresentationFeedback,
    },
    input::pointer::CursorImageStatus,
    output::Output,
    reexports::wayland_server::protocol::wl_surface::WlSurface,
    wayland::compositor::SurfaceData,
};

pub fn collect(
    state: &Smallvil,
    output: &Output,
    rendered: &RenderElementStates,
) -> OutputPresentationFeedback {
    let update = |surface: &WlSurface, data: &SurfaceData| {
        update_surface_primary_scanout_output(
            surface,
            output,
            data,
            rendered,
            default_primary_scanout_output_compare,
        );
    };
    for window in state.space.elements() {
        window.with_surfaces(update);
    }
    if let CursorImageStatus::Surface(surface) = &state.cursor_image {
        with_surfaces_surface_tree(surface, update);
    }
    if let Some(surface) = &state.drag_icon {
        with_surfaces_surface_tree(surface, update);
    }
    let mut feedback = OutputPresentationFeedback::new(output);
    for window in state.space.elements() {
        if state.space.outputs_for_element(window).contains(output) {
            window.take_presentation_feedback(
                &mut feedback,
                surface_primary_scanout_output,
                |surface, _| surface_presentation_feedback_flags_from_states(surface, rendered),
            );
        }
    }
    for surface in state.drag_icon.iter().chain(match &state.cursor_image {
        CursorImageStatus::Surface(surface) => Some(surface),
        _ => None,
    }) {
        take_presentation_feedback_surface_tree(
            surface,
            &mut feedback,
            surface_primary_scanout_output,
            |surface, _| surface_presentation_feedback_flags_from_states(surface, rendered),
        );
    }
    feedback
}
