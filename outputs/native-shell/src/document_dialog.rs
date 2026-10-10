//! Local human file selection. Only a deliberate response dispatches filesystem work.
use super::*;
pub fn choose(
    parent: Option<&gtk::Window>,
    exporting: Option<(String, u64)>,
    activity: Option<String>,
    commands: Sender<Command>,
) {
    let save = exporting.is_some();
    let dialog = gtk::FileChooserNative::builder()
        .title(if save {
            "Export saved document to a new file"
        } else {
            "Import UTF-8 document"
        })
        .action(if save {
            gtk::FileChooserAction::Save
        } else {
            gtk::FileChooserAction::Open
        })
        .accept_label(if save { "Export" } else { "Import" })
        .cancel_label("Cancel")
        .modal(true)
        .build();
    dialog.set_transient_for(parent);
    if save {
        dialog.set_current_name("document.txt");
    }
    dialog.connect_response(move |dialog, response| {
        if response == gtk::ResponseType::Accept {
            if let Some(path) = dialog.file().and_then(|file| file.path()) {
                let command = if let Some((surface, revision)) = &exporting {
                    Some(Command::ExportDocument {
                        surface: surface.clone(),
                        revision: *revision,
                        path,
                    })
                } else {
                    activity.as_ref().map(|id| Command::ImportDocument {
                        activity: id.clone(),
                        path,
                    })
                };
                if let Some(command) = command {
                    let _ = commands.send(command);
                }
            }
        }
        dialog.destroy();
    });
    dialog.show();
}

pub fn choose_replacement(
    parent: Option<&gtk::Window>,
    surface: String,
    revision: u64,
    commands: Sender<Command>,
) {
    let dialog = gtk::FileChooserNative::builder()
        .title("Choose existing text file to review")
        .action(gtk::FileChooserAction::Open)
        .accept_label("Review replacement")
        .cancel_label("Cancel")
        .modal(true)
        .build();
    dialog.set_transient_for(parent);
    let weak = parent.map(|p| p.downgrade());
    dialog.connect_response(move |dialog, response| {
        if response == gtk::ResponseType::Accept {
            if let Some(path) = dialog.file().and_then(|file| file.path()) {
                let parent = weak.as_ref().and_then(|p| p.upgrade());
                review_replacement(
                    parent.as_ref(),
                    surface.clone(),
                    revision,
                    path,
                    commands.clone(),
                );
            }
        }
        dialog.destroy();
    });
    dialog.show();
}
fn review_replacement(
    parent: Option<&gtk::Window>,
    surface: String,
    revision: u64,
    path: PathBuf,
    commands: Sender<Command>,
) -> gtk::Window {
    let window = gtk::Window::builder()
        .title("Review file replacement")
        .default_width(900)
        .default_height(600)
        .modal(true)
        .build();
    window.set_transient_for(parent);
    window.set_application(parent.and_then(|p| p.application()).as_ref());
    let content = ui::column(12);
    content.set_margin_top(20);
    content.set_margin_bottom(20);
    content.set_margin_start(20);
    content.set_margin_end(20);
    let notice = ui::text("Loading saved document and current file…", false);
    content.append(&notice);
    let panes = ui::row(12);
    panes.set_vexpand(true);
    let mut previews = Vec::new();
    for label in ["Current file", "Saved document replacement"] {
        let column = ui::column(8);
        column.set_hexpand(true);
        column.append(&ui::text(label, true));
        let text = gtk::TextView::builder()
            .editable(false)
            .monospace(true)
            .wrap_mode(gtk::WrapMode::WordChar)
            .build();
        text.update_property(&[gtk::accessible::Property::Label(label)]);
        let scroll = gtk::ScrolledWindow::builder()
            .min_content_height(240)
            .child(&text)
            .vexpand(true)
            .hexpand(true)
            .build();
        column.append(&scroll);
        panes.append(&column);
        previews.push(text);
    }
    content.append(&panes);
    let save = ui::button(
        "Replace file and retain original",
        ButtonVariant::Primary,
        false,
    );
    save.set_sensitive(false);
    let cancel = ui::button("Cancel", ButtonVariant::Outline, false);
    let row = ui::row(8);
    row.append(&save);
    row.append(&cancel);
    content.append(&row);
    window.set_child(Some(&content));
    let fingerprint = Rc::new(RefCell::new(None::<String>));
    let (sender, digest, weak) = (commands.clone(), fingerprint.clone(), window.downgrade());
    let selected = path.clone();
    let id = surface.clone();
    save.connect_clicked(move |button| {
        if let Some(expected_sha256) = digest.borrow().as_ref() {
            button.set_sensitive(false);
            let _ = sender.send(Command::ReplaceDocumentFile {
                surface: id.clone(),
                revision,
                path: selected.clone(),
                expected_sha256: expected_sha256.clone(),
            });
            if let Some(window) = weak.upgrade() {
                window.close();
            }
        }
    });
    let weak = window.downgrade();
    cancel.connect_clicked(move |_| {
        if let Some(window) = weak.upgrade() {
            window.close();
        }
    });
    let (reply, receiver) = std::sync::mpsc::channel();
    let _ = commands.send(Command::ReviewDocumentFile {
        surface,
        revision,
        path,
        reply,
    });
    let weak = window.downgrade();
    glib::timeout_add_local(Duration::from_millis(100), move || {
        if weak.upgrade().is_none() {
            return glib::ControlFlow::Break;
        }
        match receiver.try_recv() {
            Ok(Ok(value)) => {
                notice.set_text(&format!("{}\nSaved revision {}. The original is retained in private recovery storage. Changes to the file or document require a new review.",value["path"].as_str().unwrap_or("Selected file"),revision));
                previews[0]
                    .buffer()
                    .set_text(value["before"].as_str().unwrap_or(""));
                previews[1]
                    .buffer()
                    .set_text(value["after"].as_str().unwrap_or(""));
                *fingerprint.borrow_mut() = value["expected_sha256"].as_str().map(String::from);
                save.set_sensitive(fingerprint.borrow().is_some());
                glib::ControlFlow::Break
            }
            Ok(Err(error)) => {
                notice.set_text(&error);
                glib::ControlFlow::Break
            }
            Err(std::sync::mpsc::TryRecvError::Empty) => glib::ControlFlow::Continue,
            Err(_) => {
                notice.set_text("File review unavailable");
                glib::ControlFlow::Break
            }
        }
    });
    window.present();
    window
}

