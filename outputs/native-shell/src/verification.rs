//! Executed only by the explicit --self-test verification mode on a private display.
use super::*;
use std::sync::mpsc;
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
        let (commands,rx)=mpsc::channel();let drafts=Arc::new(Mutex::new(BTreeMap::new()));
        frame.core=transport::request(&socket,&json!({"op":"snapshot"})).unwrap();frame.activity=doc["activity_id"].as_str().map(String::from);frame.usage=json!({"unavailable":true});frame.broker=json!([]);
        let mut controls=controls::Controls::new(app,commands.clone());controls.verify_controls(&frame,&commands);
        assert!(rx.try_iter().any(|c|matches!(c,Command::Ask{prompt,..} if prompt=="Explicit native request λ")));

        controls.verify_output(&frame,&commands);
        let output_commands=rx.try_iter().collect::<Vec<_>>();
        assert!(output_commands.iter().any(|command|matches!(command,Command::FreezeOutput(10))));
        assert!(output_commands.iter().any(|command|matches!(command,Command::FollowOutput(true))));
        assert!(output_commands.iter().any(|command|matches!(command,Command::PageOutput(-1))));
        let mut surface=Surface::new(app,"native-fixture",&commands);surface.update("native-fixture",&doc,&frame,&commands,&drafts);
        let paintable=gtk::WidgetPaintable::new(Some(&surface.scroll));let quit=app.clone();let capture=capture.clone();
        glib::timeout_add_local_once(Duration::from_millis(std::env::var("AGENT_OS_NATIVE_TEST_DELAY_MS").ok().and_then(|s|s.parse::<u64>().ok()).unwrap_or(700).clamp(700,10000)),move || {
            println!("CHECK: mapped native surface");
            let table=surface.elements["table"].table.as_ref().unwrap();assert_eq!(table.row_count(),200);assert!(table.select_key("row-7"));assert_eq!(table.selected_key().as_deref(),Some("row-7"));
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
            surface.elements["button"].button.as_ref().unwrap().emit_clicked();
            assert!(rx.try_iter().any(|c|matches!(c,Command::Action{reference,..} if reference=="fixture-action")));
            field.entry.emit_activate();
            assert_eq!(rx.try_iter().filter(|c|matches!(c,Command::Action{reference,..} if reference=="fixture-action")).count(),1,"Text field submit must dispatch exactly once");
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
