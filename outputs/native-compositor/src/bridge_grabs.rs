//! Pointer previews stay local; a frozen core revision is committed only on release.
use super::*;
use std::time::Instant;
#[derive(Clone)]
pub struct Preview {
    pub rect: Rect,
    pub active: bool,
}
struct Lease {
    workspace: String,
    surface: String,
    output: String,
    revision: Value,
    renewed: Instant,
}
pub struct Grabs {
    leases: BTreeMap<String, Lease>,
    previews: Arc<Mutex<BTreeMap<String, Preview>>>,
}
impl Grabs {
    pub fn new(previews: Arc<Mutex<BTreeMap<String, Preview>>>) -> Self {
        Self {
            leases: BTreeMap::new(),
            previews,
        }
    }
    fn end(&mut self, socket: &PathBuf, runtime: &str) {
        if let Some(lease) = self.leases.remove(runtime) {
            let _ = call(
                socket,
                &json!({"op":"interaction.end","surface_id":lease.workspace}),
            );
        }
        self.previews.lock().unwrap().remove(runtime);
    }
    pub fn renew(&mut self, socket: &PathBuf) {
        let expired = self
            .leases
            .iter_mut()
            .filter_map(|(id, lease)| {
                if lease.renewed.elapsed() < Duration::from_secs(10) {
                    return None;
                }
                lease.renewed = Instant::now();
                call(
                    socket,
                    &json!({"op":"interaction.renew","surface_id":lease.workspace}),
                )
                .err()
                .map(|_| id.clone())
            })
            .collect::<Vec<_>>();
        for id in expired {
            self.end(socket, &id)
        }
    }
    pub fn stop(&mut self, socket: &PathBuf) {
        for id in self.leases.keys().cloned().collect::<Vec<_>>() {
            self.end(socket, &id)
        }
    }
    pub fn handle(
        &mut self,
        socket: &PathBuf,
        scene: &Scene,
        value: &Value,
    ) -> Option<Result<Value, String>> {
        let op = value["op"].as_str()?;
        if !op.starts_with("workspace.grab.") {
            return None;
        }
        let runtime = value["runtime"].as_str().unwrap_or("");
        let result = (|| match op {
            "workspace.grab.begin" => {
                if self.leases.contains_key(runtime) {
                    return Err("Pointer interaction already active".into());
                }
                let surface = scene
                    .identities
                    .get(runtime)
                    .ok_or("Surface identity unavailable")?;
                let doc = scene
                    .workspaces
                    .as_object()
                    .into_iter()
                    .flat_map(|d| d.values())
                    .find(|d| placed_surfaces(&json!({"documents":{"w":d}})).contains(surface))
                    .ok_or("Surface is not placed")?;
                let output = doc["outputs"]
                    .as_object()
                    .into_iter()
                    .flat_map(|o| o.iter())
                    .find(|(_, o)| {
                        placed_surfaces(
                            &json!({"documents":{"w":{"workspace_id":"w","outputs":{"o":o}}}}),
                        )
                        .contains(surface)
                    })
                    .map(|(id, _)| id.clone())
                    .ok_or("Output unavailable")?;
                let workspace = doc["workspace_id"]
                    .as_str()
                    .ok_or("Workspace required")?
                    .to_string();
                let response = call(
                    socket,
                    &json!({"op":"interaction.begin","surface_id":workspace}),
                )?;
                if response["surface_revision"] != doc["revision"] {
                    // Acquire once, then inspect under that lease. Renderer
                    // element-focus bookkeeping must not invalidate a drag
                    // when every placement and policy field is unchanged.
                    let refreshed = call(
                        socket,
                        &json!({"op":"presentation.get","document_id":workspace}),
                    );
                    let acceptable = refreshed.as_ref().is_ok_and(|current| {
                        current["revision"] == response["surface_revision"]
                            && crate::input_revision::only_element_focus_changed(doc, current)
                    });
                    if !acceptable {
                        let _ = call(
                            socket,
                            &json!({"op":"interaction.end","surface_id":workspace}),
                        );
                        return Err(refreshed.err().unwrap_or_else(|| {
                            "Workspace changed before pointer interaction began".into()
                        }));
                    }
                }
                self.leases.insert(
                    runtime.into(),
                    Lease {
                        workspace,
                        surface: surface.clone(),
                        output,
                        revision: response["surface_revision"].clone(),
                        renewed: Instant::now(),
                    },
                );
                if let Some(preview) = self.previews.lock().unwrap().get_mut(runtime) {
                    preview.active = true;
                }
                Ok(json!({"leased":true}))
            }
            "workspace.grab.finish" => {
                let lease = self
                    .leases
                    .get(runtime)
                    .ok_or("Pointer lease unavailable")?;
                let rect = self
                    .previews
                    .lock()
                    .unwrap()
                    .get(runtime)
                    .ok_or("Pointer preview unavailable")?
                    .rect;
                let stamp = std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap_or_default()
                    .as_nanos();
                call(
                    socket,
                    &json!({"op":"presentation.apply","protocol":"agentos.presentation/1","catalog_revision":"native-core/1","request_id":format!("grab-{}-{stamp}",std::process::id()),"expected_revisions":{&lease.workspace:lease.revision},"operations":[{"op":"workspace.edit","workspace_id":lease.workspace,"edit":{"kind":"float","surface_id":lease.surface,"output_id":lease.output,"x":rect.x,"y":rect.y,"width":rect.width,"height":rect.height}}]}),
                )
            }
            "workspace.grab.cancel" => Ok(json!({"cancelled":true})),
            _ => Err("Unknown pointer interaction".into()),
        })();
        if op != "workspace.grab.begin" || result.is_err() {
            self.end(socket, runtime)
        }
        Some(result)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        io::{BufRead, BufReader, Write},
        os::unix::net::UnixListener,
    };
    #[test]
    fn release_commits_frozen_revision_and_always_releases_lease() {
        for reject in [false, true] {
            let stamp = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos();
            let path =
                std::env::temp_dir().join(format!("grab-{}-{stamp}.sock", std::process::id()));
            let listener = UnixListener::bind(&path).unwrap();
            let worker = thread::spawn(move || {
                let mut requests = vec![];
                for step in 0..3 {
                    let (mut stream, _) = listener.accept().unwrap();
                    let mut line = String::new();
                    BufReader::new(&mut stream).read_line(&mut line).unwrap();
                    let request: Value = serde_json::from_str(&line).unwrap();
                    requests.push(request);
                    let response = if step == 1 && reject {
                        json!({"ok":false,"error":"stale_revision"})
                    } else {
                        json!({"ok":true,"result":{"surface_revision":42}})
                    };
                    writeln!(stream, "{response}").unwrap();
                }
                requests
            });
            let previews = Arc::new(Mutex::new(BTreeMap::from([(
                "runtime".into(),
                Preview {
                    rect: Rect {
                        x: 20,
                        y: 30,
                        width: 320,
                        height: 240,
                    },
                    active: false,
                },
            )])));
            let mut grabs = Grabs::new(previews.clone());
            let scene = Scene {
                identities: BTreeMap::from([("runtime".into(), "surface".into())]),
                workspaces: json!({"w":{"workspace_id":"w","revision":42,"outputs":{"display":{"tiles":{"kind":"leaf","surface_id":"surface"},"floating":[],"maximized":null}}}}),
                ..Scene::default()
            };
            assert!(grabs
                .handle(
                    &path,
                    &scene,
                    &json!({"op":"workspace.grab.begin","runtime":"runtime"})
                )
                .unwrap()
                .is_ok());
            assert!(previews.lock().unwrap()["runtime"].active);
            let result = grabs
                .handle(
                    &path,
                    &scene,
                    &json!({"op":"workspace.grab.finish","runtime":"runtime"}),
                )
                .unwrap();
            assert_eq!(result.is_err(), reject);
            assert!(grabs.leases.is_empty());
            assert!(previews.lock().unwrap().is_empty());
            let requests = worker.join().unwrap();
            assert_eq!(requests[0]["op"], "interaction.begin");
            assert_eq!(requests[1]["expected_revisions"]["w"], 42);
            assert_eq!(requests[1]["operations"][0]["edit"]["x"], 20);
            assert_eq!(requests[2]["op"], "interaction.end");
            std::fs::remove_file(path).unwrap();
        }
    }
    #[test]
    fn pointer_begin_reconciles_only_element_focus_and_never_replays_its_lease() {
        for mutation in [
            json!({}),
            json!({"constraints":[{"surface_id":"surface"}]}),
            json!({"activity_id":"2"}),
            json!({"focus":{"surface_id":"other","element_id":null}}),
            json!({"future_policy":true}),
            json!({"outputs":{}}),
            json!({"revision":5}),
        ] {
            let allowed = mutation == json!({});
            let baseline = json!({"protocol":"agentos.presentation/1","workspace_id":"w","activity_id":"1","revision":3,"outputs":{"display":{"tiles":{"kind":"leaf","surface_id":"surface"},"floating":[],"maximized":null}},"constraints":[],"focus":{"surface_id":"surface","element_id":"editor"}});
            let mut current = baseline.clone();
            current["revision"] = json!(4);
            current["focus"]["element_id"] = Value::Null;
            for (key, value) in mutation.as_object().unwrap() {
                current[key] = value.clone();
            }
            let path = std::env::temp_dir().join(format!(
                "grab-focus-{}-{}.sock",
                std::process::id(),
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap()
                    .as_nanos()
            ));
            let listener = UnixListener::bind(&path).unwrap();
            let worker = thread::spawn(move || {
                let mut requests = vec![];
                loop {
                    let (mut stream, _) = listener.accept().unwrap();
                    let mut line = String::new();
                    BufReader::new(&mut stream).read_line(&mut line).unwrap();
                    let value: Value = serde_json::from_str(&line).unwrap();
                    let result = if value["op"] == "presentation.get" {
                        current.clone()
                    } else {
                        json!({"surface_revision":4})
                    };
                    writeln!(stream, "{}", json!({"ok":true,"result":result})).unwrap();
                    let ended = value["op"] == "interaction.end";
                    requests.push(value);
                    if ended {
                        break;
                    }
                }
                requests
            });
            let previews = Arc::new(Mutex::new(BTreeMap::from([(
                "runtime".into(),
                Preview {
                    rect: Rect {
                        x: 0,
                        y: 0,
                        width: 320,
                        height: 240,
                    },
                    active: false,
                },
            )])));
            let mut grabs = Grabs::new(previews.clone());
            let scene = Scene {
                identities: BTreeMap::from([("runtime".into(), "surface".into())]),
                workspaces: json!({"w":baseline}),
                ..Scene::default()
            };
            let result = grabs
                .handle(
                    &path,
                    &scene,
                    &json!({"op":"workspace.grab.begin","runtime":"runtime"}),
                )
                .unwrap();
            let leased = grabs
                .leases
                .get("runtime")
                .map(|lease| lease.revision.clone());
            let active = previews
                .lock()
                .unwrap()
                .get("runtime")
                .is_some_and(|preview| preview.active);
            grabs.stop(&path);
            let requests = worker.join().unwrap();
            std::fs::remove_file(&path).unwrap();
            assert_eq!(
                requests
                    .iter()
                    .filter(|request| request["op"] == "interaction.begin")
                    .count(),
                1,
                "A pointer lease was replayed"
            );
            assert_eq!(requests.last().unwrap()["op"], "interaction.end");
            assert!(grabs.leases.is_empty() && previews.lock().unwrap().is_empty());
            assert_eq!(
                result.is_ok(),
                allowed,
                "Pointer begin must accept only element-focus bookkeeping: {mutation}; {result:?}"
            );
            assert_eq!(active, allowed);
            assert_eq!(leased, allowed.then(|| json!(4)));
        }
    }
}
