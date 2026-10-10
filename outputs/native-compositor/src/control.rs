//! Same-login control socket. Parsing and slow clients stay off the render loop.
use serde_json::{json, Value};
use std::{
    io::{BufRead, BufReader, Read, Write},
    os::unix::{fs::PermissionsExt, net::UnixListener},
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc::{self, Receiver, SyncSender},
        Arc,
    },
    thread,
    time::{Duration, Instant},
};
pub struct Request {
    pub value: Value,
    pub reply: SyncSender<Value>,
    pub deadline: Option<Instant>,
}
impl Request {
    pub fn expired(&self) -> bool {
        self.deadline
            .map(|deadline| Instant::now() >= deadline)
            .unwrap_or(false)
    }
}
pub struct Control {
    pub requests: Receiver<Request>,
    pub path: PathBuf,
    stop: Arc<AtomicBool>,
    worker: Option<thread::JoinHandle<()>>,
}
impl Control {
    pub fn start() -> std::io::Result<Self> {
        let runtime = std::env::var_os("XDG_RUNTIME_DIR")
            .ok_or_else(|| std::io::Error::other("XDG_RUNTIME_DIR required"))?;
        let path =
            PathBuf::from(runtime).join(format!("agentos-compositor-{}.sock", std::process::id()));
        Self::start_at(path)
    }
    fn start_at(path: PathBuf) -> std::io::Result<Self> {
        let listener = UnixListener::bind(&path)?;
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))?;
        listener.set_nonblocking(true)?;
        let (sender, requests) = mpsc::sync_channel(32);
        let stop = Arc::new(AtomicBool::new(false));
        let stopping = stop.clone();
        let worker = thread::spawn(move || {
            while !stopping.load(Ordering::Relaxed) {
                match listener.accept() {
                    Ok((mut stream, _)) => {
                        let _ = stream.set_read_timeout(Some(Duration::from_millis(200)));
                        let _ = stream.set_write_timeout(Some(Duration::from_millis(200)));
                        let mut line = String::new();
                        let parsed = BufReader::new(&mut stream)
                            .take(65537)
                            .read_line(&mut line)
                            .ok()
                            .filter(|_| line.len() <= 65536 && line.ends_with('\n'))
                            .and_then(|_| serde_json::from_str::<Value>(&line).ok());
                        let result = if let Some(value) = parsed {
                            let (reply, rx) = mpsc::sync_channel(1);
                            if sender
                                .try_send(Request {
                                    value,
                                    reply,
                                    deadline: Some(Instant::now() + Duration::from_millis(500)),
                                })
                                .is_ok()
                            {
                                rx.recv_timeout(Duration::from_millis(500)).unwrap_or_else(
                                    |_| json!({"ok":false,"error":"Compositor unavailable"}),
                                )
                            } else {
                                json!({"ok":false,"error":"Compositor busy"})
                            }
                        } else {
                            json!({"ok":false,"error":"Invalid request"})
                        };
                        let _ = writeln!(stream, "{}", result);
                    }
                    Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                        thread::sleep(Duration::from_millis(10))
                    }
                    Err(_) => break,
                }
            }
        });
        Ok(Self {
            requests,
            path,
            stop,
            worker: Some(worker),
        })
    }
}
impl Drop for Control {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
        let _ = std::fs::remove_file(&self.path);
    }
}
pub fn handle(state: &mut crate::Smallvil, v: &Value) -> Value {
    use smithay::reexports::wayland_server::Resource;
    let result = (|| -> Result<Value, String> {
        match v["op"].as_str() {
            Some("snapshot") => {
                state.arrange();
                let windows=state.space.elements().map(|w|{let surface=w.toplevel().unwrap().wl_surface();let (title,app_id)=smithay::wayland::compositor::with_states(surface,|states|{let data=states.data_map.get::<smithay::wayland::shell::xdg::XdgToplevelSurfaceData>().unwrap().lock().unwrap();(data.title.clone(),data.app_id.clone())});let geometry=state.space.element_geometry(w);json!({"id":format!("{:?}",surface.id()),"title":title,"app_id":app_id,"geometry":geometry.map(|r|json!({"x":r.loc.x,"y":r.loc.y,"width":r.size.w,"height":r.size.h}))})}).collect::<Vec<_>>();
                let outputs=state.space.outputs().filter_map(|output|state.space.output_geometry(output).map(|geometry|json!({"name":output.name(),"x":geometry.loc.x,"y":geometry.loc.y,"width":geometry.size.w,"height":geometry.size.h,"scale":output.current_scale().fractional_scale(),"transform":format!("{:?}",output.current_transform())}))).collect::<Vec<_>>();
                let scene = state
                    .bridge
                    .as_ref()
                    .map(|b| b.scene.lock().unwrap().clone());
                let seat_focus = state
                    .seat
                    .get_keyboard()
                    .and_then(|keyboard| keyboard.current_focus())
                    .map(|surface| format!("{:?}", surface.id()));
                Ok(
                    json!({"seat_focus":seat_focus,"pointer_location":state.seat.get_pointer().map(|pointer|{let point=pointer.current_location();json!([point.x,point.y])}),"layout":state.policy.current,"windows":windows,"outputs":outputs,"direct_frames_presented":state.direct_frames_presented,"direct_active":state.direct_active,"direct_resume_error":state.direct_resume_error,"shared":scene.map(|s|json!({"identities":s.identities,"workspaces":s.workspaces,"error":s.error,"overview":s.overview}))}),
                )
            }
            Some("viewport.pan") => {
                let id = v["id"].as_str().ok_or("View ID required")?;
                let x = v["x"]
                    .as_i64()
                    .filter(|n| (-1..=1).contains(n))
                    .ok_or("Horizontal step must be -1, 0 or 1")?;
                let y = v["y"]
                    .as_i64()
                    .filter(|n| (-1..=1).contains(n))
                    .ok_or("Vertical step must be -1, 0 or 1")?;
                state.pan_view(id, x as i32, y as i32)?;
                state.arrange();
                Ok(json!({"view":id,"viewport_offset":state.viewport_offsets.get(id)}))
            }
            Some("place") => {
                if state.bridge.is_some() {
                    return Err("Use workspace.apply with an exact document revision".into());
                }
                let id = v["id"].as_str().ok_or("Window ID required")?;
                let expected = v["expected_revision"].as_u64().ok_or("Revision required")?;
                let placement = serde_json::from_value(v["placement"].clone())
                    .map_err(|_| "Invalid placement")?;
                state.policy.change(id, placement, expected)?;
                state.arrange();
                Ok(json!({"revision":state.policy.current.revision}))
            }
            Some("undo") => {
                if state.bridge.is_some() {
                    return Err("Use workspace.undo with a journal event cursor".into());
                }
                if v["expected_revision"].as_u64() != Some(state.policy.current.revision) {
                    return Err("Layout changed".into());
                }
                state.policy.undo()?;
                state.arrange();
                Ok(json!({"revision":state.policy.current.revision}))
            }
            Some("focus") => {
                if state.bridge.is_some() {
                    return Err("Use workspace.apply to persist focus".into());
                }
                let id = v["id"].as_str().ok_or("Window ID required")?;
                if v["expected_revision"].as_u64() != Some(state.policy.current.revision) {
                    return Err("Layout changed".into());
                }
                let window = state
                    .space
                    .elements()
                    .find(|w| format!("{:?}", w.toplevel().unwrap().wl_surface().id()) == id)
                    .cloned()
                    .ok_or("Window unavailable")?;
                state.space.raise_element(&window, true);
                let keyboard = state.seat.get_keyboard().ok_or("Keyboard unavailable")?;
                keyboard.set_focus(
                    state,
                    Some(window.toplevel().unwrap().wl_surface().clone()),
                    smithay::utils::SERIAL_COUNTER.next_serial(),
                );
                state.policy.current.focus = Some(id.into());
                state.policy.current.revision += 1;
                Ok(json!({"revision":state.policy.current.revision}))
            }
            Some("shutdown") => {
                state.loop_signal.stop();
                Ok(json!({"status":"stopping"}))
            }
            _ => Err("Unknown compositor operation".into()),
        }
    })();
    match result {
        Ok(value) => json!({"ok":true,"result":value}),
        Err(error) => json!({"ok":false,"error":error}),
    }
}

#[cfg(test)]
mod deadline_tests {
    use super::*;
    #[test]
    fn socket_timeout_expires_the_request_still_waiting_in_the_render_queue() {
        use std::os::unix::net::UnixStream;
        let path = std::env::temp_dir().join(format!(
            "agentos-control-deadline-{}.sock",
            std::process::id()
        ));
        let control = Control::start_at(path.clone()).unwrap();
        let mut stream = UnixStream::connect(&path).unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(3)))
            .unwrap();
        writeln!(stream, "{}", json!({"op":"undo","expected_revision":1})).unwrap();
        // Keep the render loop stalled while the actual socket worker times out.
        let mut line = String::new();
        BufReader::new(stream).read_line(&mut line).unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(&line).unwrap()["error"],
            "Compositor unavailable"
        );
        let request = control
            .requests
            .recv_timeout(Duration::from_secs(1))
            .unwrap();
        assert!(
            request.expired(),
            "A timed-out command must be skipped on dequeue"
        );
        drop(control);
        assert!(!path.exists(), "Control worker/socket must be cleaned up");
    }
}
