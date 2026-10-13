//! One inert background per live output; never reserves work area or takes focus.
use super::*;
use gtk::glib::translate::ToGlibPtr;
thread_local! {static TEXTURE:RefCell<Option<gtk::gdk::Texture>>=const {RefCell::new(None)};}
/// Reuse the approved image across output backgrounds and bar legibility.
pub fn texture() -> Result<gtk::gdk::Texture,glib::Error> {
    TEXTURE.with(|cached| {
        if let Some(texture)=cached.borrow().as_ref(){return Ok(texture.clone());}
        let texture=gtk::gdk::Texture::from_bytes(&glib::Bytes::from_static(include_bytes!("../assets/alpine-wallpaper.png")))?;
        *cached.borrow_mut()=Some(texture.clone());Ok(texture)
    })
}
type Background = (
    gtk::gdk::Monitor,
    gtk::ApplicationWindow,
    libloading::Library,
);
pub struct Backgrounds {
    display: gtk::gio::ListModel,
    handler: Option<glib::SignalHandlerId>,
    windows: Rc<RefCell<Vec<Background>>>,
}
impl Backgrounds {
    pub fn new(app: &gtk::Application, display: &gtk::gdk::Display) -> Self {
        let monitors = display.monitors();
        let windows = Rc::new(RefCell::new(Vec::<Background>::new()));
        let application = app.clone();
        let retained = windows.clone();
        let reconcile = Rc::new(move |monitors: &gtk::gio::ListModel| {
            let live = (0..monitors.n_items())
                .filter_map(|i| monitors.item(i)?.downcast::<gtk::gdk::Monitor>().ok())
                .collect::<Vec<_>>();
            let mut windows = retained.borrow_mut();
            windows.retain(|(monitor, window, _)| {
                if live.contains(monitor) {
                    true
                } else {
                    window.destroy();
                    false
                }
            });
            for monitor in live {
                if windows.iter().any(|(known, _, _)| known == &monitor) {
                    continue;
                }
                let texture = match texture() {
                    Ok(texture) => texture,
                    Err(error) => {
                        eprintln!("Wallpaper unavailable: {error}");
                        continue;
                    }
                };
                let picture = gtk::Picture::for_paintable(&texture);
                picture.set_can_shrink(true);
                picture.set_content_fit(gtk::ContentFit::Cover);
                picture.set_focusable(false);
                picture.set_can_target(false);
                let window = gtk::ApplicationWindow::builder()
                    .application(&application)
                    .title("agentOS wallpaper")
                    .decorated(false)
                    .child(&picture)
                    .build();
                window.add_css_class("agentos-wallpaper");
                match configure(&window, &monitor) {
                    Ok(library) => {
                        window.present();
                        windows.push((monitor, window, library));
                    }
                    Err(error) => {
                        eprintln!("Wallpaper unavailable: {error}");
                        window.destroy();
                    }
                }
            }
        });
        reconcile(&monitors);
        let handler = monitors.connect_items_changed(move |monitors, _, _, _| reconcile(monitors));
        Self {
            display: monitors,
            handler: Some(handler),
            windows,
        }
    }
}
impl Drop for Backgrounds {
    fn drop(&mut self) {
        if let Some(handler) = self.handler.take() {
            self.display.disconnect(handler);
        }
        for (_, window, _) in self.windows.borrow_mut().drain(..) {
            window.destroy();
        }
    }
}
fn configure(
    window: &gtk::ApplicationWindow,
    monitor: &gtk::gdk::Monitor,
) -> Result<libloading::Library, String> {
    let library = system_bar::configure(window, true)?;
    unsafe {
        let pointer = window.upcast_ref::<gtk::Window>().to_glib_none().0;
        library
            .get::<unsafe extern "C" fn(*mut gtk::ffi::GtkWindow, *const libc::c_char)>(
                b"gtk_layer_set_namespace\0",
            )
            .map_err(|e| e.to_string())?(pointer, c"agentos-wallpaper".as_ptr());
        library
            .get::<unsafe extern "C" fn(*mut gtk::ffi::GtkWindow, i32)>(b"gtk_layer_set_layer\0")
            .map_err(|e| e.to_string())?(pointer, 0);
        library
            .get::<unsafe extern "C" fn(*mut gtk::ffi::GtkWindow, i32)>(
                b"gtk_layer_set_keyboard_mode\0",
            )
            .map_err(|e| e.to_string())?(pointer, 0);
        library
            .get::<unsafe extern "C" fn(*mut gtk::ffi::GtkWindow, *mut gtk::gdk::ffi::GdkMonitor)>(
                b"gtk_layer_set_monitor\0",
            )
            .map_err(|e| e.to_string())?(pointer, monitor.to_glib_none().0);
        let anchor = library
            .get::<unsafe extern "C" fn(*mut gtk::ffi::GtkWindow, i32, i32)>(
                b"gtk_layer_set_anchor\0",
            )
            .map_err(|e| e.to_string())?;
        for edge in 0..4 {
            anchor(pointer, edge, 1);
        }
        // -1 makes the background cover the entire output, including the bar.
        library
            .get::<unsafe extern "C" fn(*mut gtk::ffi::GtkWindow, i32)>(
                b"gtk_layer_set_exclusive_zone\0",
            )
            .map_err(|e| e.to_string())?(pointer, -1);
    }
    Ok(library)
}
