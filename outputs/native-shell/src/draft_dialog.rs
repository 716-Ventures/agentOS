//! Deliberate conflict review preserves a human draft without silently adopting a newer revision.
use super::*;
pub fn review(
    parent: Option<&gtk::Window>,
    surface: String,
    element: String,
    commands: Sender<Command>,
) -> gtk::Window {
    let document_dialog::ReviewPanel {
        window,
        notice,
        previews,
        save,
        cancel,
    } = document_dialog::panel(
        parent,
        "Review latest version",
        ["Latest saved value", "Your retained draft"],
        "Save reviewed draft",
    );
    let reviewed = Rc::new(RefCell::new(None::<Value>));
    let (sender, current, weak) = (commands.clone(), reviewed.clone(), window.downgrade());
    let (id, key) = (surface.clone(), element.clone());
    save.connect_clicked(move |button| {
        if let Some(value) = current.borrow().as_ref() {
            button.set_sensitive(false);
            let _ = sender.send(Command::ResolveReviewedDraft {
                surface: id.clone(),
                element: key.clone(),
                revision: value["revision"].as_u64().unwrap_or(0),
                draft_revision: value["draft_revision"].as_u64().unwrap_or(0),
                text: value["after"].as_str().unwrap_or("").into(),
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
    let _ = commands.send(Command::ReviewDraft {
        surface,
        element,
        reply,
    });
    let weak = window.downgrade();
    glib::timeout_add_local(Duration::from_millis(100), move || {
        if weak.upgrade().is_none() {
            return glib::ControlFlow::Break;
        }
        match receiver.try_recv() {
            Ok(Ok(value)) => {
                notice.set_text(&format!("{} · current revision {}. Saving uses the exact versions shown here. Further changes preserve your draft and require another review.",value["title"].as_str().unwrap_or("Editor"),value["revision"]));
                previews[0]
                    .buffer()
                    .set_text(value["before"].as_str().unwrap_or(""));
                previews[1]
                    .buffer()
                    .set_text(value["after"].as_str().unwrap_or(""));
                *reviewed.borrow_mut() = Some(value);
                save.set_sensitive(true);
                glib::ControlFlow::Break
            }
            Ok(Err(error)) => {
                notice.set_text(&error);
                glib::ControlFlow::Break
            }
            Err(std::sync::mpsc::TryRecvError::Empty) => glib::ControlFlow::Continue,
            Err(_) => {
                notice.set_text("Draft review unavailable; the retained draft was not changed");
                glib::ControlFlow::Break
            }
        }
    });
    window.present();
    window
}

pub fn verify(parent: &gtk::Window) {
    let (sender, receiver) = std::sync::mpsc::channel();
    let window = review(
        Some(parent),
        "draft-fixture".into(),
        "editor".into(),
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
        Command::ReviewDraft {
            surface,
            element,
            reply,
        } => {
            assert_eq!(surface, "draft-fixture");
            assert_eq!(element, "editor");
            reply.send(Ok(json!({"title":"Changed document","before":"Current λ","after":"Retained 日本語","revision":9,"draft_revision":4}))).unwrap();
        }
        _ => panic!("Draft review must precede save"),
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
        matches!(receiver.try_recv().unwrap(),Command::ResolveReviewedDraft{surface,element,revision:9,draft_revision:4,text} if surface=="draft-fixture" && element=="editor" && text=="Retained 日本語")
    );
    assert!(!window.is_visible());
    window.destroy();
    println!("CHECK: latest value/draft comparison and deliberate save capture exact reviewed document and draft revisions");
}
