//! Explicit image storage reclamation, with core-enforced reference and ownership checks.
use super::*;
pub struct ImageControls {
    pub widget: gtk::Expander,
    chooser: gtk::DropDown,
    model: gtk::StringList,
    entries: Rc<RefCell<(Option<String>, Vec<String>)>>,
    remove: gtk::Button,
    notice: gtk::Label,
}
impl ImageControls {
    pub fn new(commands: Sender<Command>) -> Self {
        let content = ui::column(8);
        let notice=ui::text("Close image views before removing unused stored bytes. Removing bytes also prevents reopening that image through layout undo.",false);
        content.append(&notice);
        let model = gtk::StringList::new(&[]);
        let chooser = gtk::DropDown::new(Some(model.clone()), gtk::Expression::NONE);
        chooser.update_property(&[gtk::accessible::Property::Label("Stored image")]);
        content.append(&chooser);
        let remove = ui::button("Remove unused stored image", ButtonVariant::Outline, false);
        content.append(&remove);
        let entries = Rc::new(RefCell::new((None::<String>, Vec::<String>::new())));
        let current = entries.clone();
        let selected = chooser.clone();
        remove.connect_clicked(move |_| {
            let current = current.borrow();
            if let (Some(activity), Some(reference)) =
                (&current.0, current.1.get(selected.selected() as usize))
            {
                let _ = commands.send(Command::ReleaseImage {
                    activity: activity.clone(),
                    reference: reference.clone(),
                });
            }
        });
        let widget = gtk::Expander::builder()
            .label("Stored images")
            .child(&content)
            .build();
        Self {
            widget,
            chooser,
            model,
            entries,
            remove,
            notice,
        }
    }
    pub fn update(&self, frame: &Frame) {
        let values = frame.stored_images["resources"]
            .as_array()
            .cloned()
            .unwrap_or_default();
        let ids = values
            .iter()
            .filter_map(|r| r["reference"].as_str().map(String::from))
            .collect::<Vec<_>>();
        let current = self.entries.borrow();
        let selected = current.1.get(self.chooser.selected() as usize).cloned();
        let changed = current.0 != frame.activity || current.1 != ids;
        drop(current);
        if changed {
            let labels = values
                .iter()
                .map(|r| {
                    format!(
                        "{} · {} × {}",
                        r["label"].as_str().unwrap_or("Image"),
                        r["width"],
                        r["height"]
                    )
                })
                .collect::<Vec<_>>();
            self.model.splice(
                0,
                self.model.n_items(),
                &labels.iter().map(String::as_str).collect::<Vec<_>>(),
            );
            self.chooser.set_selected(
                selected
                    .and_then(|id| ids.iter().position(|r| r == &id))
                    .unwrap_or(0) as u32,
            );
        }
        self.remove
            .set_sensitive(frame.connected && !ids.is_empty());
        self.notice.set_text(frame.stored_images["unavailable"].as_str().unwrap_or("Close image views before removing unused stored bytes. Removing bytes also prevents reopening that image through layout undo."));
        *self.entries.borrow_mut() = (frame.activity.clone(), ids);
    }
}

pub fn verify() {
    let (commands, receiver) = std::sync::mpsc::channel();
    let control = ImageControls::new(commands);
    let mut frame = Frame {
        connected: true,
        activity: Some("1".into()),
        stored_images: json!({"resources":[{"reference":"resource-fixture","label":"Blue pixel","width":1,"height":1}]}),
        ..Frame::default()
    };
    control.update(&frame);
    assert!(control.remove.is_sensitive());
    assert!(receiver.try_recv().is_err());
    control.remove.emit_clicked();
    assert!(
        matches!(receiver.try_recv().unwrap(),Command::ReleaseImage{activity,reference} if activity=="1" && reference=="resource-fixture")
    );
    frame.connected = false;
    control.update(&frame);
    assert!(!control.remove.is_sensitive());
}
