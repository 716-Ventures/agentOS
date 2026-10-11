//! Host-only system layer. The library is preloaded by the compositor so its
//! Wayland shim precedes GTK (upstream GTK4 Layer Shell linking requirement).
use super::*;
use gtk::glib::translate::ToGlibPtr;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};

pub fn configure(
    window: &gtk::ApplicationWindow,
    launcher: bool,
) -> Result<libloading::Library, String> {
    unsafe {
        let library =
            libloading::Library::new("libgtk4-layer-shell.so.0").map_err(|e| e.to_string())?;
        let supported = library
            .get::<unsafe extern "C" fn() -> i32>(b"gtk_layer_is_supported\0")
            .map_err(|e| e.to_string())?;
        if supported() == 0 {
            return Err("Private system-layer protocol unavailable".into());
        }
        let init = library
            .get::<unsafe extern "C" fn(*mut gtk::ffi::GtkWindow)>(b"gtk_layer_init_for_window\0")
            .map_err(|e| e.to_string())?;
        let namespace = library
            .get::<unsafe extern "C" fn(*mut gtk::ffi::GtkWindow, *const libc::c_char)>(
                b"gtk_layer_set_namespace\0",
            )
            .map_err(|e| e.to_string())?;
        let layer = library
            .get::<unsafe extern "C" fn(*mut gtk::ffi::GtkWindow, i32)>(b"gtk_layer_set_layer\0")
            .map_err(|e| e.to_string())?;
        let anchor = library
            .get::<unsafe extern "C" fn(*mut gtk::ffi::GtkWindow, i32, i32)>(
                b"gtk_layer_set_anchor\0",
            )
            .map_err(|e| e.to_string())?;
        let keyboard = library
            .get::<unsafe extern "C" fn(*mut gtk::ffi::GtkWindow, i32)>(
                b"gtk_layer_set_keyboard_mode\0",
            )
            .map_err(|e| e.to_string())?;
        let exclusive = library
            .get::<unsafe extern "C" fn(*mut gtk::ffi::GtkWindow)>(
                b"gtk_layer_auto_exclusive_zone_enable\0",
            )
            .map_err(|e| e.to_string())?;
        let pointer = window.upcast_ref::<gtk::Window>().to_glib_none().0;
        init(pointer);
        if launcher {
            namespace(pointer, c"agentos-launcher".as_ptr());
            layer(pointer, 3); // OVERLAY, centered without reserving work area
            keyboard(pointer, 1); // EXCLUSIVE only while deliberately invoked
        } else {
            namespace(pointer, c"agentos-system-bar".as_ptr());
            layer(pointer, 2); // TOP
            for edge in [0, 1, 2] {
                anchor(pointer, edge, 1);
            }
            keyboard(pointer, 2); // ON_DEMAND
            exclusive(pointer);
        }
        Ok(library)
    }
}

/// Pointer-operated keyboard: reserve the bottom work area without taking the
/// application's keyboard focus. It uses the same private layer capability.
pub fn configure_keyboard(window: &gtk::ApplicationWindow) -> Result<libloading::Library, String> {
    let library = configure(window, true)?;
    unsafe {
        let pointer = window.upcast_ref::<gtk::Window>().to_glib_none().0;
        library
            .get::<unsafe extern "C" fn(*mut gtk::ffi::GtkWindow, *const libc::c_char)>(
                b"gtk_layer_set_namespace\0",
            )
            .map_err(|e| e.to_string())?(pointer, c"agentos-keyboard".as_ptr());
        let anchor = library
            .get::<unsafe extern "C" fn(*mut gtk::ffi::GtkWindow, i32, i32)>(
                b"gtk_layer_set_anchor\0",
            )
            .map_err(|e| e.to_string())?;
        for edge in [0, 1, 3] {
            anchor(pointer, edge, 1);
        }
        library
            .get::<unsafe extern "C" fn(*mut gtk::ffi::GtkWindow, i32)>(
                b"gtk_layer_set_keyboard_mode\0",
            )
            .map_err(|e| e.to_string())?(pointer, 0);
        library
            .get::<unsafe extern "C" fn(*mut gtk::ffi::GtkWindow)>(
                b"gtk_layer_auto_exclusive_zone_enable\0",
            )
            .map_err(|e| e.to_string())?(pointer);
    }
    Ok(library)
}

/// Independent of core connectivity: direct controls remain reachable offline.
/// A fresh renderer establishes a baseline instead of replaying old invocations.
pub struct LauncherEvents {
    pub sequence: Arc<AtomicU64>,
    pub keyboard_sequence: Arc<AtomicU64>,
    zoom: Arc<AtomicU64>,
    stop: Arc<AtomicBool>,
    worker: Option<std::thread::JoinHandle<()>>,
}
impl LauncherEvents {
    pub fn start() -> Self {
        let sequence = Arc::new(AtomicU64::new(0));
        let keyboard_sequence = Arc::new(AtomicU64::new(0));
        let keyboard_events = keyboard_sequence.clone();
        let zoom=Arc::new(AtomicU64::new(1.0f64.to_bits()));
        let zoom_events=zoom.clone();
        let stop = Arc::new(AtomicBool::new(false));
        let (events, stopping) = (sequence.clone(), stop.clone());
        let path = std::env::var_os("AGENT_OS_COMPOSITOR_SOCKET").map(PathBuf::from);
        let worker = path.map(|path| {
            std::thread::spawn(move || {
                let mut prior = None;
                let mut prior_keyboard = None;
                while !stopping.load(Ordering::Relaxed) {
                    if let Ok(value) = transport::request_timeout(
                        &path,
                        &json!({"op":"launcher.state"}),
                        Duration::from_millis(300),
                    ) {
                        if let Some(factor)=value["display_zoom"].as_f64().filter(|factor| factor.is_finite() && (1.0..=2.0).contains(factor)) {zoom_events.store(factor.to_bits(),Ordering::Relaxed);}
                        if let Some(current) = value["keyboard_sequence"].as_u64() {
                            if prior_keyboard.is_some_and(|old| current > old) {
                                keyboard_events.fetch_add(1, Ordering::Relaxed);
                            }
                            prior_keyboard = Some(current);
                        }
                        if let Some(current) = value["sequence"].as_u64() {
                            if prior.is_some_and(|old| current > old) {
                                events.fetch_add(1, Ordering::Relaxed);
                            }
                            prior = Some(current);
                        }
                    }
                    std::thread::sleep(Duration::from_millis(50));
                }
            })
        });
        Self {
            sequence,
            keyboard_sequence,
            zoom,
            stop,
            worker,
        }
    }
    pub fn zoom(&self) -> f64 {f64::from_bits(self.zoom.load(Ordering::Relaxed))}
    pub fn current(&self) -> u64 {
        self.sequence.load(Ordering::Relaxed)
    }
}
impl Drop for LauncherEvents {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }
}

pub fn capture(window: &gtk::ApplicationWindow, path: &str) -> bool {
    if window.width() <= 0 || window.height() <= 0 {
        return false;
    }
    let paintable = gtk::WidgetPaintable::new(Some(window));
    let snapshot = gtk::Snapshot::new();
    paintable.snapshot(&snapshot, window.width() as f64, window.height() as f64);
    if let (Some(node), Some(renderer)) = (snapshot.to_node(), window.renderer()) {
        return renderer
            .render_texture(&node, None)
            .save_to_png(path)
            .is_ok();
    }
    false
}
