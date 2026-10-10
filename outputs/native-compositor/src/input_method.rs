//! Optional human-configured input method, connected by a private inherited socket.
//! Never grant this global to ordinary clients based on their PID or app-id.
use crate::{process, state::ClientState, Smallvil};
use smithay::wayland::{input_method::InputMethodManagerState, text_input::TextInputManagerState};
use std::{
    os::{
        fd::AsRawFd,
        unix::{net::UnixStream, process::CommandExt},
    },
    path::Path,
    process::Command,
    sync::{Arc, Mutex},
};

pub struct Service {
    child: process::OwnedChild,
    _manager: InputMethodManagerState,
    _text: TextInputManagerState,
}
fn arguments(value: &str) -> Result<Vec<String>, String> {
    if value.len() > 16384 {
        return Err("Input method arguments exceed 16 KiB".into());
    }
    let argv: Vec<String> = serde_json::from_str(value)
        .map_err(|_| "Input method must be a JSON array of arguments")?;
    if argv.is_empty()
        || argv.len() > 16
        || !Path::new(&argv[0]).is_absolute()
        || argv
            .iter()
            .any(|arg| arg.len() > 4096 || arg.contains('\0'))
    {
        return Err(
            "Input method requires an absolute executable and at most 16 bounded arguments".into(),
        );
    }
    Ok(argv)
}
impl Service {
    pub fn start(state: &mut Smallvil) -> Result<Option<Self>, Box<dyn std::error::Error>> {
        let Some(value) = std::env::var_os("AGENT_OS_INPUT_METHOD_ARGV") else {
            return Ok(None);
        };
        let argv = arguments(
            value
                .to_str()
                .ok_or("Input method arguments must be UTF-8")?,
        )?;
        let (server, socket) = UnixStream::pair()?;
        state.display_handle.insert_client(
            server,
            Arc::new(ClientState {
                input_method: true,
                ..ClientState::default()
            }),
        )?;
        let manager =
            InputMethodManagerState::new::<Smallvil, _>(&state.display_handle, |client| {
                client
                    .get_data::<ClientState>()
                    .is_some_and(|data| data.input_method)
            });
        let text = TextInputManagerState::new::<Smallvil>(&state.display_handle);
        let fd = socket.as_raw_fd();
        let mut command = Command::new(&argv[0]);
        command
            .args(&argv[1..])
            .env("WAYLAND_SOCKET", fd.to_string());
        process::configure_child(&mut command);
        unsafe {
            command.pre_exec(move || {
                if libc::fcntl(fd, libc::F_SETFD, 0) == -1 {
                    return Err(std::io::Error::last_os_error());
                }
                Ok(())
            });
        }
        let child = command.spawn()?;
        // socket closes in the parent. No filesystem socket carries the capability.
        Ok(Some(Self {
            child: process::OwnedChild(Arc::new(Mutex::new(Some(child)))),
            _manager: manager,
            _text: text,
        }))
    }
    pub fn check(&self) -> Result<(), String> {
        if let Some(child) = self.child.0.lock().unwrap().as_mut() {
            if let Some(status) = child.try_wait().map_err(|e| e.to_string())? {
                return Err(format!(
                    "Configured helper exited ({status}); restart the session after inspecting it"
                ));
            }
        }
        Ok(())
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn human_input_method_configuration_is_literal_and_bounded() {
        assert_eq!(
            arguments(r#"["/usr/bin/fcitx5","--replace"]"#).unwrap(),
            vec!["/usr/bin/fcitx5", "--replace"]
        );
        for bad in [
            "[]",
            r#"["fcitx5"]"#,
            r#"["/bin/sh",null]"#,
            r#"["/usr/bin/fcitx5\u0000"]"#,
            "shell command",
        ] {
            assert!(arguments(bad).is_err());
        }
        assert!(arguments(&serde_json::to_string(&vec!["/bin/helper"; 17]).unwrap()).is_err());
        assert!(arguments(&" ".repeat(16385)).is_err());
    }
}
