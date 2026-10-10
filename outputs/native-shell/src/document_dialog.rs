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
