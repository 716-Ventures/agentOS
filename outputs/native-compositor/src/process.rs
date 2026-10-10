//! Renderer ownership survives compositor errors and unwinding.
use std::{
    process::Child,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};
pub struct OwnedChild(pub Arc<Mutex<Option<Child>>>);
impl Drop for OwnedChild {
    fn drop(&mut self) {
        if let Some(mut child) = self.0.lock().unwrap_or_else(|p| p.into_inner()).take() {
            let pid = child.id() as i32;
            unsafe {
                libc::kill(-pid, libc::SIGTERM);
            }
            let deadline = Instant::now() + Duration::from_secs(3);
            while matches!(child.try_wait(), Ok(None)) {
                if Instant::now() >= deadline {
                    unsafe {
                        libc::kill(-pid, libc::SIGKILL);
                    }
                    break;
                }
                std::thread::sleep(Duration::from_millis(20));
            }
            let _ = child.wait();
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::process::CommandExt;
    #[test]
    fn unwinding_reaps_the_owned_renderer() {
        let child = std::process::Command::new("/bin/sh")
            .args(["-c", "exec sleep 30"])
            .process_group(0)
            .spawn()
            .unwrap();
        let pid = child.id();
        let cell = Arc::new(Mutex::new(Some(child)));
        let result = std::panic::catch_unwind(|| {
            let _owned = OwnedChild(cell.clone());
            panic!("Simulated display failure");
        });
        assert!(result.is_err());
        assert!(cell.lock().unwrap().is_none());
        assert_eq!(unsafe { libc::kill(pid as i32, 0) }, -1);
    }
}
