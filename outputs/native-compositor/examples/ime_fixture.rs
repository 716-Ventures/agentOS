//! Test-only input-method client; never installed or used as a real language engine.
use std::{
    io::{BufRead, BufReader, Write},
    os::unix::net::UnixListener,
    path::PathBuf,
    time::{Duration, Instant},
};
use wayland_client::{
    protocol::{wl_registry, wl_seat},
    Connection, Dispatch, QueueHandle,
};
use wayland_protocols_misc::zwp_input_method_v2::client::{
    zwp_input_method_manager_v2, zwp_input_method_v2,
};

#[derive(Default)]
struct Method {
    manager: Option<zwp_input_method_manager_v2::ZwpInputMethodManagerV2>,
    seat: Option<wl_seat::WlSeat>,
    active: bool,
    serial: u32,
}
impl Dispatch<wl_registry::WlRegistry, ()> for Method {
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
                "wl_seat" => state.seat = Some(registry.bind(name, version.min(7), qh, ())),
                "zwp_input_method_manager_v2" => {
                    state.manager = Some(registry.bind(name, 1, qh, ()))
                }
                _ => {}
            }
        }
    }
}
impl Dispatch<zwp_input_method_v2::ZwpInputMethodV2, ()> for Method {
    fn event(
        state: &mut Self,
        _: &zwp_input_method_v2::ZwpInputMethodV2,
        event: zwp_input_method_v2::Event,
        _: &(),
        _: &Connection,
        _: &QueueHandle<Self>,
    ) {
        match event {
            zwp_input_method_v2::Event::Activate => state.active = true,
            zwp_input_method_v2::Event::Deactivate => state.active = false,
            zwp_input_method_v2::Event::Done => state.serial += 1,
            zwp_input_method_v2::Event::Unavailable => panic!("Test input method is unavailable"),
            _ => {}
        }
    }
}
wayland_client::delegate_noop!(Method: ignore wl_seat::WlSeat);
wayland_client::delegate_noop!(Method: ignore zwp_input_method_manager_v2::ZwpInputMethodManagerV2);
struct Socket(PathBuf);
impl Drop for Socket {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let path = PathBuf::from(
        std::env::args()
            .nth(1)
            .ok_or("Private test control socket required")?,
    );
    let connection = Connection::connect_to_env()?;
    let mut queue = connection.new_event_queue::<Method>();
    let qh = queue.handle();
    connection.display().get_registry(&qh, ());
    let mut state = Method::default();
    queue.roundtrip(&mut state)?;
    let input = state
        .manager
        .as_ref()
        .ok_or("Privileged manager not advertised")?
        .get_input_method(state.seat.as_ref().ok_or("Seat missing")?, &qh, ());
    queue.roundtrip(&mut state)?;
    let listener = UnixListener::bind(&path)?;
    let _owned = Socket(path.clone());
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))?;
    listener.set_nonblocking(true)?;
    let end = Instant::now() + Duration::from_secs(90);
    while Instant::now() < end {
        queue.roundtrip(&mut state)?;
        if let Ok((mut stream, _)) = listener.accept() {
            stream.set_read_timeout(Some(Duration::from_secs(2)))?;
            let mut line = String::new();
            // Bounded even if the test driver misbehaves.
            use std::io::Read;
            BufReader::new(&stream).take(1025).read_line(&mut line)?;
            let request: serde_json::Value = serde_json::from_str(&line)?;
            if line.len() > 1024 {
                return Err("Oversized test command".into());
            }
            let mut ok = true;
            match request["op"].as_str() {
                Some("status") => {}
                Some("preedit") if state.active => {
                    let text = request["text"].as_str().ok_or("Text required")?.to_string();
                    input.set_preedit_string(text.clone(), text.len() as i32, text.len() as i32);
                    input.commit(state.serial);
                }
                Some("commit") if state.active => {
                    input.set_preedit_string(String::new(), 0, 0);
                    input.commit_string(
                        request["text"].as_str().ok_or("Text required")?.to_string(),
                    );
                    input.commit(state.serial);
                }
                _ => ok = false,
            }
            queue.roundtrip(&mut state)?;
            writeln!(
                stream,
                "{}",
                serde_json::json!({"ok":ok,"active":state.active,"serial":state.serial})
            )?;
        }
        std::thread::sleep(Duration::from_millis(10));
    }
    Ok(())
}
