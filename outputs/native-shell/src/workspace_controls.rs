//! Model-independent desktop controls over exact shared document revisions.
use super::*;
pub struct WorkspaceControls {
    pub widget: gtk::Expander,
    notice: gtk::Label,
    surfaces: gtk::DropDown,
    targets: gtk::DropDown,
    outputs: gtk::DropDown,
    surface_model: gtk::StringList,
    target_model: gtk::StringList,
    output_model: gtk::StringList,
    state: Rc<RefCell<(Vec<String>, Vec<String>, Option<Value>)>>,
    undo: gtk::Button,
    undo_cursor: Rc<Cell<Option<i64>>>,
    apply: gtk::Button,
}
fn dropdown(label: &str) -> (gtk::DropDown, gtk::StringList) {
    let model = gtk::StringList::new(&[]);
    let control = gtk::DropDown::new(Some(model.clone()), gtk::Expression::NONE);
    control.update_property(&[gtk::accessible::Property::Label(label)]);
    (control, model)
}
fn spin(label: &str, min: f64, max: f64, step: f64, value: f64) -> gtk::SpinButton {
    let s = gtk::SpinButton::with_range(min, max, step);
    s.set_value(value);
    s.update_property(&[gtk::accessible::Property::Label(label)]);
    s
}
impl WorkspaceControls {
    pub fn new(commands: Sender<Command>) -> Self {
        let content = ui::column(12);
        let widget = gtk::Expander::builder()
            .label("Arrange workspace")
            .child(&content)
            .build();
        let notice = ui::text("", true);
        content.append(&notice);
        let (surfaces, surface_model) = dropdown("Surface to arrange");
        let (targets, target_model) = dropdown("Second surface for split or swap");
        let (outputs, output_model) = dropdown("Destination output");
        let action = gtk::DropDown::from_strings(&[
            "Focus",
            "Tile beside target",
            "Stack above target",
            "Float / move / resize",
            "Maximize",
            "Restore arrangement",
            "Resize split",
            "Swap with target",
            "Pin placement",
            "Release pin",
        ]);
        action.update_property(&[gtk::accessible::Property::Label("Workspace action")]);
        for w in [&surfaces, &action, &targets, &outputs] {
            content.append(w);
        }
        let ratio = spin("Split share", 0.05, 0.95, 0.05, 0.5);
        let x = spin("Floating x", 0.0, 32768.0, 10.0, 80.0);
        let y = spin("Floating y", 0.0, 32768.0, 10.0, 80.0);
        let width = spin("Floating width", 80.0, 32768.0, 20.0, 640.0);
        let height = spin("Floating height", 32.0, 32768.0, 20.0, 480.0);
        let fields = gtk::FlowBox::new();
        fields.set_selection_mode(gtk::SelectionMode::None);
        fields.set_min_children_per_line(1);
        fields.set_max_children_per_line(3);
        fields.set_column_spacing(12);
        fields.set_row_spacing(12);
        for (label, s) in [
            ("Split share", &ratio),
            ("X", &x),
            ("Y", &y),
            ("Width", &width),
            ("Height", &height),
        ] {
            let row = ui::column(4);
            row.append(&ui::text(label, false));
            row.append(s);
            fields.insert(&row, -1);
        }
        content.append(&fields);
        let apply = ui::button("Apply arrangement", ButtonVariant::Outline, false);
        let undo = ui::button("Undo last arrangement", ButtonVariant::Outline, false);
        content.append(&apply);
        content.append(&undo);
        let state = Rc::new(RefCell::new((
            Vec::<String>::new(),
            Vec::<String>::new(),
            None::<Value>,
        )));
        let undo_cursor = Rc::new(Cell::new(None));
        let model = state.clone();
        let sender = commands.clone();
        let (s, t, o) = (surfaces.clone(), targets.clone(), outputs.clone());
        apply.connect_clicked(move |_|{
            let state=model.borrow();let Some(doc)=&state.2 else{return;};let Some(id)=state.0.get(s.selected() as usize) else{return;};let target=state.0.get(t.selected() as usize);let output=state.1.get(o.selected() as usize);
            let edit=match action.selected(){
                0=>json!({"kind":"focus","surface_id":id,"element_id":null}),
                n @ (1|2)=>{let Some(output)=output else{return;};json!({"kind":"tile","surface_id":id,"output_id":output,"target":target.filter(|other|*other!=id),"axis":if n==1{"horizontal"}else{"vertical"},"ratio":ratio.value()})},
                3=>{let Some(output)=output else{return;};json!({"kind":"float","surface_id":id,"output_id":output,"x":x.value(),"y":y.value(),"width":width.value(),"height":height.value()})},
                4=>json!({"kind":"maximize","surface_id":id}),5=>json!({"kind":"restore","surface_id":id}),6=>json!({"kind":"resize_split","surface_id":id,"ratio":ratio.value()}),
                7=>{let Some(other)=target else{return;};json!({"kind":"swap","surface_id":id,"other":other})},8=>json!({"kind":"pin","surface_id":id,"required":true}),9=>json!({"kind":"pin","surface_id":id,"required":false}),_=>return,
            };
            if let (Some(workspace),Some(revision))=(doc["workspace_id"].as_str(),doc["revision"].as_u64()){let _=sender.send(Command::WorkspaceEdit{workspace:workspace.into(),revision,edit});}
        });
        let cursor = undo_cursor.clone();
        undo.connect_clicked(move |_| {
            if let Some(cursor) = cursor.get() {
                let _ = commands.send(Command::WorkspaceUndo(cursor));
            }
        });
        Self {
            notice,
            widget,
            surfaces,
            targets,
            outputs,
            surface_model,
            target_model,
            output_model,
            state,
            undo,
            undo_cursor,
            apply,
        }
    }
    pub fn verify(&self, frame: &Frame) {
        if frame
            .documents
            .values()
            .any(|d| d.get("workspace_id").is_some())
        {
            assert!(self.apply.is_sensitive());
            self.apply.emit_clicked();
        }
    }
    pub fn update(&self, frame: &Frame) {
        let message = frame.compositor["unavailable"]
            .as_str()
            .or_else(|| frame.compositor["error"].as_str())
            .or_else(|| frame.compositor["overview"]["reason"].as_str())
            .unwrap_or("");
        self.notice.set_text(message);
        self.notice.set_visible(!message.is_empty());
        let doc = frame
            .documents
            .values()
            .find(|d| d.get("workspace_id").is_some());
        let mut entries = BTreeMap::new();
        fn walk(value: &Value, entries: &mut BTreeMap<String, String>, frame: &Frame) {
            match value {
                Value::Object(m) => {
                    if let Some(id) = m.get("surface_id").and_then(Value::as_str) {
                        let title = frame
                            .documents
                            .get(id)
                            .and_then(|d| d["title"].as_str())
                            .or_else(|| frame.host_surfaces[id]["title"].as_str())
                            .unwrap_or("Unavailable view");
                        let unavailable = frame
                            .host_surfaces
                            .get(id)
                            .map(|h| h["availability"] != "available")
                            .unwrap_or(false);
                        entries.insert(
                            id.into(),
                            format!(
                                "{title}{}",
                                if unavailable { " · disconnected" } else { "" }
                            ),
                        );
                    }
                    for v in m.values() {
                        walk(v, entries, frame)
                    }
                }
                Value::Array(a) => {
                    for v in a {
                        walk(v, entries, frame)
                    }
                }
                _ => {}
            }
        }
        if let Some(doc) = doc {
            walk(&doc["outputs"], &mut entries, frame);
        }
        for (id, document) in &frame.documents {
            if document.get("surface_id").is_some() {
                entries.entry(id.clone()).or_insert_with(|| {
                    format!(
                        "{} · available view",
                        document["title"].as_str().unwrap_or("Native view")
                    )
                });
            }
        }
        for (id, host) in frame
            .host_surfaces
            .as_object()
            .into_iter()
            .flat_map(|h| h.iter())
        {
            if host["activity_id"].as_str() == frame.activity.as_deref() {
                entries.entry(id.clone()).or_insert_with(|| {
                    format!(
                        "{} · {}",
                        host["title"].as_str().unwrap_or("Application"),
                        if host["availability"] == "available" {
                            "available view"
                        } else {
                            "disconnected"
                        }
                    )
                });
            }
        }
        let ids = entries.keys().cloned().collect::<Vec<_>>();
        let names = entries.values().map(String::as_str).collect::<Vec<_>>();
        let outputs = doc
            .and_then(|d| d["outputs"].as_object())
            .map(|o| o.keys().cloned().collect::<Vec<_>>())
            .unwrap_or_default();
        let mut current = self.state.borrow_mut();
        if current.0 != ids
            || (0..self.surface_model.n_items())
                .map(|i| self.surface_model.string(i).unwrap().to_string())
                .collect::<Vec<_>>()
                != names
        {
            let selected = current.0.get(self.surfaces.selected() as usize).cloned();
            let target = current.0.get(self.targets.selected() as usize).cloned();
            self.surface_model
                .splice(0, self.surface_model.n_items(), &names);
            self.target_model
                .splice(0, self.target_model.n_items(), &names);
            self.surfaces.set_selected(
                ids.iter()
                    .position(|id| Some(id) == selected.as_ref())
                    .unwrap_or(0) as u32,
            );
            self.targets.set_selected(
                ids.iter()
                    .position(|id| Some(id) == target.as_ref())
                    .unwrap_or(0) as u32,
            );
        }
        if current.1 != outputs {
            let labels = outputs.iter().map(String::as_str).collect::<Vec<_>>();
            self.output_model
                .splice(0, self.output_model.n_items(), &labels);
            self.outputs.set_selected(0);
        }
        *current = (ids, outputs, doc.cloned());
        self.apply
            .set_sensitive(frame.connected && current.2.is_some() && !current.0.is_empty());
        self.undo_cursor.set(frame.workspace_undo);
        self.undo
            .set_sensitive(frame.connected && frame.workspace_undo.is_some());
    }
}
