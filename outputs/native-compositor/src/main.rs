//! Adapted from Smithay smallvil v0.6.0 (MIT); see LICENSE-SMITHAY.
#![allow(irrefutable_let_patterns)]

mod bridge;
mod control;
mod core_ipc;
mod handlers;
mod policy;
mod pressure;
mod process;
mod system_shell;
mod shell_keyboard;
mod shortcuts;
#[path = "../../native-shell/src/timings.rs"]
mod timings;

#[cfg(feature = "direct-display")]
mod direct;
#[cfg(feature = "direct-display")]
mod presentation_feedback;
mod accessibility;
mod frame_cadence;
mod input_frame;
mod grabs;
mod input;
mod input_revision;
mod input_method;
#[cfg(test)]
mod input_method_tests;
#[cfg(feature = "direct-display")]
mod output_config;
mod output_zoom;
mod output_recovery;
mod pointer_geometry;
mod physical_keys;
mod state;
mod winit;

use smithay::reexports::{
    calloop::EventLoop,
    wayland_server::{Display, DisplayHandle},
};
pub use state::Smallvil;

pub struct CalloopData {
    state: Smallvil,
    display_handle: DisplayHandle,
}

static TERMINATE: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);
extern "C" fn terminate(_: libc::c_int) {
    TERMINATE.store(true, std::sync::atomic::Ordering::Relaxed);
}
fn main() -> Result<(), Box<dyn std::error::Error>> {
    if let Ok(env_filter) = tracing_subscriber::EnvFilter::try_from_default_env() {
        tracing_subscriber::fmt().with_env_filter(env_filter).init();
    } else {
        tracing_subscriber::fmt().init();
    }

    unsafe {
        libc::signal(libc::SIGTERM, terminate as libc::sighandler_t);
        libc::signal(libc::SIGINT, terminate as libc::sighandler_t);
    }
    let mut event_loop: EventLoop<CalloopData> = EventLoop::try_new()?;

    let display: Display<Smallvil> = Display::new()?;
    let display_handle = display.handle();
    let state = Smallvil::new(&mut event_loop, display);

    let mut data = CalloopData {
        state,
        display_handle,
    };

    let backend = std::env::var("AGENT_OS_COMPOSITOR_BACKEND").unwrap_or_else(|_| "winit".into());
    match backend.as_str() {
        "winit" => crate::winit::init_winit(&mut event_loop, &mut data)?,
        #[cfg(feature = "direct-display")]
        "drm" => crate::direct::init(&mut event_loop, &mut data)?,
        _ => return Err("Unsupported compositor backend".into()),
    }

    if std::env::var("AGENT_OS_SCREEN_READER").as_deref()==Ok("1") {
        let keyboard=data.state.seat.get_keyboard().unwrap();
        let keymap=keyboard.with_xkb_state(&mut data.state,|context| {
            let xkb=context.xkb().lock().unwrap();
            // Only serialize while borrowed under the keyboard lock; retain no reference.
            unsafe {xkb.keymap().get_as_string(smithay::input::keyboard::xkb::KEYMAP_FORMAT_TEXT_V1)}
        });
        data.state.accessibility=Some(accessibility::Service::start(keymap)?);
    }
    let mut input_method = input_method::Service::start(&mut data.state)?;
    let control = control::Control::start()?;
    std::env::set_var("AGENT_OS_COMPOSITOR_SOCKET", &control.path);
    println!(
        "{}",
        serde_json::json!({"wayland_display":data.state.socket_name.to_string_lossy(),"control_socket":control.path})
    );
    let child = std::sync::Arc::new(std::sync::Mutex::new(None::<std::process::Child>));
    let _owned = process::OwnedChild(child.clone());
    let mut args = std::env::args().skip(1).peekable();
    let trusted_shell=args.peek().is_some_and(|arg|arg=="--trusted-shell");
    if trusted_shell {args.next();}
    if matches!(args.next().as_deref(), Some("-c" | "--command")) {
        if let Some(command) = args.next() {
            let mut renderer = std::process::Command::new(command);
            renderer.args(args);
            if trusted_shell {system_shell::spawn(&mut data.state,&mut renderer,&child)?;} else {
                process::configure_child(&mut renderer);
                *child.lock().unwrap() = Some(renderer.spawn()?);
            }
        }
    }
    event_loop.run(
        Some(std::time::Duration::from_millis(16)),
        &mut data,
        |data| {
            if let Some(service)=&data.state.accessibility {service.dispatch();}
            data.state.wake_input_frame();
            // Core/seat reconciliation must progress when the outer compositor
            // throttles frame callbacks (for example an occluded nested window).
            if backend == "winit" {
                data.state.arrange();
            }
            if let Some(service) = &mut input_method {
                if let Err(error) = service.check() {
                    eprintln!("Input method unavailable: {error}");
                }
            }
            if TERMINATE.load(std::sync::atomic::Ordering::Relaxed) {
                data.state.loop_signal.stop();
            }
            for req in control.requests.try_iter().take(8) {
                if req.expired() {
                    let _ = req.reply.try_send(serde_json::json!({"ok":false,"error":"Input or command expired; try again"}));
                    continue;
                }
                if req.value["op"]=="monitor.present" {
                    let response=match system_shell::present_monitor(&mut data.state,req.peer_pid) {Ok(())=>serde_json::json!({"ok":true,"result":{}}),Err(error)=>serde_json::json!({"ok":false,"error":error})};
                    let _=req.reply.try_send(response);continue;
                }
                if req.value["op"]=="terminal.present" {
                    let response=match system_shell::present_terminal(&mut data.state,req.peer_pid,req.value["app_id"].as_str().unwrap_or("")) {Ok(())=>serde_json::json!({"ok":true,"result":{}}),Err(error)=>serde_json::json!({"ok":false,"error":error})};
                    let _=req.reply.try_send(response);continue;
                }
                if matches!(req.value["op"].as_str(), Some("keyboard.stroke" | "keyboard.restore_focus" | "display.zoom")) {
                    let response = shell_keyboard::handle(&mut data.state, req.peer_pid, &req.value);
                    let _ = req.reply.try_send(response);
                    continue;
                }
                if req.value["op"].as_str()==Some("screen_reader.register") {
                    let result=data.state.accessibility.as_mut().ok_or("Screen reader is disabled").and_then(|service|service.register(req.peer_pid,req.value["pid"].as_u64(),req.value["start"].as_str()));
                    let response=match result {Ok(())=>serde_json::json!({"ok":true,"result":{}}),Err(error)=>serde_json::json!({"ok":false,"error":error})};
                    let _=req.reply.try_send(response);continue;
                }
                if req.value["op"].as_str()==Some("workspace.restore_outputs") {
                    if let Err(error)=system_shell::trusted_renderer(&data.state,req.peer_pid) {
                        let _=req.reply.try_send(serde_json::json!({"ok":false,"error":error}));
                        continue;
                    }
                }
                if req.value["op"]
                    .as_str()
                    .map(|op| op.starts_with("workspace."))
                    .unwrap_or(false)
                {
                    if let Some(bridge) = &data.state.bridge {
                        if let Err(error) = bridge.commands.try_send(req) {
                            let req = match error {
                                std::sync::mpsc::TrySendError::Full(req)
                                | std::sync::mpsc::TrySendError::Disconnected(req) => req,
                            };
                            let _ = req.reply.try_send(
                                serde_json::json!({"ok":false,"error":"Workspace worker busy"}),
                            );
                        }
                        continue;
                    }
                }
                let response = control::handle(&mut data.state, &req.value);
                let _ = req.reply.try_send(response);
            }
            if let Some(child) = &mut *child.lock().unwrap() {
                if let Some(status) = child.try_wait().ok().flatten() {
                    eprintln!("Owned renderer exited: {status}");
                    data.state.loop_signal.stop();
                }
            }
            // Protocol responses (seat focus, text input, configure and control)
            // must leave the server even when no frame can be presented.
            let _ = data.display_handle.flush_clients();
        },
    )?;

    Ok(())
}
