//! Explicit --self-test and opt-in private IME fixture setup.
use super::*;
use std::sync::mpsc;
fn verify_focused_draft_resolution(app: &gtk::Application, frame: &Frame, commands: &Sender<Command>) {
    fn edit(element: &Element, value: &str) {
        if let Some(field)=&element.field { field.entry.set_text(value); }
        if let Some(area)=&element.area { area.view.buffer().set_text(value); }
        if let Some(choice)=&element.choice { choice.control.set_selected(if value=="First" {0} else {1}); }
        if let Some(toggle)=&element.toggle { toggle.control.set_active(value=="true"); }
    }
    fn value(element: &Element) -> String {
        if let Some(field)=&element.field { return field.entry.text().into(); }
        if let Some(area)=&element.area { return area.value(); }
        if let Some(choice)=&element.choice { return choice.options()[choice.control.selected() as usize].clone(); }
        if let Some(toggle)=&element.toggle { return toggle.control.is_active().to_string(); }
        unreachable!()
    }
    for (kind,mut props,saved,edited) in [
        ("TextField@1",json!({"label":"Focused field","value":"Saved λ 日本語"}),"Saved λ 日本語","Next λ 日本語"),
        ("TextField@1",json!({"label":"Focused multiline","multiline":true,"value":"Saved λ 日本語"}),"Saved λ 日本語","Next λ 日本語"),
        ("DocumentEditor@1",json!({"label":"Focused document","value":"Saved λ 日本語"}),"Saved λ 日本語","Next λ 日本語"),
        ("Choice@1",json!({"label":"Focused choice","options":["First","Second"],"value":"First"}),"First","Second"),
        ("Toggle@1",json!({"label":"Focused toggle","value":false}),"false","true"),
    ] {
        let id="focused-resolution";let key=(id.into(),"control".into());
        let mut frame=frame.clone();let drafts=Arc::new(Mutex::new(BTreeMap::new()));
        let mut doc=json!({"surface_id":id,"activity_id":"1","revision":0,"title":"Focused human resolution","root":"control","elements":{"control":{"type":kind,"props":props}},"actions":{},"bindings":{}});
        let mut surface=Surface::new(app,id,commands);surface.update(id,&doc,&frame,commands,&drafts);
        let element=&surface.elements["control"];
        let focused=if let Some(field)=&element.field {field.entry.grab_focus()} else if let Some(area)=&element.area {area.view.grab_focus()} else if let Some(choice)=&element.choice {choice.control.grab_focus()} else {element.toggle.as_ref().unwrap().control.grab_focus()};
        assert!(focused,"{kind} did not accept widget focus");
        edit(element,edited);assert_eq!(value(element),edited);
        surface.update(id,&doc,&frame,commands,&drafts);assert_eq!(value(&surface.elements["control"]),edited,"Background reconciliation replaced focused input");
        drafts.lock().unwrap().insert(key.clone(),Draft{text:saved.into(),expected:4,dirty:false,resolved:Some(0),acknowledged:None});
        frame.drafts.insert(key.clone(),json!({"draft_revision":4,"draft":null}));
        surface.update(id,&doc,&frame,commands,&drafts);
        assert_eq!(value(&surface.elements["control"]),saved,"Human resolution did not replace focused {kind}");
        assert!(!drafts.lock().unwrap().contains_key(&key),"Resolved marker did not retire");
        edit(&surface.elements["control"],edited);
        let next=drafts.lock().unwrap()[&key].clone();assert!(next.dirty);assert_eq!(next.expected,4,"Next edit reused an obsolete construction-time draft revision");
        props["value"]=if kind=="Toggle@1" {json!(true)} else {json!(edited)};doc["elements"]["control"]["props"]=props;
        surface.update(id,&doc,&frame,commands,&drafts);assert_eq!(value(&surface.elements["control"]),edited);
        // The core has committed this user's previous value, but newer typing
        // has already begun before the renderer receives that revision.
        doc["revision"]=json!(1);
        edit(&surface.elements["control"],saved);
        drafts.lock().unwrap().insert(key.clone(),Draft{text:saved.into(),expected:6,dirty:true,resolved:None,acknowledged:Some((1,edited.into()))});
        frame.drafts.insert(key.clone(),json!({"draft_revision":6,"draft":saved}));
        surface.update(id,&doc,&frame,commands,&drafts);
        assert_eq!(surface.revision,Some(1),"Own Save left the displayed revision frozen for {kind}");
        assert_eq!(value(&surface.elements["control"]),saved,"Acknowledged Save erased newer typing for {kind}");
        assert!(drafts.lock().unwrap()[&key].dirty);
        assert_eq!(surface.elements["control"].events.borrow()["revision"],1);
        surface.window.destroy();
    }
    println!("CHECK: focused human Save/Discard resolution applies to text, multiline, document, choice and toggle; later edits use the acknowledged draft revision and background updates preserve input");
}

