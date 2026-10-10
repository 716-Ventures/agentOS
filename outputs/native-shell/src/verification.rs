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
        let mut frame=Frame{connected:true,..Frame::default()};
        let bindings=transport::request(&socket,&json!({"op":"binding.snapshot","surface_id":"native-fixture"})).unwrap();frame.bindings.insert("native-fixture".into(),bindings);
        let (commands,rx)=mpsc::channel();let drafts=Arc::new(Mutex::new(BTreeMap::new()));
        let mut surface=Surface::new(app,"native-fixture",&commands);surface.update("native-fixture",&doc,&frame,&commands,&drafts);
        let paintable=gtk::WidgetPaintable::new(Some(&surface.scroll));let quit=app.clone();let capture=capture.clone();
        glib::timeout_add_local_once(Duration::from_millis(700),move || {
            let reading=surface.elements["reading"].label.clone().unwrap();
            let field=surface.elements["field"].field.clone().unwrap();
            assert_eq!(reading.layout().unknown_glyphs_count(),0);reading.select_region(0,-1);
            let widget=surface.elements["reading"].widget.clone();
            doc["revision"]=json!(1);doc["elements"]["reading"]["props"]["text"]=json!("Concurrent replacement");
            frame.bindings.insert("native-fixture".into(),json!({"bindings":{"work":{"availability":"available","value":"running"}}}));
            surface.update("native-fixture",&doc,&frame,&commands,&drafts);
            assert_eq!(reading.text(),"Native café · 日本語 · select this text");
            assert_eq!(surface.elements["status"].label.as_ref().unwrap().text(),"running");
            reading.select_region(0,0);field.entry.grab_focus();field.entry.set_text("Unsaved λ 日本語");
            assert_eq!(drafts.lock().unwrap()[&("native-fixture".into(),"field".into())].text,"Unsaved λ 日本語");
            surface.update("native-fixture",&doc,&frame,&commands,&drafts);assert_eq!(field.entry.text(),"Unsaved λ 日本語");
            // Simulate a durable flush; the retained local editor must still own its value.
            drafts.lock().unwrap().values_mut().for_each(|d|d.dirty=false);
            surface.elements["button"].button.as_ref().unwrap().grab_focus();
            doc["elements"]["root"]["slots"]["children"]=json!(["field","reading","status","button","link","progress"]);
            surface.update("native-fixture",&doc,&frame,&commands,&drafts);
            assert_eq!(surface.elements["reading"].widget,widget);assert_eq!(field.entry.text(),"Unsaved λ 日本語");
            assert_eq!(surface.elements["root"].container.as_ref().unwrap().first_child().unwrap(),field.widget.clone().upcast::<gtk::Widget>());
            assert!(!surface.elements["button"].button.as_ref().unwrap().is_sensitive());
            doc["actions"]["click"]=json!({"ref":"fixture-action"});doc["elements"]["button"]["events"]=json!({"activate":{"action":"click"}});doc["revision"]=json!(2);
            frame.actions.insert("fixture-action".into(),json!({"available":true}));surface.update("native-fixture",&doc,&frame,&commands,&drafts);
            surface.elements["button"].button.as_ref().unwrap().emit_clicked();
            assert!(rx.try_iter().any(|c|matches!(c,Command::Action{reference,..} if reference=="fixture-action")));
            frame.connected=false;surface.update("native-fixture",&doc,&frame,&commands,&drafts);assert_eq!(field.entry.text(),"Unsaved λ 日本語");
            if let Some(path)=capture {let snapshot=gtk::Snapshot::new();paintable.snapshot(&snapshot,surface.scroll.width() as f64,surface.scroll.height() as f64);let node=snapshot.to_node().unwrap();surface.window.renderer().unwrap().render_texture(&node,None).save_to_png(path).unwrap();}
            println!("PASS: real core IPC, native catalog rendering, Unicode selection, live source updates, preserved drafts, keyed reordering, scoped action dispatch, offline retained view");
            surface.window.destroy();quit.quit();
        });
    });
    app.run_with_args(&["agent-os-desktop-verification"]);
}
