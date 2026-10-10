//! Adapted from Smithay smallvil v0.6.0 (MIT); see LICENSE-SMITHAY.
#![allow(irrefutable_let_patterns)]

mod bridge;
mod control;
mod handlers;
mod policy;
mod pressure;
mod process;
mod shortcuts;

mod grabs;
mod input;
mod pointer_geometry;
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

    crate::winit::init_winit(&mut event_loop, &mut data)?;

    let control = control::Control::start()?;
    std::env::set_var("AGENT_OS_COMPOSITOR_SOCKET", &control.path);
    println!(
        "{}",
        serde_json::json!({"wayland_display":data.state.socket_name.to_string_lossy(),"control_socket":control.path})
    );
    let child = std::sync::Arc::new(std::sync::Mutex::new(None::<std::process::Child>));
    let _owned = process::OwnedChild(child.clone());
    let mut args = std::env::args().skip(1);
    if matches!(args.next().as_deref(), Some("-c" | "--command")) {
        if let Some(command) = args.next() {
            use std::os::unix::process::CommandExt;
            *child.lock().unwrap() = Some(
                std::process::Command::new(command)
                    .args(args)
                    .process_group(0)
                    .spawn()?,
            );
        }
    }
    event_loop.run(
        Some(std::time::Duration::from_millis(16)),
        &mut data,
        move |data| {
            if TERMINATE.load(std::sync::atomic::Ordering::Relaxed) {
                data.state.loop_signal.stop();
            }
            for req in control.requests.try_iter().take(8) {
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
                if child.try_wait().ok().flatten().is_some() {
                    data.state.loop_signal.stop();
                }
            }
        },
    )?;

    Ok(())
}