fn verify_validation_feedback(app: &gtk::Application, frame: &Frame, commands: &Sender<Command>) {
    for (kind,multiline) in [("TextField@1",false),("TextField@1",true),("DocumentEditor@1",false),("Choice@1",false),("Toggle@1",false)] {
        let id="validation-resolution"; let key=(id.into(),"control".into());
        let drafts=Arc::new(Mutex::new(BTreeMap::new()));
        let mut doc=json!({"surface_id":id,"activity_id":"1","revision":0,"title":"Validation feedback","root":"control","elements":{"control":{"type":kind,"props":{"label":"Stable editor","value":"Saved","multiline":multiline}}},"actions":{},"bindings":{}});
        if kind!="TextField@1" {doc["elements"]["control"]["props"].as_object_mut().unwrap().remove("multiline");}
        if kind=="Choice@1" {doc["elements"]["control"]["props"]["options"]=json!(["Saved","Unsaved λ 日本語"]);}
        if kind=="Toggle@1" {doc["elements"]["control"]["props"]["value"]=json!(false);}
        let mut surface=Surface::new(app,id,commands);surface.update(id,&doc,frame,commands,&drafts);
        let element=&surface.elements["control"];let original=element.widget.clone();
        if let Some(field)=&element.field {assert!(field.entry.grab_focus());field.entry.set_text("Unsaved λ 日本語");field.entry.select_region(0,3);}
        if let Some(area)=&element.area {assert!(area.view.grab_focus());area.view.buffer().set_text("Unsaved λ 日本語");area.view.buffer().select_range(&area.view.buffer().start_iter(),&area.view.buffer().iter_at_offset(3));}
        if let Some(choice)=&element.choice {assert!(choice.control.grab_focus());choice.control.set_selected(1);}
        if let Some(toggle)=&element.toggle {assert!(toggle.control.grab_focus());toggle.control.set_active(true);}
        let focus=gtk::prelude::RootExt::focus(&surface.window);let draft=drafts.lock().unwrap()[&key].clone();
        for (revision,message) in [(1,Some("Literal <b>日本語</b> λ")),(2,Some("Choose another name.")),(3,None),(4,Some("Keep selected error"))] {
            doc["revision"]=json!(revision);
            if let Some(message)=message {doc["elements"]["control"]["props"]["validation_message"]=json!(message);} else {doc["elements"]["control"]["props"].as_object_mut().unwrap().remove("validation_message");}
            surface.update(id,&doc,frame,commands,&drafts);
            let element=&surface.elements["control"];assert_eq!(element.widget,original);assert_eq!(surface.revision,Some(revision));
            assert_eq!(gtk::prelude::RootExt::focus(&surface.window),focus);
            let feedback=element.validation.as_ref().unwrap();assert_eq!(feedback.label.is_visible(),message.is_some());assert_eq!(feedback.label.text(),message.unwrap_or(""));
            if let Some(field)=&element.field {assert_eq!(field.entry.text(),"Unsaved λ 日本語");assert_eq!(field.entry.selection_bounds(),Some((0,3)));}
            if let Some(area)=&element.area {assert_eq!(area.value(),"Unsaved λ 日本語");assert_eq!(area.view.buffer().selection_bounds().map(|(a,b)|(a.offset(),b.offset())),Some((0,3)));}
            if let Some(choice)=&element.choice {assert_eq!(choice.value().as_deref(),Some("Unsaved λ 日本語"));}
            if let Some(toggle)=&element.toggle {assert!(toggle.control.is_active());assert!(!toggle.control.is_inconsistent());}
            let current=drafts.lock().unwrap()[&key].clone();assert_eq!((current.text,current.expected,current.dirty,current.resolved,current.acknowledged),(draft.text.clone(),draft.expected,draft.dirty,draft.resolved,draft.acknowledged.clone()));
        }
        let label=surface.elements["control"].validation.as_ref().unwrap().label.clone();label.select_region(0,4);
        doc["revision"]=json!(5);doc["elements"]["control"]["props"]["validation_message"]=json!("Deferred error");
        surface.update(id,&doc,frame,commands,&drafts);assert_eq!(surface.revision,Some(4));assert_eq!(label.text(),"Keep selected error");
        label.select_region(0,0);surface.update(id,&doc,frame,commands,&drafts);assert_eq!(surface.revision,Some(5));assert_eq!(label.text(),"Deferred error");
        for prop in ["value","label"] {let mut unsafe_doc=doc.clone();unsafe_doc["revision"]=json!(6);unsafe_doc["elements"]["control"]["props"][prop]=json!("Background replacement");surface.update(id,&unsafe_doc,frame,commands,&drafts);assert_eq!(surface.revision,Some(5));assert_eq!(surface.elements["control"].widget,original);}
        surface.window.destroy();
    }
    println!("CHECK: inline validation preserves text/document/choice/toggle identity, logical focus and draft values; text and error selections defer replacement and unrelated changes remain blocked");
}

