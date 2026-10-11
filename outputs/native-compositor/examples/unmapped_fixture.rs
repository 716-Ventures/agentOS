//! Test-only unbuffered toplevel. Never installed in the runtime.
use std::time::{Duration, Instant};
use wayland_client::{
    protocol::{wl_compositor, wl_registry, wl_surface},
    Connection, Dispatch, QueueHandle,
};
use wayland_protocols::xdg::shell::client::{xdg_surface, xdg_toplevel, xdg_wm_base};
#[derive(Default)]
struct Fixture {
    compositor: Option<wl_compositor::WlCompositor>,
    shell: Option<xdg_wm_base::XdgWmBase>,
    configured: bool,
}
impl Dispatch<wl_registry::WlRegistry, ()> for Fixture {
    fn event(
        state: &mut Self,
        registry: &wl_registry::WlRegistry,
        event: wl_registry::Event,
        _: &(),
        _: &Connection,
        qh: &QueueHandle<Self>,
    ) {
        if let wl_registry::Event::Global {
            name,
            interface,
            version,
        } = event
        {
            match interface.as_str() {
                "wl_compositor" => {
                    state.compositor = Some(registry.bind(name, version.min(4), qh, ()))
                }
                "xdg_wm_base" => state.shell = Some(registry.bind(name, version.min(2), qh, ())),
                _ => {}
            }
        }
    }
}
impl Dispatch<xdg_wm_base::XdgWmBase, ()> for Fixture {
    fn event(
        _: &mut Self,
        shell: &xdg_wm_base::XdgWmBase,
        event: xdg_wm_base::Event,
        _: &(),
        _: &Connection,
        _: &QueueHandle<Self>,
    ) {
        if let xdg_wm_base::Event::Ping { serial } = event {
            shell.pong(serial);
        }
    }
}
impl Dispatch<xdg_surface::XdgSurface, ()> for Fixture {
    fn event(
        state: &mut Self,
        surface: &xdg_surface::XdgSurface,
        event: xdg_surface::Event,
        _: &(),
        _: &Connection,
        _: &QueueHandle<Self>,
    ) {
        if let xdg_surface::Event::Configure { serial } = event {
            surface.ack_configure(serial);
            state.configured = true;
        }
    }
}
wayland_client::delegate_noop!(Fixture: ignore wl_compositor::WlCompositor);
wayland_client::delegate_noop!(Fixture: ignore wl_surface::WlSurface);
wayland_client::delegate_noop!(Fixture: ignore xdg_toplevel::XdgToplevel);
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let connection = Connection::connect_to_env()?;
    let mut queue = connection.new_event_queue::<Fixture>();
    let qh = queue.handle();
    connection.display().get_registry(&qh, ());
    let mut state = Fixture::default();
    queue.roundtrip(&mut state)?;
    let surface = state
        .compositor
        .as_ref()
        .ok_or("Compositor missing")?
        .create_surface(&qh, ());
    let xdg = state
        .shell
        .as_ref()
        .ok_or("Shell missing")?
        .get_xdg_surface(&surface, &qh, ());
    let toplevel = xdg.get_toplevel(&qh, ());
    toplevel.set_title("Unmapped fixture".into());
    toplevel.set_app_id("com.agentos.UnmappedFixture".into());
    surface.commit(); // Negotiate configure, but never attach a buffer.
    let deadline = Instant::now() + Duration::from_secs(10);
    while Instant::now() < deadline {
        queue.roundtrip(&mut state)?;
        if state.configured {
            if let Some(path) = std::env::args().nth(1) {
                std::fs::write(path, b"configured")?;
            }
            state.configured = false;
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    Ok(())
}
