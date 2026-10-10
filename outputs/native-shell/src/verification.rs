//! Executed only by the explicit --self-test verification mode on a private display.
use super::*;
use std::sync::mpsc;
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
    assert_eq!(surface.revision, Some(12));
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
        ui::install_theme(&gtk::gdk::Display::default().unwrap(),Appearance::Dark,1.0,true);
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
        verify_container_replacement(app,&frame,&commands,&drafts);
        let mut controls=controls::Controls::new(app,commands.clone());controls.verify_controls(&frame,&commands);
        let gestures=rx.try_iter().collect::<Vec<_>>();assert!(gestures.iter().any(|c|matches!(c,Command::Ask{prompt,..} if prompt=="Explicit native request λ")));assert!(gestures.iter().any(|c|matches!(c,Command::CreateDocument)));

        controls.verify_output(&frame,&commands);
        let output_commands=rx.try_iter().collect::<Vec<_>>();
        assert!(output_commands.iter().any(|command|matches!(command,Command::FreezeOutput(10))));
        assert!(output_commands.iter().any(|command|matches!(command,Command::FollowOutput(true))));
        assert!(output_commands.iter().any(|command|matches!(command,Command::PageOutput(-1))));
        let mut surface=Surface::new(app,"native-fixture",&commands);surface.update("native-fixture",&doc,&frame,&commands,&drafts);
        if std::env::var("AGENT_OS_NATIVE_TEST_SKIP_FILE_REVIEW").as_deref()!=Ok("1"){document_dialog::verify_review(surface.window.upcast_ref());}
        let paintable=gtk::WidgetPaintable::new(Some(&surface.scroll));let quit=app.clone();let capture=capture.clone();
        glib::timeout_add_local_once(Duration::from_millis(std::env::var("AGENT_OS_NATIVE_TEST_DELAY_MS").ok().and_then(|s|s.parse::<u64>().ok()).unwrap_or(700).clamp(700,10000)),move || {
            println!("CHECK: mapped native surface");
            let image=surface.elements["image"].image.as_ref().unwrap();assert!(image.picture.paintable().is_some());assert_eq!(image.caption.text(),"Native blue pixel");
            println!("CHECK: authenticated immutable image resource and native texture");
            assert_eq!(surface.elements["editor"].area.as_ref().unwrap().value(),"Document body λ\n日本語");
            let pty=surface.elements["pty"].pty.as_ref().unwrap();assert!(!pty.view.input_enabled());assert!(!pty.attach.is_sensitive());
            pty.view.feed(b"Terminal fixture\r\n",false).unwrap();
            println!("CHECK: native PTY renderer remains detached without running authorized work");

            let outcome=surface.elements["result"].outcome.as_ref().unwrap();assert_eq!(outcome.widget.accessible_role(),gtk::AccessibleRole::Status);assert_eq!(outcome.message.text(),"succeeded");
            let failure=surface.elements["failure"].outcome.as_ref().unwrap();assert_eq!(failure.widget.accessible_role(),gtk::AccessibleRole::Alert);assert_eq!(failure.message.text(),"Fixture reason 日本語");assert!(!failure.recovery.is_visible());

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
            doc["elements"]["root"]["slots"]["children"]=json!(["field","reading","status","button","link","progress"]);
            surface.update("native-fixture",&doc,&frame,&commands,&drafts);
            println!("CHECK: reordered retained widgets");
            assert_eq!(surface.elements["reading"].widget,widget);assert_eq!(field.entry.text(),"Unsaved λ 日本語");
            assert_eq!(surface.elements["root"].container.as_ref().unwrap().first_child().unwrap(),field.widget.clone().upcast::<gtk::Widget>());
            assert!(!surface.elements["button"].button.as_ref().unwrap().is_sensitive());
            doc["actions"]["click"]=json!({"ref":"fixture-action"});doc["elements"]["button"]["events"]=json!({"activate":{"action":"click"}});doc["elements"]["field"]["events"]=json!({"submit":{"action":"click"}});doc["revision"]=json!(2);
            frame.actions.insert("fixture-action".into(),json!({"available":true}));surface.update("native-fixture",&doc,&frame,&commands,&drafts);
            doc["elements"]["failure"]["events"]=json!({"recover":{"action":"click"}});surface.update("native-fixture",&doc,&frame,&commands,&drafts);
            let failure=surface.elements["failure"].outcome.as_ref().unwrap();assert!(failure.recovery.is_sensitive());failure.recovery.emit_clicked();
            assert!(rx.try_iter().any(|c|matches!(c,Command::Action{reference,action,..} if reference=="fixture-action" && action=="click")));
            surface.elements["button"].button.as_ref().unwrap().emit_clicked();
            assert!(rx.try_iter().any(|c|matches!(c,Command::Action{reference,..} if reference=="fixture-action")));
            field.entry.emit_activate();
            assert_eq!(rx.try_iter().filter(|c|matches!(c,Command::Action{reference,..} if reference=="fixture-action")).count(),1,"Text field submit must dispatch exactly once");
            let editor=surface.elements["editor"].area.as_ref().unwrap();editor.view.buffer().set_text("Human edited document 日本語");
            let toolbar=surface.elements["editor"].widget.last_child().unwrap();let save=toolbar.first_child().unwrap().downcast::<gtk::Button>().unwrap();save.emit_clicked();
            assert!(rx.try_iter().any(|c|matches!(c,Command::ResolveDraft{surface,element,commit:true,revision:2} if surface=="native-fixture" && element=="editor")));
            frame.connected=false;surface.update("native-fixture",&doc,&frame,&commands,&drafts);assert_eq!(field.entry.text(),"Unsaved λ 日本語");
            // Capture after GTK has rendered the verified final state.
            glib::timeout_add_local_once(Duration::from_millis(180),move || {
            if let Some(path)=capture {let snapshot=gtk::Snapshot::new();paintable.snapshot(&snapshot,surface.scroll.width() as f64,surface.scroll.height() as f64);let node=snapshot.to_node().unwrap();surface.window.renderer().unwrap().render_texture(&node,None).save_to_png(path).unwrap();}
            println!("PASS: real core IPC, native catalog rendering, Unicode selection, live source updates, preserved drafts, keyed reordering, scoped action dispatch, offline retained view");
            surface.window.destroy();quit.quit();
            });
        });
    });
    app.run_with_args(&["agent-os-desktop-verification"]);
}
