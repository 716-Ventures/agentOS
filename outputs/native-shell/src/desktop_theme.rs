//! Offline desktop materials, scoped independently from document components.
use super::*;
thread_local! { static PROVIDER: RefCell<Option<gtk::CssProvider>> = const { RefCell::new(None) }; }
pub fn install(display: &gtk::gdk::Display, light: bool, scale: f64) {
    let font_size = 15.0 * scale.clamp(1.0, 3.0);
    let (bg, fg, muted, line, selected, panel) = if light {
        (
            "#f8fafc", "#172334", "#4c5c70", "#cbd5e1", "#e1eef9", "#eef3f8",
        )
    } else {
        (
            "rgba(20,29,35,0.97)",
            "#eff2f4",
            "#b8c3cd",
            "#36424b",
            "#263b4e",
            "#1e2a33",
        )
    };
    let css = format!(
        r#"
    window.seven-ui {{ background: {bg}; color: {fg}; font-family: Commissioner, Inter, sans-serif; font-size: {font_size}px; border-radius: 12px; }}
    window.seven-ui decoration {{ border-radius: 12px; border: none; box-shadow: 0 12px 30px rgba(0,0,0,0.28); }}
    window.seven-ui:backdrop decoration {{ box-shadow: 0 6px 16px rgba(0,0,0,0.16); }}
    window.seven-ui headerbar {{ background: {bg}; background-image: none; color: {fg}; min-height: 38px; padding: 0 12px; border: none; border-bottom: 1px solid {line}; box-shadow: none; border-radius: 12px 12px 0 0; }}
    window.seven-ui headerbar .title {{ font-size: 13px; font-weight: 600; }}
    window.seven-ui headerbar button.desktop-window-control {{ min-width: 12px; min-height: 12px; padding: 0; margin: 0; border: none; border-radius: 100%; box-shadow: none; background-image: none; }}
    window.seven-ui headerbar button.desktop-close {{ background: #ed6a5e; }}
    window.seven-ui headerbar button.desktop-maximize {{ background: #61c454; }}
    window.seven-ui headerbar button.desktop-window-control image {{ opacity: 0; -gtk-icon-size: 10px; }}
    window.seven-ui headerbar button.desktop-window-control:hover image, window.seven-ui headerbar button.desktop-window-control:focus-visible image {{ opacity: 1; }}
    window.seven-ui:backdrop headerbar button.desktop-window-control {{ background: {line}; }}
    window.seven-ui headerbar button.desktop-window-control:focus-visible {{ outline: 2px solid #527dab; outline-offset: 3px; }}
    window.agentos-monitor, window.agentos-launcher {{ background: {bg}; color: {fg}; font-family: Commissioner, Inter, sans-serif; font-size: {font_size}px; }}
    .agentos-monitor label {{ color: {fg}; }}
    .agentos-monitor headerbar {{ background: {bg}; color: {muted}; border-bottom: 1px solid {line}; box-shadow: none; }}
    .agentos-monitor .desktop-heading {{ font-size: 2.4em; font-weight: 500; letter-spacing: -0.5px; }}
    .agentos-monitor .desktop-subtitle, .agentos-monitor .desktop-muted {{ color: {muted}; }}
    .agentos-monitor .agent-table {{ background: transparent; border: none; padding: 0; }}
    .agentos-monitor .agent-table row {{ padding: 13px 12px; border-radius: 6px; border-bottom: 1px solid {line}; color: {fg}; }}
    .agentos-monitor .agent-table row:selected {{ background: {selected}; outline: 1px solid #527dab; outline-offset: -1px; }}
    .agentos-monitor .agent-table row:hover {{ background: {panel}; }}
    .agentos-monitor .agent-table row:selected:hover {{ background: {selected}; }}
    .agentos-monitor .agent-table-header {{ color: {muted}; padding: 0 16px; font-size: 0.85em; font-weight: 500; }}
    .agentos-monitor .agent-details {{ border-top: 1px solid {line}; padding-top: 23px; }}
    .agentos-monitor .agent-detail {{ background: transparent; padding: 0; }}
    .agentos-monitor button.desktop-primary {{ background: #27547d; color: #ffffff; }}
    .agentos-monitor button.desktop-primary label {{ color: #ffffff; }}
    .agentos-monitor .agent-name {{ font-weight: 600; }}
    .agentos-monitor .token-count {{ font-feature-settings: 'tnum'; }}
    .agentos-monitor expander > title {{ color: {muted}; padding: 8px 0; }}
    window.agentos-system-bar, .agentos-system-bar, window.agentos-wallpaper {{ background: transparent; background-image: none; box-shadow: none; border: none; }}
    .agentos-system-bar label, .agentos-system-bar button {{ color: #ffffff; font-family: Commissioner, Inter, sans-serif; font-weight: 500; text-shadow: 0 1px 1px rgba(0,0,0,0.55); }}
    .agentos-system-bar button {{ background: transparent; border: none; box-shadow: none; min-height: 0; padding: 4px 8px; }}
    .agentos-system-bar button:hover {{ text-decoration: underline; }}
    .agentos-system-bar button:focus-visible {{ outline: 2px solid #ffffff; outline-offset: 2px; }}
    .agentos-launcher .desktop-heading {{ font-size: 22px; font-weight: 600; }}
    .agentos-launcher entry {{ padding: 14px; min-height: 30px; }}
    "#
    );
    PROVIDER.with(|slot| {
        if let Some(old) = slot.borrow_mut().take() {
            gtk::style_context_remove_provider_for_display(display, &old);
        }
        let provider = gtk::CssProvider::new();
        provider.load_from_data(&css);
        gtk::style_context_add_provider_for_display(
            display,
            &provider,
            gtk::STYLE_PROVIDER_PRIORITY_APPLICATION + 1,
        );
        *slot.borrow_mut() = Some(provider);
    });
}
/// The licensed face is embedded so the approved desktop does not depend on a network.
pub fn register_font() {
    let directory = std::env::var_os("XDG_CACHE_HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            PathBuf::from(std::env::var_os("HOME").unwrap_or_default()).join(".cache")
        })
        .join("agentos/fonts");
    if std::fs::create_dir_all(&directory).is_err() {
        return;
    }
    let path = directory.join("Commissioner.ttf");
    if std::fs::read(&path).ok().as_deref()
        != Some(include_bytes!("../assets/Commissioner.ttf").as_slice())
        && std::fs::write(&path, include_bytes!("../assets/Commissioner.ttf")).is_err()
    {
        return;
    }
    unsafe {
        if let (Ok(library), Ok(path)) = (
            libloading::Library::new("libfontconfig.so.1"),
            std::ffi::CString::new(path.as_os_str().as_encoded_bytes()),
        ) {
            if let Ok(add) = library
                .get::<unsafe extern "C" fn(*mut libc::c_void, *const u8) -> i32>(
                    b"FcConfigAppFontAddFile\0",
                )
            {
                add(std::ptr::null_mut(), path.as_ptr().cast());
            }
        }
    }
}
pub fn signed_in_name() -> String {
    unsafe {
        let mut record: libc::passwd = std::mem::zeroed();
        let mut result = std::ptr::null_mut();
        let mut bytes = vec![0u8; 16384];
        if libc::getpwuid_r(
            libc::geteuid(),
            &mut record,
            bytes.as_mut_ptr().cast(),
            bytes.len(),
            &mut result,
        ) == 0
            && !result.is_null()
        {
            if !record.pw_gecos.is_null() {
                let name = std::ffi::CStr::from_ptr(record.pw_gecos)
                    .to_string_lossy()
                    .split(',')
                    .next()
                    .unwrap_or("")
                    .trim()
                    .to_owned();
                if !name.is_empty() {
                    return name;
                }
            }
        }
    }
    std::env::var("USER").unwrap_or_else(|_| "Local user".into())
}

/// Shared client-side chrome: native move, resize, maximize and close semantics.
pub fn titlebar(window: &gtk::ApplicationWindow) {
    let header=gtk::HeaderBar::new();
    header.set_show_title_buttons(false);
    let controls=gtk::Box::new(gtk::Orientation::Horizontal,8);
    controls.set_valign(gtk::Align::Center);
    for (class,icon,label) in [("desktop-close","window-close-symbolic","Close window"),("desktop-maximize","window-maximize-symbolic","Maximize window")] {
        let image=gtk::Image::from_icon_name(icon);image.set_pixel_size(10);
        let button=gtk::Button::builder().child(&image).tooltip_text(label).valign(gtk::Align::Center).build();
        button.add_css_class("desktop-window-control");button.add_css_class(class);
        button.update_property(&[gtk::accessible::Property::Label(label)]);
        let target=window.downgrade();
        button.connect_clicked(move |_| {if let Some(window)=target.upgrade() {if class=="desktop-close" {window.close();}else if window.is_maximized() {window.unmaximize();}else {window.maximize();}}});
        controls.append(&button);
    }
    header.pack_start(&controls);
    window.set_titlebar(Some(&header));
}
