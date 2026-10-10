//! Explicit graphical verification fixture; never installed in the runtime.
use seven_sixteen_ui::gtk::{self, glib, prelude::*};
fn main() {
    let app = gtk::Application::builder()
        .application_id("com.agentos.MinimumFixture")
        .build();
    app.connect_activate(|app| {
        let window = gtk::ApplicationWindow::builder()
            .application(app)
            .title("Minimum size fixture")
            .child(&gtk::Label::new(Some(
                "This view requires 1600 × 900 logical units.",
            )))
            .build();
        window.set_size_request(1600, 900);
        window.present();
        let app = app.clone();
        glib::timeout_add_local_once(std::time::Duration::from_secs(12), move || app.quit());
    });
    app.run_with_args(&["minimum-fixture"]);
}