pub fn verify_review(parent: &gtk::Window) {
    let (sender, receiver) = std::sync::mpsc::channel();
    let window = review_replacement(
        Some(parent),
        "review-fixture".into(),
        7,
        PathBuf::from("/tmp/agentos-review-fixture"),
        sender,
    );
    let content = window.child().unwrap().downcast::<gtk::Box>().unwrap();
    let row = content
        .last_child()
        .unwrap()
        .downcast::<gtk::Box>()
        .unwrap();
    let save = row
        .first_child()
        .unwrap()
        .downcast::<gtk::Button>()
        .unwrap();
    assert!(!save.is_sensitive());
    match receiver.try_recv().unwrap() {
        Command::ReviewDocumentFile {
            surface,
            revision,
            path,
            reply,
        } => {
            assert_eq!(surface, "review-fixture");
            assert_eq!(revision, 7);
            assert_eq!(path, PathBuf::from("/tmp/agentos-review-fixture"));
            reply.send(Ok(json!({"before":"Original λ","after":"Reviewed 日本語","expected_sha256":"a".repeat(64),"path":"/tmp/agentos-review-fixture"}))).unwrap();
        }
        _ => panic!("File review must precede replacement"),
    }
    let deadline = std::time::Instant::now() + Duration::from_secs(2);
    while !save.is_sensitive() {
        assert!(std::time::Instant::now() < deadline);
        while glib::MainContext::default().pending() {
            glib::MainContext::default().iteration(false);
        }
        std::thread::sleep(Duration::from_millis(5));
    }
    assert!(receiver.try_recv().is_err());
    save.emit_clicked();
    assert!(
        matches!(receiver.try_recv().unwrap(),Command::ReplaceDocumentFile{surface,revision:7,expected_sha256,..} if surface=="review-fixture" && expected_sha256=="a".repeat(64))
    );
    assert!(!window.is_visible());
    window.destroy();
    println!("CHECK: file replacement requires completed review and deliberate human action with exact revision/hash");
}
