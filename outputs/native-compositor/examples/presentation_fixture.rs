//! Private real-Wayland receipt fixture; never installed in the runtime.
use std::{
    fs::File,
    io::{BufRead, BufReader, Read, Write},
    os::{
        fd::{AsFd, FromRawFd},
        unix::{
            fs::{FileExt, PermissionsExt},
            net::UnixListener,
        },
    },
    path::PathBuf,
    time::{Duration, Instant},
};
use wayland_client::{
    protocol::{
        wl_buffer, wl_compositor, wl_keyboard, wl_registry, wl_seat, wl_shm, wl_shm_pool,
        wl_surface,
    },
    Connection, Dispatch, QueueHandle, WEnum,
};
use wayland_protocols::{
    wp::presentation_time::client::{wp_presentation, wp_presentation_feedback},
    xdg::shell::client::{xdg_surface, xdg_toplevel, xdg_wm_base},
};

#[derive(Default)]
struct Fixture {
    compositor: Option<wl_compositor::WlCompositor>,
    shell: Option<xdg_wm_base::XdgWmBase>,
    shm: Option<wl_shm::WlShm>,
    presentation: Option<wp_presentation::WpPresentation>,
    surface: Option<wl_surface::WlSurface>,
    clock_id: Option<u32>,
    configured: bool,
    mapped: bool,
    next: u64,
    receipts: Vec<serde_json::Value>,
}
#[derive(Clone, Copy)]
struct Receipt {
    id: u64,
    key_time: Option<u32>,
}
impl Fixture {
    fn request(&mut self, qh: &QueueHandle<Self>, key_time: Option<u32>) -> u64 {
        self.next += 1;
        self.presentation.as_ref().unwrap().feedback(
            self.surface.as_ref().unwrap(),
            qh,
            Receipt {
                id: self.next,
                key_time,
            },
        );
        self.next
    }
    fn draw(
        &mut self,
        qh: &QueueHandle<Self>,
        key_time: Option<u32>,
    ) -> Result<u64, Box<dyn std::error::Error>> {
        let fd = unsafe {
            libc::memfd_create(c"agentos-presentation-fixture".as_ptr(), libc::MFD_CLOEXEC)
        };
        if fd < 0 {
            return Err(std::io::Error::last_os_error().into());
        }
        let storage = unsafe { File::from_raw_fd(fd) };
        const SIZE: i32 = 64 * 64 * 4;
        storage.set_len(SIZE as u64)?;
        let color = if self.next % 2 == 0 {
            [0x20, 0xc0, 0x20, 0xff]
        } else {
            [0xc0, 0x20, 0x20, 0xff]
        };
        storage.write_all_at(&color.repeat(64 * 64), 0)?;
        let pool = self
            .shm
            .as_ref()
            .unwrap()
            .create_pool(storage.as_fd(), SIZE, qh, ());
        let buffer = pool.create_buffer(0, 64, 64, 64 * 4, wl_shm::Format::Xrgb8888, qh, ());
        pool.destroy();
        let id = self.request(qh, key_time);
        let surface = self.surface.as_ref().unwrap();
        surface.attach(Some(&buffer), 0, 0);
        surface.damage_buffer(0, 0, 64, 64);
        surface.commit();
        self.mapped = true;
        Ok(id)
    }
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
                "wl_shm" => state.shm = Some(registry.bind(name, 1, qh, ())),
                "wp_presentation" => {
                    state.presentation = Some(registry.bind(name, version.min(2), qh, ()))
                }
                "wl_seat" => {
                    let _: wl_seat::WlSeat = registry.bind(name, version.min(7), qh, ());
                }
                _ => {}
            }
        }
    }
}
impl Dispatch<wl_seat::WlSeat, ()> for Fixture {
    fn event(
        _: &mut Self,
        seat: &wl_seat::WlSeat,
        event: wl_seat::Event,
        _: &(),
        _: &Connection,
        qh: &QueueHandle<Self>,
    ) {
        if let wl_seat::Event::Capabilities {
            capabilities: WEnum::Value(caps),
        } = event
        {
            if caps.contains(wl_seat::Capability::Keyboard) {
                seat.get_keyboard(qh, ());
            }
        }
    }
}
impl Dispatch<wl_keyboard::WlKeyboard, ()> for Fixture {
    fn event(
        state: &mut Self,
        _: &wl_keyboard::WlKeyboard,
        event: wl_keyboard::Event,
        _: &(),
        _: &Connection,
        qh: &QueueHandle<Self>,
    ) {
        if let wl_keyboard::Event::Key {
            time,
            state: WEnum::Value(wl_keyboard::KeyState::Pressed),
            ..
        } = event
        {
            if state.mapped {
                state
                    .draw(qh, Some(time))
                    .expect("Fixture buffer allocation");
            }
        }
    }
}
impl Dispatch<wp_presentation::WpPresentation, ()> for Fixture {
    fn event(
        state: &mut Self,
        _: &wp_presentation::WpPresentation,
        event: wp_presentation::Event,
        _: &(),
        _: &Connection,
        _: &QueueHandle<Self>,
    ) {
        if let wp_presentation::Event::ClockId { clk_id } = event {
            state.clock_id = Some(clk_id);
        }
    }
}
impl Dispatch<wp_presentation_feedback::WpPresentationFeedback, Receipt> for Fixture {
    fn event(
        state: &mut Self,
        _: &wp_presentation_feedback::WpPresentationFeedback,
        event: wp_presentation_feedback::Event,
        data: &Receipt,
        _: &Connection,
        _: &QueueHandle<Self>,
    ) {
        match event {
            wp_presentation_feedback::Event::Presented {
                tv_sec_hi,
                tv_sec_lo,
                tv_nsec,
                refresh,
                seq_hi,
                seq_lo,
                flags,
            } => {
                let timestamp = ((u64::from(tv_sec_hi) << 32) | u64::from(tv_sec_lo))
                    * 1_000_000_000
                    + u64::from(tv_nsec);
                state.receipts.push(serde_json::json!({"id":data.id,"kind":"presented","time_ns":timestamp,"refresh_ns":refresh,"sequence":(u64::from(seq_hi)<<32)|u64::from(seq_lo),"flags":flags.into_result().map(|f|f.bits()).unwrap_or(0),"key_time_ms":data.key_time}));
            }
            wp_presentation_feedback::Event::Discarded => state
                .receipts
                .push(serde_json::json!({"id":data.id,"kind":"discarded"})),
            _ => {}
        }
        assert!(state.receipts.len() <= 256, "Fixture receipt bound");
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
impl Dispatch<wl_buffer::WlBuffer, ()> for Fixture {
    fn event(
        _: &mut Self,
        buffer: &wl_buffer::WlBuffer,
        event: wl_buffer::Event,
        _: &(),
        _: &Connection,
        _: &QueueHandle<Self>,
    ) {
        if let wl_buffer::Event::Release = event {
            buffer.destroy();
        }
    }
}
wayland_client::delegate_noop!(Fixture: ignore wl_compositor::WlCompositor);
wayland_client::delegate_noop!(Fixture: ignore wl_surface::WlSurface);
wayland_client::delegate_noop!(Fixture: ignore wl_shm::WlShm);
wayland_client::delegate_noop!(Fixture: ignore wl_shm_pool::WlShmPool);
wayland_client::delegate_noop!(Fixture: ignore xdg_toplevel::XdgToplevel);
struct Socket(PathBuf);
impl Drop for Socket {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let path = PathBuf::from(std::env::args().nth(1).ok_or("Private socket required")?);
    let connection = Connection::connect_to_env()?;
    let mut queue = connection.new_event_queue::<Fixture>();
    let qh = queue.handle();
    connection.display().get_registry(&qh, ());
    let mut state = Fixture::default();
    queue.roundtrip(&mut state)?;
    if state.presentation.is_none() {
        return Err("Presentation protocol unavailable".into());
    }
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
    toplevel.set_title("Presentation fixture".into());
    toplevel.set_app_id("com.agentos.PresentationFixture".into());
    state.surface = Some(surface.clone());
    state.request(&qh, None);
    surface.commit();
    queue.roundtrip(&mut state)?;
    let listener = UnixListener::bind(&path)?;
    let _owned = Socket(path.clone());
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))?;
    listener.set_nonblocking(true)?;
    let end = Instant::now() + Duration::from_secs(90);
    while Instant::now() < end {
        queue.roundtrip(&mut state)?;
        if let Ok((mut stream, _)) = listener.accept() {
            stream.set_read_timeout(Some(Duration::from_secs(2)))?;
            let mut line = String::new();
            BufReader::new(&stream).take(1025).read_line(&mut line)?;
            if line.len() > 1024 {
                return Err("Oversized fixture request".into());
            }
            let request: serde_json::Value = serde_json::from_str(&line)?;
            let mut id = None;
            let mut stop = false;
            match request["op"].as_str() {
                Some("status") => {}
                Some("map") if state.configured => {
                    id = Some(state.draw(&qh, None)?);
                }
                Some("supersede") if state.mapped => {
                    state.draw(&qh, None)?;
                    id = Some(state.draw(&qh, None)?);
                }
                Some("unmap") => {
                    surface.attach(None, 0, 0);
                    surface.commit();
                    state.mapped = false;
                }
                Some("stop") => stop = true,
                _ => return Err("Invalid fixture request".into()),
            }
            queue.roundtrip(&mut state)?;
            writeln!(
                stream,
                "{}",
                serde_json::json!({"ok":true,"id":id,"clock_id":state.clock_id,"configured":state.configured,"mapped":state.mapped,"receipts":state.receipts})
            )?;
            if stop {
                break;
            }
        }
        std::thread::sleep(Duration::from_millis(2));
    }
    Ok(())
}
