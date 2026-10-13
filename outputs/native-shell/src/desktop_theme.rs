//! Offline desktop materials, scoped independently from document components.
use super::*;
thread_local! { static PROVIDER: RefCell<Option<gtk::CssProvider>> = const { RefCell::new(None) }; }
pub fn install(display: &gtk::gdk::Display, light: bool, scale: f64) {
    let font_size = 14.0 * scale.clamp(1.0, 3.0);
    let (bg, fg, muted, line, selected, panel) = if light {
        (
            "#f7f8fa", "#202630", "#536171", "#d7dce2", "#e1eef9", "#edf0f4",
        )
    } else {
        (
            "#192229",
            "#eff2f4",
            "#b8c3cd",
            "#35414a",
            "#263b4e",
            "#1e2a33",
        )
    };
    let heading_size = (36.0 * scale.clamp(1.0, 3.0)).min(48.0);
    let terminal_bg=if light {"#ffffff"}else{"#11171d"};
    let css = format!(
        r#"
    window.seven-ui {{ background: {bg}; color: {fg}; font-family: Commissioner, Inter, sans-serif; font-size: {font_size}px; border-radius: 12px; }}
    window.seven-ui .local-terminal-console {{ background: {terminal_bg}; }}
    window.seven-ui .terminal-close-panel {{ background: {bg}; border: 1px solid {line}; border-radius: 12px; box-shadow: 0 8px 24px rgba(0,0,0,0.25); }}
    window.seven-ui .terminal-close-panel button.destructive {{ background: #b43132; color: #ffffff; }}
    window.seven-ui .terminal-close-panel button.destructive:hover {{ background: #c13d3e; }}
    window.seven-ui .terminal-close-panel button.destructive:active {{ background: #962729; }}
    window.seven-ui .terminal-close-panel button.destructive label {{ color: #ffffff; }}
    window.seven-ui decoration {{ border-radius: 12px; border: none; box-shadow: 0 12px 30px rgba(0,0,0,0.28); }}
    window.seven-ui.desktop-inactive decoration {{ box-shadow: 0 6px 16px rgba(0,0,0,0.16); }}
    window.seven-ui headerbar {{ background: {bg}; background-image: none; color: {fg}; min-height: 38px; padding: 0; border: none; border-bottom: 1px solid {line}; box-shadow: none; border-radius: 12px 12px 0 0; }}
    window.seven-ui label {{ color: {fg}; }}
    window.seven-ui label.muted, window.seven-ui .desktop-muted {{ color: {muted}; }}
    window.seven-ui button {{ min-height: 1.4em; padding: 0.32em 0.85em; border-radius: 6px; font-weight: 500; }}
    window.seven-ui button.primary, window.seven-ui button.desktop-primary {{ background: #2b6397; color: white; }}
    window.seven-ui button.primary:hover, window.seven-ui button.desktop-primary:hover {{ background: #3475ad; }}
    window.seven-ui button.primary:active, window.seven-ui button.desktop-primary:active {{ background: #24547f; }}
    window.seven-ui button.primary label, window.seven-ui button.desktop-primary label {{ color: white; }}
    window.seven-ui button.outline {{ background: {panel}; color: {fg}; border: 1px solid {line}; min-height: 1.4em; }}
    window.seven-ui button.outline:hover, window.seven-ui button.ghost:hover {{ background: {selected}; }}
    window.seven-ui button.outline:active, window.seven-ui button.ghost:active {{ background: {line}; }}
    window.seven-ui button:disabled {{ opacity: 0.45; }}
    window.seven-ui entry {{ background: {panel}; color: {fg}; border: 1px solid {line}; min-height: 1.5em; padding: 0.4em 0.65em; border-radius: 6px; }}
    window.seven-ui dropdown > button, window.seven-ui spinbutton {{ background: {panel}; color: {fg}; border: 1px solid {line}; border-radius: 6px; background-image: none; }}
    window.seven-ui spinbutton entry {{ background: transparent; border: none; }}
    window.seven-ui spinbutton button {{ background: transparent; border: none; padding: 4px 6px; }}
    window.seven-ui dropdown > button:hover, window.seven-ui spinbutton button:hover {{ background: {selected}; }}
    window.seven-ui entry text placeholder {{ color: {muted}; }}
    window.seven-ui entry:focus-within {{ border-color: #5286b9; outline: 2px solid alpha(#5286b9,0.65); outline-offset: 1px; }}
    window.seven-ui button:focus-visible, window.seven-ui textview:focus-visible {{ outline: 2px solid #5286b9; outline-offset: 2px; }}
    window.seven-ui selection {{ background: #275d8b; color: white; }}
    window.seven-ui separator {{ background: {line}; min-height: 1px; }}
    window.seven-ui.desktop-inactive headerbar .title {{ color: {muted}; }}
    window.seven-ui headerbar .title {{ font-size: 13px; font-weight: 600; }}
    window.seven-ui headerbar button.desktop-window-control {{ min-width: 12px; min-height: 12px; padding: 6px; margin: 0; background: transparent; border: none; border-radius: 100%; box-shadow: none; background-image: none; }}
    window.seven-ui headerbar button.desktop-close .desktop-control-disc {{ background: #ed6a5e; }}
    window.seven-ui headerbar button.desktop-maximize .desktop-control-disc {{ background: #61c454; }}
    .desktop-control-disc {{ min-width: 12px; min-height: 12px; border-radius: 100%; }}
    window.seven-ui headerbar button.desktop-window-control image {{ opacity: 0; -gtk-icon-size: 10px; }}
    window.seven-ui headerbar button.desktop-window-control:hover image, window.seven-ui headerbar button.desktop-window-control:focus-visible image {{ opacity: 1; }}
    window.seven-ui.desktop-inactive headerbar button.desktop-window-control .desktop-control-disc {{ background: {line}; }}
    window.seven-ui headerbar button.desktop-window-control:focus-visible {{ outline: 2px solid #527dab; outline-offset: 3px; }}
    window.agentos-monitor, window.agentos-launcher {{ background: {bg}; color: {fg}; font-family: Commissioner, Inter, sans-serif; font-size: {font_size}px; }}
    .agentos-monitor label {{ color: {fg}; }}
    .agentos-monitor headerbar {{ background: {bg}; color: {muted}; border-bottom: 1px solid {line}; box-shadow: none; }}
    .agentos-monitor .desktop-heading {{ font-size: {heading_size}px; font-weight: 500; letter-spacing: -0.5px; }}
    .agentos-monitor .desktop-subtitle, .agentos-monitor .desktop-muted {{ color: {muted}; }}
    .agentos-monitor .agent-table {{ background: transparent; border: none; padding: 0; }}
    .agentos-monitor .agent-table row {{ padding: 13px 12px; border-radius: 6px; border-bottom: 1px solid {line}; color: {fg}; }}
    .agentos-monitor .agent-table row:selected {{ background: {selected}; outline: 1px solid #527dab; outline-offset: -1px; }}
    .agentos-monitor .agent-table row:hover {{ background: {panel}; }}
    .agentos-monitor .agent-table row:selected:hover {{ background: {selected}; }}
    .agentos-monitor .agent-table-header {{ color: {muted}; padding: 0 16px; font-size: 0.85em; font-weight: 500; }}
    .agentos-monitor .agent-details {{ padding: 0; border: none; }}
    .agentos-monitor flowboxchild {{ padding: 0; }}
    .agentos-monitor .monitor-heading {{ font-size: 1.15em; font-weight: 600; }}
    .agentos-monitor .agent-detail {{ background: transparent; padding: 0; }}
    .agentos-monitor button.desktop-primary label {{ color: #ffffff; }}
    .agentos-monitor .agent-name {{ font-weight: 600; }}
    .agentos-monitor .token-count {{ font-feature-settings: 'tnum'; }}
    .agentos-monitor expander > title {{ color: {muted}; padding: 8px 0; }}
    window.agentos-system-bar, .agentos-system-bar, window.agentos-wallpaper {{ background: transparent; background-image: none; box-shadow: none; border: none; }}
    .agentos-system-bar label, .agentos-system-bar button {{ font-size: 15px; color: #ffffff; font-family: Commissioner, Inter, sans-serif; font-weight: 500; text-shadow: 0 1px 1px rgba(0,0,0,0.55); }}
    .agentos-system-bar button {{ background: transparent; border: none; box-shadow: none; min-height: 0; padding: 4px 8px; }}
    .agentos-system-bar button:hover {{ text-decoration: underline; }}
    .agentos-system-bar .desktop-user-menu > button {{ padding: 4px 0; }}
    .agentos-system-bar .desktop-menu contents {{ background: {bg}; border: 1px solid {line}; border-radius: 8px; padding: 6px; box-shadow: 0 8px 24px rgba(0,0,0,0.22); }}
    .agentos-system-bar .desktop-menu label, .agentos-system-bar .desktop-menu button {{ color: {fg}; font-size: {font_size}px; text-shadow: none; }}
    .agentos-system-bar .desktop-menu button {{ padding: 6px 12px; border-radius: 4px; }}
    .agentos-system-bar .desktop-menu button:hover {{ background: {selected}; text-decoration: none; }}
    .agentos-system-bar .desktop-menu button:focus-visible {{ outline: 2px solid #5286b9; outline-offset: -2px; }}
    .agentos-system-bar button:focus-visible {{ outline: 2px solid #ffffff; outline-offset: 2px; }}
    .agentos-launcher .desktop-heading {{ font-size: 22px; font-weight: 600; }}
    .agentos-launcher .launcher-request entry {{ font-size: 1.25em; padding: 0.6em 0.7em; min-height: 1.5em; }}
    .agentos-launcher .launcher-context, .agentos-launcher .launcher-voice-status {{ color: {muted}; font-size: 0.93em; }}
    .agentos-launcher .launcher-direct {{ margin-top: 12px; }}
    .agentos-launcher .launcher-direct flowboxchild {{ padding: 0; }}
    .agentos-launcher .launcher-request-actions {{ margin-top: 2px; }}
    window.agentos-settings .settings-navigation {{ background: {panel}; }}
    window.agentos-settings button.settings-category {{ background: transparent; border: none; color: {fg}; padding: 8px 12px; }}
    window.agentos-settings button.settings-category:checked {{ background: {selected}; }}
    window.agentos-settings button.settings-category:hover {{ background: {selected}; }}
    .agentos-monitor .monitor-empty {{ padding: 28px 12px 36px; }}
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
    local_terminal::apply_theme(light,scale);
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
pub fn titlebar(window: &impl IsA<gtk::Window>) {
    let window = window.upcast_ref::<gtk::Window>();
    let activation=|window: &gtk::Window| {
        if window.is_active() {window.remove_css_class("desktop-inactive");}
        else {window.add_css_class("desktop-inactive");}
    };
    activation(window);
    window.connect_is_active_notify(activation);
    let header=gtk::HeaderBar::new();
    header.set_show_title_buttons(false);
    let title=gtk::Label::new(None);title.add_css_class("title");
    title.set_ellipsize(gtk::pango::EllipsizeMode::End);title.set_single_line_mode(true);
    let update=|window: &gtk::Window, label: &gtk::Label| {
        let text=window.title().unwrap_or_default();
        label.set_text(text.strip_prefix("Agent view · ").unwrap_or(&text));
    };
    update(window,&title);
    let label=title.clone();window.connect_title_notify(move |window|update(window,&label));
    header.set_title_widget(Some(&title));
    let controls=gtk::Box::new(gtk::Orientation::Horizontal,0);
    controls.set_valign(gtk::Align::Center);
    controls.set_margin_start(12);controls.set_margin_end(12);
    for (class,icon,label) in [("desktop-close","window-close-symbolic","Close window"),("desktop-maximize","window-maximize-symbolic","Maximize window")] {
        let image=gtk::Image::from_icon_name(icon);image.set_pixel_size(10);
        let disc=gtk::Box::new(gtk::Orientation::Horizontal,0);
        disc.add_css_class("desktop-control-disc");
        let face=gtk::Overlay::new();face.set_child(Some(&disc));face.add_overlay(&image);
        image.set_halign(gtk::Align::Center);image.set_valign(gtk::Align::Center);
        let button=gtk::Button::builder().child(&face).tooltip_text(label).valign(gtk::Align::Center).build();
        button.add_css_class("desktop-window-control");button.add_css_class(class);
        button.update_property(&[gtk::accessible::Property::Label(label)]);
        let target=window.downgrade();
        button.connect_clicked(move |_| {if let Some(window)=target.upgrade() {if class=="desktop-close" {window.close();}else if window.is_maximized() {window.unmaximize();}else {window.maximize();}}});
        if class == "desktop-maximize" {
            let control=button.downgrade();let glyph=image.downgrade();
            window.connect_maximized_notify(move |window| {
                let label=if window.is_maximized(){"Restore window"}else{"Maximize window"};
                if let Some(button)=control.upgrade(){button.set_tooltip_text(Some(label));button.update_property(&[gtk::accessible::Property::Label(label)]);}
                if let Some(image)=glyph.upgrade(){image.set_icon_name(Some(if window.is_maximized(){"window-restore-symbolic"}else{"window-maximize-symbolic"}));}
            });
        }
        controls.append(&button);
    }
    header.pack_start(&controls);
    window.set_titlebar(Some(&header));
}

/// GTK's selected-item label otherwise takes precedence over a field's name.
/// Keep the authored identity while the trigger still exposes its current value.
pub fn name_dropdown(control: &gtk::DropDown, name: &str) {
    fn apply(control: &gtk::DropDown, name: &str) {
        control.reset_relation(gtk::AccessibleRelation::LabelledBy);
        control.update_property(&[gtk::accessible::Property::Label(name)]);
    }
    apply(control,name);
    let title=name.to_owned();control.connect_map(move |control|apply(control,&title));
    let title=name.to_owned();control.connect_selected_notify(move |control|apply(control,&title));
}