fn verify_form_owners(frame: &Frame, commands: &Sender<Command>) {
    let drafts = Arc::new(Mutex::new(BTreeMap::new()));
    let baseline = Arc::strong_count(&drafts);
    let mut recovered = frame.clone();
    recovered.drafts.insert(("form-owners".into(), "toggle".into()), json!({"draft_revision":7,"draft":"unavailable"}));
    let element = construct("form-owners", "1", "toggle", &json!({"type":"Toggle@1","props":{"label":"Recover toggle","value":false}}), &recovered, commands, &drafts);
    let toggle = element.toggle.as_ref().unwrap();
    let notice = element.selection_notice.as_ref().unwrap();
    assert!(toggle.control.is_inconsistent() && notice.is_visible());
    toggle.control.set_active(true);
    assert!(!toggle.control.is_inconsistent() && !notice.is_visible());
    assert_eq!(drafts.lock().unwrap()[&("form-owners".into(), "toggle".into())].text, "true");
    let weak = toggle.control.downgrade();
    let warning = notice.downgrade();
    drop(element);
    assert!(weak.upgrade().is_none(), "Closed toggle retained its own change callback");
    assert!(warning.upgrade().is_none(), "Closed toggle retained its recovery notice");
    assert_eq!(Arc::strong_count(&drafts), baseline, "Closed toggle retained shared drafts");
    for (id, node) in [
        ("choice", json!({"type":"Choice@1","props":{"label":"Choice","options":["First","Second"],"value":"First"}})),
        ("field", json!({"type":"TextField@1","props":{"label":"Field","value":"Original"}})),
        ("multiline", json!({"type":"TextField@1","props":{"label":"Multiline","multiline":true,"value":"Original"}})),
        ("editor", json!({"type":"DocumentEditor@1","props":{"label":"Editor","value":"Original"}})),
    ] {
        let element = construct("form-owners", "1", id, &node, frame, commands, &drafts);
        let weak = element.widget.downgrade();
        if let Some(area) = &element.area {
            area.view.buffer().set_text("Edited λ\n日本語");
            assert_eq!(drafts.lock().unwrap()[&("form-owners".into(), id.into())].text, "Edited λ\n日本語");
        }
        drop(element);
        assert!(weak.upgrade().is_none(), "Closed {id} retained its native container");
        assert_eq!(Arc::strong_count(&drafts), baseline, "Closed {id} retained shared drafts");
    }
    println!("CHECK: recovered toggle correction and final native control/notice/draft-owner release");
    println!("CHECK: choice, text field, multiline and document editor release native owners and shared drafts");
}
fn verify_container_replacement(
    app: &gtk::Application,
    frame: &Frame,
    commands: &Sender<Command>,
    drafts: &Arc<Mutex<BTreeMap<(String, String), Draft>>>,
) {
    let id = "container-reconciliation";
    let mut surface = Surface::new(app, id, commands);
    surface.window.set_visible(false);
    let mut doc = json!({"surface_id":id,"activity_id":"1","title":"Container reconciliation","revision":0,"root":"root","elements":{"root":{"type":"Stack@1","props":{},"slots":{"children":["a","b"]}},"a":{"type":"Text@1","props":{"text":"Stable a"}},"b":{"type":"Text@1","props":{"text":"Stable b"}}}});
    surface.update(id, &doc, frame, commands, drafts);
    let a = surface.elements["a"].widget.clone();
    let b = surface.elements["b"].widget.clone();
    let old = surface.elements["root"].widget.clone();
    doc["revision"] = json!(1);
    doc["elements"]["root"]["type"] = json!("Row@1");
    surface.update(id, &doc, frame, commands, drafts);
    let row = surface.elements["root"].widget.clone();
    assert_ne!(old, row);
    assert_eq!(surface.elements["a"].widget, a);
    assert_eq!(a.parent().as_ref(), Some(&row));
    doc["revision"] = json!(2);
    doc["elements"]["group"] = json!({"type":"Stack@1","props":{},"slots":{"children":["a","b"]}});
    doc["elements"]["root"]["slots"]["children"] = json!(["group"]);
    surface.update(id, &doc, frame, commands, drafts);
    assert_eq!(a.parent().as_ref(), Some(&surface.elements["group"].widget));
    doc["revision"] = json!(3);
    doc["elements"].as_object_mut().unwrap().remove("group");
    doc["elements"]["root"]["slots"]["children"] = json!(["a", "b"]);
    surface.update(id, &doc, frame, commands, drafts);
    assert_eq!(a.parent().as_ref(), Some(&row));
    assert_eq!(b.parent().as_ref(), Some(&row));
    assert_eq!(surface.elements["b"].widget, b);
    doc["revision"] = json!(4);
    doc["elements"]["root"] = json!({"type":"Section@1","props":{"label":"Grouped details"},"slots":{"children":["region"]}});
    doc["elements"]["region"] = json!({"type":"Scroll@1","props":{"label":"Scrollable details","spacing":"compact"},"slots":{"children":["a","b"]}});
    surface.update(id, &doc, frame, commands, drafts);
    let section = surface.elements["root"].section.as_ref().unwrap();
    assert_eq!(
        section.heading.accessible_role(),
        gtk::AccessibleRole::Heading
    );
    assert_eq!(section.heading.text(), "Grouped details");
    let region = surface.elements["region"].region.as_ref().unwrap();
    assert_eq!(a.parent().as_ref(), Some(&region.content.clone().upcast()));
    assert_eq!(region.content.spacing(), 6);
    assert_eq!(
        region.widget.parent().as_ref(),
        Some(&section.content.clone().upcast())
    );
    doc["revision"] = json!(5);
    doc["elements"]["root"]["props"]["label"] = json!("Updated details");
    doc["elements"]["a"]["props"]["role"] = json!("heading");
    surface.update(id, &doc, frame, commands, drafts);
    assert_eq!(
        surface.elements["root"]
            .section
            .as_ref()
            .unwrap()
            .heading
            .text(),
        "Updated details"
    );
    assert_eq!(
        surface.elements["a"]
            .label
            .as_ref()
            .unwrap()
            .accessible_role(),
        gtk::AccessibleRole::Heading
    );
    assert_eq!(surface.elements["b"].widget, b);
    doc["revision"] = json!(6);
    doc["elements"]["a"]["props"]["role"] = json!("text");
    surface.update(id, &doc, frame, commands, drafts);
    assert_eq!(
        surface.elements["a"]
            .label
            .as_ref()
            .unwrap()
            .accessible_role(),
        gtk::AccessibleRole::Label
    );
    doc["revision"] = json!(7);
    doc["elements"]["root"] =
        json!({"type":"Split@1","props":{"label":"Comparison"},"slots":{"children":["a","b"]}});
    doc["elements"].as_object_mut().unwrap().remove("region");
    surface.update(id, &doc, frame, commands, drafts);
    let split = surface.elements["root"].split.as_ref().unwrap();
    assert_eq!(
        split.children(),
        vec![surface.elements["a"].widget.clone(), b.clone()]
    );
    split.widget.set_position(120);
    let position = split.widget.position();
    doc["revision"] = json!(8);
    doc["elements"]["root"]["props"]["label"] = json!("Updated comparison");
    surface.update(id, &doc, frame, commands, drafts);
    assert_eq!(
        surface.elements["root"]
            .split
            .as_ref()
            .unwrap()
            .widget
            .position(),
        position
    );
    doc["revision"] = json!(9);
    doc["elements"]["root"] = json!({"type":"Tabs@1","props":{"label":"Details","labels":["A","B"]},"slots":{"children":["a","b"]}});
    surface.update(id, &doc, frame, commands, drafts);
    assert!(surface.elements["root"]
        .tabs
        .as_ref()
        .unwrap()
        .select_key("b"));
    doc["revision"] = json!(10);
    doc["elements"]["root"]["slots"]["children"] = json!(["b", "a"]);
    doc["elements"]["root"]["props"]["labels"] = json!(["B renamed", "A"]);
    surface.update(id, &doc, frame, commands, drafts);
    let tabs = surface.elements["root"].tabs.as_ref().unwrap();
    assert_eq!(tabs.selected_key().as_deref(), Some("b"));
    assert_eq!(tabs.widget.tab_label_text(&b).as_deref(), Some("B renamed"));
    assert_eq!(surface.elements["b"].widget, b);
    doc["revision"] = json!(11);
    doc["elements"]["root"]["slots"]["children"] = json!(["a"]);
    doc["elements"]["root"]["props"]["labels"] = json!(["A"]);
    doc["elements"].as_object_mut().unwrap().remove("b");
    surface.update(id, &doc, frame, commands, drafts);
    assert_eq!(
        surface.elements["root"]
            .tabs
            .as_ref()
            .unwrap()
            .selected_key()
            .as_deref(),
        Some("a")
    );
    doc["revision"] = json!(12);
    doc["elements"]["root"] =
        json!({"type":"Stack@1","props":{},"slots":{"children":["a","choice","toggle"]}});
    doc["elements"]["choice"] = json!({"type":"Choice@1","props":{"label":"Density","options":["Compact","Comfortable"],"value":"Comfortable"}});
    doc["elements"]["toggle"] = json!({"type":"Toggle@1","props":{"label":"Wrap","value":true}});
    surface.update(id, &doc, frame, commands, drafts);
    surface.elements["choice"]
        .choice
        .as_ref()
        .unwrap()
        .control
        .set_selected(0);
    surface.elements["toggle"]
        .toggle
        .as_ref()
        .unwrap()
        .control
        .set_active(false);
    assert_eq!(
        drafts.lock().unwrap()[&(id.into(), "choice".into())].text,
        "Compact"
    );
    assert_eq!(
        drafts.lock().unwrap()[&(id.into(), "toggle".into())].text,
        "false"
    );
    doc["revision"] = json!(13);
    surface.update(id, &doc, frame, commands, drafts);
    assert_eq!(
        surface.elements["choice"]
            .choice
            .as_ref()
            .unwrap()
            .value()
            .as_deref(),
        Some("Compact")
    );
    assert!(!surface.elements["toggle"]
        .toggle
        .as_ref()
        .unwrap()
        .control
        .is_active());
    // An otherwise identical document may advance its revision while drafts
    // remain local; no GTK children or committed field values are replaced.
    assert_eq!(surface.revision, Some(13));
    drafts
        .lock()
        .unwrap()
        .retain(|(surface, _), _| surface != id);
    surface.update(id, &doc, frame, commands, drafts);
    assert_eq!(
        surface.elements["choice"]
            .choice
            .as_ref()
            .unwrap()
            .value()
            .as_deref(),
        Some("Comfortable")
    );
    assert!(surface.elements["toggle"]
        .toggle
        .as_ref()
        .unwrap()
        .control
        .is_active());
    assert!(
        !drafts
            .lock()
            .unwrap()
            .keys()
            .any(|(surface, _)| surface == id),
        "Programmatic reconciliation must not create edits"
    );
    doc["revision"] = json!(14);
    doc["elements"]["root"]["slots"]["children"] =
        json!(["a", "choice", "toggle", "rich", "chart"]);
    doc["elements"]["rich"] = json!({"type":"RichText@1","props":{"runs":[{"text":"Literal <b>日本語</b>","style":"strong"}]}});
    doc["elements"]["chart"] = json!({"type":"Chart@1","props":{"label":"Comparison","points":[{"id":"loss","label":"Loss","value":-2.5},{"id":"gain","label":"Gain","value":7.0}]}});
    surface.update(id, &doc, frame, commands, drafts);
    assert_eq!(
        surface.elements["rich"].label.as_ref().unwrap().text(),
        "Literal <b>日本語</b>"
    );
    let chart = surface.elements["chart"].chart.as_ref().unwrap();
    assert_eq!(chart.data.row_count(), 2);
    assert!(chart.data.select_key("gain"));
    doc["revision"] = json!(15);
    doc["elements"]["chart"]["props"]["points"] = json!([{"id":"gain","label":"Gain updated","value":8.0},{"id":"loss","label":"Loss","value":-2.5}]);
    surface.update(id, &doc, frame, commands, drafts);
    assert_eq!(
        surface.elements["chart"]
            .chart
            .as_ref()
            .unwrap()
            .data
            .selected_key()
            .as_deref(),
        Some("gain")
    );
    surface.window.destroy();
}
pub fn run(socket: PathBuf, capture: Option<String>) {
    let app = gtk::Application::builder()
        .application_id("com.agentos.DesktopVerification")
        .build();
    app.connect_activate(move |app| {
        apply_preferences(&gtk::gdk::Display::default().unwrap());
        let state=transport::request(&socket,&json!({"op":"presentation.snapshot"})).expect("Real core snapshot");
        let mut doc=state["documents"]["native-fixture"].clone();assert!(doc.is_object());
        transport::request(&socket,&json!({"op":"host.renderer","surface_id":"native-fixture"})).expect("Authenticated fixture renderer");
        let mut frame=Frame{connected:true,..Frame::default()};
        frame.documents=serde_json::from_value(state["documents"].clone()).unwrap();frame.host_surfaces=state["host_surfaces"].clone();
        let bindings=transport::request(&socket,&json!({"op":"binding.snapshot","surface_id":"native-fixture"})).unwrap();frame.bindings.insert("native-fixture".into(),bindings);
        let reference=doc["elements"]["image"]["props"]["reference"].as_str().unwrap();
        let image=transport::request(&socket,&json!({"op":"resource.get","activity_id":doc["activity_id"],"reference":reference})).unwrap();
        frame.resources.insert(reference.into(),Arc::new(ui::content::image_hex(image["png_hex"].as_str().unwrap()).unwrap()));
        let (commands,rx)=mpsc::channel();let drafts=Arc::new(Mutex::new(BTreeMap::new()));
        frame.core=transport::request(&socket,&json!({"op":"snapshot"})).unwrap();frame.activity=doc["activity_id"].as_str().map(String::from);frame.usage=json!({"unavailable":true});frame.broker=json!([]);
        verify_form_owners(&frame,&commands);
        verify_focused_draft_resolution(app,&frame,&commands);
        verify_validation_feedback(app,&frame,&commands);
        verify_container_replacement(app,&frame,&commands,&drafts);
        image_controls::verify();
        let mut controls=controls::Controls::new(app,commands.clone());controls.verify_controls(&frame,&commands);
        let gestures=rx.try_iter().collect::<Vec<_>>();assert!(gestures.iter().any(|c|matches!(c,Command::Ask{prompt,..} if prompt=="Explicit native request λ")));assert!(gestures.iter().any(|c|matches!(c,Command::CreateDocument)));

        controls.verify_context_request(&frame);
        let context_commands=rx.try_iter().collect::<Vec<_>>();
        for (prompt,selection) in [("Contextual native request λ","Original selected λ 日本語"),("Refreshed contextual request","Later selection must not replace captured evidence")] {
            let context=context_commands.iter().find_map(|c|match c {Command::Ask{prompt:p,grounding:Some(context),..} if p==prompt=>Some(context),_=>None}).expect("Contextual request missing");
            assert_eq!(context["modality"],"typed");assert_eq!(context["selection"],selection);assert_eq!(context["element_id"],"field");assert_eq!(context["layout_revision"],7);
            assert_eq!(context["input_id"].as_str().unwrap().len(),32);
            assert!(context["selection_captured_at"].as_f64().unwrap()<=context["captured_at"].as_f64().unwrap());
        }
        input_context::verify(app,&frame,&commands,&drafts);
        println!("CHECK: typed request preserves immutable selected context; reopening captures the new selection");
        controls.verify_output(&frame,&commands);
        let output_commands=rx.try_iter().collect::<Vec<_>>();
        assert!(output_commands.iter().any(|command|matches!(command,Command::FreezeOutput(10))));
        assert!(output_commands.iter().any(|command|matches!(command,Command::FollowOutput(true))));
        assert!(output_commands.iter().any(|command|matches!(command,Command::PageOutput(-1))));
        let mut surface=Surface::new(app,"native-fixture",&commands);surface.update("native-fixture",&doc,&frame,&commands,&drafts);
        if std::env::var("AGENT_OS_NATIVE_TEST_SKIP_FILE_REVIEW").as_deref()!=Ok("1"){document_dialog::verify_review(surface.window.upcast_ref());draft_dialog::verify(surface.window.upcast_ref());}
        let paintable=gtk::WidgetPaintable::new(Some(&surface.window));let quit=app.clone();let capture=capture.clone();
        glib::timeout_add_local_once(Duration::from_millis(std::env::var("AGENT_OS_NATIVE_TEST_DELAY_MS").ok().and_then(|s|s.parse::<u64>().ok()).unwrap_or(700).clamp(700,10000)),move || {
            println!("CHECK: mapped native surface");
            if let Ok(maximum)=std::env::var("AGENT_OS_NATIVE_TEST_MAX_WIDTH") {
                let maximum=maximum.parse::<i32>().unwrap();
                assert!(surface.window.width()<=maximum,"Native view {} exceeds logical output {}",surface.window.width(),maximum);
            }
            let image=surface.elements["image"].image.as_ref().unwrap();assert!(image.picture.paintable().is_some());assert_eq!(image.caption.text(),"Native blue pixel");
            println!("CHECK: authenticated immutable image resource and native texture");
            assert_eq!(surface.elements["editor"].area.as_ref().unwrap().value(),"Document body λ\n日本語");
            let pty=surface.elements["pty"].pty.as_ref().unwrap();assert!(!pty.view.input_enabled());assert!(!pty.attach.is_sensitive());
            pty.view.feed(b"Terminal fixture\r\n",false).unwrap();
            input_context::verify_terminal_selection(&surface.elements["pty"]);
            println!("CHECK: native PTY renderer remains detached without running authorized work");

            let outcome=surface.elements["result"].outcome.as_ref().unwrap();assert_eq!(outcome.widget.accessible_role(),gtk::AccessibleRole::Status);assert_eq!(outcome.message.text(),"succeeded");
            let failure=surface.elements["failure"].outcome.as_ref().unwrap();assert_eq!(failure.widget.accessible_role(),gtk::AccessibleRole::Alert);assert_eq!(failure.message.text(),"Fixture reason 日本語");assert!(!failure.recovery.is_visible());

            // Real renderer binding refresh must expose the latest observed value
            // without replacing the human-selected snapshot or dispatching actions.
            let original_bindings=frame.bindings["native-fixture"].clone();
            let outcome=surface.elements["result"].outcome.as_ref().unwrap();
            assert!(outcome.message.grab_focus());outcome.message.select_region(0,-1);
            frame.bindings.get_mut("native-fixture").unwrap()["bindings"]["work"]["value"]=json!("failed 日本語");
            surface.update("native-fixture",&doc,&frame,&commands,&drafts);
            let outcome=surface.elements["result"].outcome.as_ref().unwrap();
            assert_eq!(outcome.message.text(),"succeeded");assert!(outcome.message.selection_bounds().is_some());
            assert!(outcome.current.is_visible());assert_eq!(outcome.current.text(),"Current value:\nCompletion\nfailed 日本語");
            assert_eq!(outcome.current.accessible_role(),gtk::AccessibleRole::Status);
            frame.bindings.get_mut("native-fixture").unwrap()["bindings"]["work"]["availability"]=json!("disconnected");
            surface.update("native-fixture",&doc,&frame,&commands,&drafts);
            let outcome=surface.elements["result"].outcome.as_ref().unwrap();
            assert_eq!(outcome.message.text(),"succeeded");assert!(outcome.message.selection_bounds().is_some());
            assert_eq!(outcome.current.text(),"Current value:\nCompletion\nUnavailable");
            frame.bindings.get_mut("native-fixture").unwrap()["bindings"]["work"]["availability"]=json!("available");
            surface.update("native-fixture",&doc,&frame,&commands,&drafts);
            assert_eq!(surface.elements["result"].outcome.as_ref().unwrap().current.text(),"Current value:\nCompletion\nfailed 日本語");
            frame.connected=false;
            surface.update("native-fixture",&doc,&frame,&commands,&drafts);
            let outcome=surface.elements["result"].outcome.as_ref().unwrap();
            assert_eq!(outcome.current.text(),"Current value:\nCompletion\nUnavailable","Disconnected core retained a live-looking outcome");
            outcome.message.select_region(0,0);
            surface.update("native-fixture",&doc,&frame,&commands,&drafts);
            let outcome=surface.elements["result"].outcome.as_ref().unwrap();
            assert_eq!(outcome.message.text(),"Unavailable");assert!(!outcome.current.is_visible());
            frame.connected=true;
            frame.bindings.insert("native-fixture".into(),original_bindings);
            surface.update("native-fixture",&doc,&frame,&commands,&drafts);
            assert_eq!(surface.elements["result"].outcome.as_ref().unwrap().message.text(),"succeeded");
            assert!(!rx.try_iter().any(|c|matches!(c,Command::Action{..})),"Binding refresh dispatched an action");
            println!("CHECK: selected outcome retains snapshot while current failure/disconnection stays visible and reconciles after deselection");

            let reference=surface.elements["reference"].reference.as_ref().unwrap();assert!(reference.widget.is_sensitive());reference.widget.emit_clicked();
            assert!(rx.try_iter().any(|c|matches!(c,Command::Navigate{surface,element,revision} if surface=="native-fixture" && element=="reference" && revision==doc["revision"].as_u64().unwrap())));
            let mut missing=frame.clone();missing.documents.remove("native-fixture");surface.update("native-fixture",&doc,&missing,&commands,&drafts);
            assert!(!surface.elements["reference"].reference.as_ref().unwrap().widget.is_sensitive());
            surface.update("native-fixture",&doc,&frame,&commands,&drafts);
            assert!(surface.elements["reference"].reference.as_ref().unwrap().widget.is_sensitive());
            println!("CHECK: reference intent, revision and target disappearance/reappearance");
            let table=surface.elements["table"].table.as_ref().unwrap();assert_eq!(table.row_count(),200);assert!(table.select_key("row-7"));assert_eq!(table.selected_key().as_deref(),Some("row-7"));
            let list=surface.elements["list"].list.as_ref().unwrap();assert_eq!(list.row_count(),200);assert!(list.select_key("item-7"));assert_eq!(list.selected_key().as_deref(),Some("item-7"));
            assert_eq!(surface.elements["details"].list.as_ref().unwrap().row_count(),2);
            controls.verify_history(&frame,&commands);
            println!("CHECK: virtualized work history with stable identities and recycled controls");
            let reading=surface.elements["reading"].label.clone().unwrap();
            let field=surface.elements["field"].field.clone().unwrap();
            assert_eq!(reading.layout().unknown_glyphs_count(),0);reading.select_region(0,-1);
            let widget=surface.elements["reading"].widget.clone();
            doc["revision"]=json!(1);doc["elements"]["reading"]["props"]["text"]=json!("Concurrent replacement");
            frame.bindings.insert("native-fixture".into(),json!({"bindings":{"work":{"availability":"available","value":"running"}}}));
            surface.update("native-fixture",&doc,&frame,&commands,&drafts);
            assert_eq!(reading.text(),"Native café · 日本語 · select this text");
            assert_eq!(surface.elements["status"].label.as_ref().unwrap().text(),"running");
            println!("CHECK: selection and live binding preserved");
            frame.bindings.get_mut("native-fixture").unwrap()["bindings"]["numeric"]=json!({"availability":"available","value":2});
            surface.update("native-fixture",&doc,&frame,&commands,&drafts);
            let progress=surface.elements["progress"].progress.as_ref().unwrap();assert_eq!(progress.fraction(),0.0);assert_eq!(progress.text().as_deref(),Some("Source unavailable"));
            frame.bindings.get_mut("native-fixture").unwrap()["bindings"]["numeric"]["value"]=json!(0.5);
            surface.update("native-fixture",&doc,&frame,&commands,&drafts);assert_eq!(surface.elements["progress"].progress.as_ref().unwrap().fraction(),0.5);
            println!("CHECK: typed numeric progress and invalid-range availability");
            reading.select_region(0,0);field.entry.grab_focus();field.entry.set_text("Unsaved λ 日本語");
            assert_eq!(drafts.lock().unwrap()[&("native-fixture".into(),"field".into())].text,"Unsaved λ 日本語");
            surface.update("native-fixture",&doc,&frame,&commands,&drafts);assert_eq!(field.entry.text(),"Unsaved λ 日本語");
            println!("CHECK: local edit preserved");
            // Simulate a durable flush; the retained local editor must still own its value.
            drafts.lock().unwrap().values_mut().for_each(|d|{d.dirty=false;d.resolved=Some(1);d.expected=1;});
            frame.drafts.insert(("native-fixture".into(),"field".into()),json!({"draft_revision":1,"draft":null}));doc["elements"]["field"]["props"]["value"]=json!("Unsaved λ 日本語");
            surface.elements["link"].link.as_ref().unwrap().grab_focus();
            doc["elements"]["root"]["slots"]["children"]=json!(["field","reading","status","button","link","progress"]);doc["revision"]=json!(2);
            surface.update("native-fixture",&doc,&frame,&commands,&drafts);
            println!("CHECK: reordered retained widgets");
            assert_eq!(surface.elements["reading"].widget,widget);assert_eq!(field.entry.text(),"Unsaved λ 日本語");
            assert_eq!(surface.elements["root"].container.as_ref().unwrap().first_child().unwrap(),field.widget.clone().upcast::<gtk::Widget>());
            assert!(!surface.elements["button"].button.as_ref().unwrap().widget.is_sensitive());
            doc["actions"]["click"]=json!({"ref":"fixture-action"});doc["elements"]["button"]["events"]=json!({"activate":{"action":"click"}});doc["elements"]["field"]["events"]=json!({"submit":{"action":"click"}});doc["revision"]=json!(3);
            frame.actions.insert("fixture-action".into(),json!({"available":true}));surface.update("native-fixture",&doc,&frame,&commands,&drafts);
            doc["elements"]["failure"]["events"]=json!({"recover":{"action":"click"}});surface.update("native-fixture",&doc,&frame,&commands,&drafts);
            let failure=surface.elements["failure"].outcome.as_ref().unwrap();assert!(failure.recovery.is_sensitive());failure.recovery.emit_clicked();
            assert!(rx.try_iter().any(|c|matches!(c,Command::Action{reference,action,..} if reference=="fixture-action" && action=="click")));
            surface.elements["button"].button.as_ref().unwrap().widget.emit_clicked();
            assert!(rx.try_iter().any(|c|matches!(c,Command::Action{reference,..} if reference=="fixture-action")));
            let retained_button=surface.elements["button"].button.as_ref().unwrap().widget.clone();
            retained_button.add_css_class("host-fixture-class");
            assert!(retained_button.grab_focus());
            doc["revision"]=json!(4);
            doc["elements"]["button"]["props"]=json!({"label":"Next action λ","variant":"outline","size":"xs","icon":"arrow-right","icon_position":"only"});
            surface.update("native-fixture",&doc,&frame,&commands,&drafts);
            assert_eq!(surface.elements["button"].button.as_ref().unwrap().widget,retained_button);
            assert_eq!(gtk::prelude::GtkWindowExt::focus(&surface.window),Some(retained_button.clone().upcast()));
            assert!(retained_button.has_css_class("host-fixture-class"));
            assert!(retained_button.has_css_class("seven-icon-only"));
            assert!(rx.try_iter().all(|c|!matches!(c,Command::Action{..})),"Rendering dispatched an action");
            retained_button.emit_clicked();
            assert_eq!(rx.try_iter().filter(|c|matches!(c,Command::Action{reference,revision:4,..} if reference=="fixture-action")).count(),1);
            doc["revision"]=json!(5);doc["elements"]["button"]["props"]["icon"]=json!("unregistered-host-icon");
            surface.update("native-fixture",&doc,&frame,&commands,&drafts);
            assert!(!retained_button.is_sensitive());retained_button.emit_clicked();
            assert!(rx.try_iter().all(|c|!matches!(c,Command::Action{..})),"Rejected props retained a stale action");
            doc["revision"]=json!(6);doc["elements"]["button"]["props"]["icon"]=json!("arrow-right");
            surface.update("native-fixture",&doc,&frame,&commands,&drafts);
            assert!(retained_button.is_sensitive());retained_button.emit_clicked();
            assert_eq!(rx.try_iter().filter(|c|matches!(c,Command::Action{reference,revision:6,..} if reference=="fixture-action")).count(),1);
            frame.actions.get_mut("fixture-action").unwrap()["available"]=json!(false);
            surface.update("native-fixture",&doc,&frame,&commands,&drafts);assert!(!retained_button.is_sensitive());
            retained_button.emit_clicked();assert!(rx.try_iter().all(|c|!matches!(c,Command::Action{..})),"Unavailable button retained dispatch");
            frame.actions.get_mut("fixture-action").unwrap()["available"]=json!(true);
            surface.update("native-fixture",&doc,&frame,&commands,&drafts);
            println!("CHECK: bounded button styles retain identity, focus and guarded action revision; invalid frames clear dispatch and recover safely");
            field.entry.emit_activate();
            assert_eq!(rx.try_iter().filter(|c|matches!(c,Command::Action{reference,..} if reference=="fixture-action")).count(),1,"Text field submit must dispatch exactly once");
            let editor=surface.elements["editor"].area.as_ref().unwrap();editor.view.buffer().set_text("Human edited document 日本語");
            let toolbar=surface.elements["editor"].widget.last_child().unwrap();let save=toolbar.first_child().unwrap().first_child().unwrap().downcast::<gtk::Button>().unwrap();save.emit_clicked();
            assert!(rx.try_iter().any(|c|matches!(c,Command::ResolveDraft{surface,element,commit:true,revision:6} if surface=="native-fixture" && element=="editor")));
            frame.connected=false;surface.update("native-fixture",&doc,&frame,&commands,&drafts);assert_eq!(field.entry.text(),"Unsaved λ 日本語");
            // Capture after GTK has rendered the verified final state.
            glib::timeout_add_local_once(Duration::from_millis(180),move || {
            if let Some(path)=capture {let snapshot=gtk::Snapshot::new();paintable.snapshot(&snapshot,surface.window.width() as f64,surface.window.height() as f64);let node=snapshot.to_node().unwrap();surface.window.renderer().unwrap().render_texture(&node,None).save_to_png(path).unwrap();}
            println!("PASS: real core IPC, native catalog rendering, Unicode selection, live source updates, preserved drafts, keyed reordering, scoped action dispatch, offline retained view");
            surface.window.destroy();quit.quit();
            });
        });
    });
    app.run_with_args(&["agent-os-desktop-verification"]);
}

// GTK 4.14's AT-SPI Component.GrabFocus is explicitly unsupported. Set up
// widget focus in this opt-in fixture; AT-SPI independently checks its state,
// edits, deliberate Save and final core value. This does not test physical input.
pub(super) fn focus_ime_fixture(surface: &Surface) -> bool {
    surface
        .elements
        .get("field")
        .is_some_and(|element| {
            element.field.as_ref().is_some_and(|field| field.entry.is_mapped() && field.entry.grab_focus())
                || element.area.as_ref().is_some_and(|area| area.view.is_mapped() && area.view.grab_focus())
        })
}

pub(super) fn select_ime_editor_fixture(surface: &Surface) -> bool {
    surface.elements.get("field").and_then(|element| element.area.as_ref()).is_some_and(|area| {
        let buffer = area.view.buffer();
        if buffer.char_count() != 65536 { return false; }
        if !area.view.grab_focus() { return false; }
        if let Some(path) = std::env::var_os("AGENT_OS_NATIVE_IME_OBSERVATION") {
            let path = std::path::PathBuf::from(path);
            area.view.connect_preedit_changed(move |view, text| {
                let observation = json!({"preedit_bytes":text.len(),"characters":view.buffer().char_count()});
                let temporary = path.with_extension("pending");
                std::fs::write(&temporary, observation.to_string()).expect("Write private IME fixture observation");
                std::fs::rename(&temporary, &path).expect("Publish private IME fixture observation");
            });
        }
        buffer.select_range(&buffer.start_iter(), &buffer.iter_at_offset(3));
        true
    })
}
