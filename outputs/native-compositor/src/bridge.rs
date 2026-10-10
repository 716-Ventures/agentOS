//! Core-owned workspaces. IPC and document reconciliation never run on the render thread.
use crate::{control::Request, policy::Rect};
use serde_json::{json, Value};
use std::{
    collections::{BTreeMap, BTreeSet},
    io::{BufRead, BufReader, Read, Write},
    os::unix::net::UnixStream,
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, AtomicI64, Ordering},
        mpsc::{self, SyncSender},
        Arc, Mutex,
    },
    thread,
    time::Duration,
};
#[path = "bridge_grabs.rs"]
mod grabs;
#[derive(Clone, Debug, PartialEq)]
pub struct Observed {
    pub id: String,
    pub title: String,
    pub app_id: String,
    pub uid: u32,
    pub session: String,
    pub min_width: i32,
    pub min_height: i32,
}
#[derive(Clone, Default)]
pub struct Scene {
    pub rectangles: BTreeMap<String, Rect>,
    pub identities: BTreeMap<String, String>,
    pub workspaces: Value,
    pub focus: Option<String>,
    pub maximized: BTreeSet<String>,
    pub error: Option<String>,
    pub overview: Value,
    pub visible: BTreeSet<String>,
}
#[derive(Clone)]
struct Observation {
    windows: Vec<Observed>,
    area: Rect,
}
pub struct Bridge {
    observation: Arc<Mutex<Option<Observation>>>,
    pub scene: Arc<Mutex<Scene>>,
    pub commands: SyncSender<Request>,
    stop: Arc<AtomicBool>,
    last_input: Arc<AtomicI64>,
    worker: Option<thread::JoinHandle<()>>,
    pub previews: Arc<Mutex<BTreeMap<String, grabs::Preview>>>,
}
impl Bridge {
    pub fn start(socket: PathBuf) -> Self {
        let observation = Arc::new(Mutex::new(None::<Observation>));
        let scene = Arc::new(Mutex::new(Scene::default()));
        let stop = Arc::new(AtomicBool::new(false));
        let (commands, rx) = mpsc::sync_channel::<Request>(32);
        let (input, output, stopping) = (observation.clone(), scene.clone(), stop.clone());
        let previews = Arc::new(Mutex::new(BTreeMap::new()));
        let worker_previews = previews.clone();
        let last_input = Arc::new(AtomicI64::new(0));
        let input_cursor = last_input.clone();
        let worker = thread::spawn(move || {
            let mut grabs = grabs::Grabs::new(worker_previews);
            let mut registrations = BTreeMap::<String, (String, String, String, String)>::new();
            let mut counter = 0u64;
            let mut input_error = None::<(String, std::time::Instant)>;
            let mut published = BTreeMap::new();
            let mut output_area = None;
            let mut selected_activity = None::<String>;
            let mut first_seen = BTreeMap::<String, std::time::Instant>::new();
            let mut nonce = [0u8; 16];
            if std::fs::File::open("/dev/urandom")
                .and_then(|mut f| f.read_exact(&mut nonce))
                .is_err()
            {
                return;
            }
            let prefix = nonce.iter().map(|b| format!("{b:02x}")).collect::<String>();
            while !stopping.load(Ordering::Relaxed) {
                // Bounded command queue; each operation has exact core revision checks.
                for req in rx.try_iter().take(8) {
                    let scene = output.lock().unwrap().clone();
                    let result = if let Some(result) = grabs.handle(&socket, &scene, &req.value) {
                        result
                    } else {
                        match req.value["op"].as_str() {
                            Some("workspace.transaction") => {
                                call(&socket, &req.value["transaction"])
                            }
                            Some("workspace.activity") => call(&socket, &json!({"op":"snapshot"}))
                                .and_then(|s| {
                                    let activity = req.value["activity_id"]
                                        .as_str()
                                        .ok_or("Activity identity required")?;
                                    if !s["activities"]
                                        .as_array()
                                        .into_iter()
                                        .flatten()
                                        .any(|a| a["id"].to_string() == activity)
                                    {
                                        return Err("Activity unavailable".into());
                                    }
                                    selected_activity = Some(activity.into());
                                    Ok(json!({"activity_id":activity}))
                                }),
                            Some("workspace.apply") => put(
                                &socket,
                                &req.value["document"],
                                req.value["expected_revision"].clone(),
                                req.value["request_id"].as_str().unwrap_or(""),
                            ),
                            Some("workspace.undo") => call(
                                &socket,
                                &json!({"op":"presentation.undo","event_cursor":req.value["event_cursor"],"request_id":req.value["request_id"]}),
                            ),
                            _ => Err("Unknown shared workspace operation".into()),
                        }
                    };
                    if let Ok(value) = &result {
                        let op = req.value["op"].as_str().unwrap_or("");
                        if op == "workspace.undo" {
                            input_cursor.store(0, Ordering::Relaxed);
                        } else if op == "workspace.grab.finish"
                            || op == "workspace.apply"
                            || (op == "workspace.transaction"
                                && req.value["transaction"]["operations"][0]["edit"]["kind"]
                                    != "focus")
                        {
                            if let Some(cursor) = value["event_cursor"].as_i64() {
                                input_cursor.store(cursor, Ordering::Relaxed);
                            }
                        }
                    }
                    if let Err(e) = &result {
                        input_error = Some((e.clone(), std::time::Instant::now()));
                        output.lock().unwrap().error = Some(e.clone());
                    }
                    let response = match result {
                        Ok(value) => json!({"ok":true,"result":value}),
                        Err(e) => json!({"ok":false,"error":e}),
                    };
                    let _ = req.reply.try_send(response);
                }
                grabs.renew(&socket);
                let observed = input.lock().unwrap().clone();
                if let Some(observed) = observed {
                    let result = (|| -> Result<Scene, String> {
                        let mut state = call(&socket, &json!({"op":"presentation.snapshot"}))?;
                        let activities = call(&socket, &json!({"op":"snapshot"}))?;
                        let available = activities["activities"]
                            .as_array()
                            .ok_or("No active activity")?;
                        let activity = selected_activity
                            .as_ref()
                            .filter(|id| available.iter().any(|a| a["id"].to_string() == **id))
                            .cloned()
                            .or_else(|| available.first().map(|a| a["id"].to_string()))
                            .ok_or("No active activity")?;
                        if output_area != Some(observed.area) {
                            call(
                                &socket,
                                &json!({"op":"outputs.register","output_id":"nested-primary","width":observed.area.width,"height":observed.area.height}),
                            )?;
                            output_area = Some(observed.area);
                        }
                        let mut identities = BTreeMap::new();
                        let live = observed
                            .windows
                            .iter()
                            .map(|w| w.id.clone())
                            .collect::<BTreeSet<_>>();
                        for (runtime, (surface, owned, title, app)) in registrations.clone() {
                            if !live.contains(&runtime) {
                                call(
                                    &socket,
                                    &json!({"op":"host.surface","surface_id":surface,"activity_id":owned,"title":title,"app_id":app,"connected":false}),
                                )?;
                                registrations.remove(&runtime);
                                published.remove(&runtime);
                            }
                        }
                        let mut added = BTreeMap::<String, Vec<String>>::new();
                        first_seen.retain(|id, _| live.contains(id));
                        for w in &observed.windows {
                            let seen = *first_seen
                                .entry(w.id.clone())
                                .or_insert_with(std::time::Instant::now);
                            if stopping.load(Ordering::Relaxed) {
                                return Err("Compositor stopping".into());
                            }
                            if let Some(surface) = native_identity(w, &state) {
                                identities.insert(w.id.clone(), surface);
                                continue;
                            }
                            // A pending reserved identity is not promoted on an unverified app-id claim.
                            if w.app_id.starts_with("agentos.surface.") {
                                continue;
                            }
                            if !registrations.contains_key(&w.id) {
                                if seen.elapsed() < Duration::from_millis(300) {
                                    continue;
                                }
                                counter += 1;
                                registrations.insert(
                                    w.id.clone(),
                                    (
                                        format!("app-{prefix}-{counter}"),
                                        activity.clone(),
                                        w.title.clone(),
                                        w.app_id.clone(),
                                    ),
                                );
                            }
                            let entry = registrations.get_mut(&w.id).unwrap();
                            entry.2 = w.title.clone();
                            entry.3 = w.app_id.clone();
                            if published.get(&w.id) != Some(entry)
                                || state["host_surfaces"].get(&entry.0).is_none()
                            {
                                call(
                                    &socket,
                                    &json!({"op":"host.surface","surface_id":entry.0,"activity_id":entry.1,"title":entry.2,"app_id":entry.3,"connected":true}),
                                )?;
                                published.insert(w.id.clone(), entry.clone());
                            }
                            identities.insert(w.id.clone(), entry.0.clone());
                        }
                        let placed = placed_surfaces(&state);
                        for surface in identities.values() {
                            if placed.contains(surface) {
                                continue;
                            }
                            let owned = state["documents"][surface]["activity_id"]
                                .as_str()
                                .map(String::from)
                                .or_else(|| {
                                    registrations
                                        .values()
                                        .find(|r| &r.0 == surface)
                                        .map(|r| r.1.clone())
                                });
                            if let Some(owned) = owned {
                                added.entry(owned).or_default().push(surface.clone());
                            }
                        }
                        for (owned, surfaces) in added {
                            let existing = state["documents"].as_object().and_then(|d| {
                                d.values().find(|d| {
                                    d.get("workspace_id").is_some() && d["activity_id"] == owned
                                })
                            });
                            let mut doc=existing.cloned().unwrap_or_else(||json!({"protocol":"agentos.presentation/1","workspace_id":format!("desktop-{owned}"),"activity_id":owned,"revision":0,"outputs":{},"constraints":[],"focus":null}));
                            let expected = existing
                                .map(|d| d["revision"].clone())
                                .unwrap_or(Value::Null);
                            if doc["outputs"].get("nested-primary").is_none() {
                                doc["outputs"]["nested-primary"] =
                                    json!({"tiles":null,"floating":[],"maximized":null});
                            }
                            // New background views do not reshape a manually constrained layout.
                            if doc["constraints"]
                                .as_array()
                                .into_iter()
                                .flatten()
                                .any(|c| c["provenance"] != "inferred_preference")
                            {
                                continue;
                            }
                            let mut tiled = Vec::new();
                            collect_tiles(&doc["outputs"]["nested-primary"]["tiles"], &mut tiled);
                            tiled.extend(surfaces);
                            doc["outputs"]["nested-primary"]["tiles"] =
                                automatic_tiles(&tiled, observed.area.width);
                            counter += 1;
                            put(&socket, &doc, expected, &format!("host-{prefix}-{counter}"))?;
                        }
                        state = call(&socket, &json!({"op":"presentation.snapshot"}))?;
                        let mut next = Scene {
                            identities,
                            ..Scene::default()
                        };
                        next.workspaces = json!(state["documents"]
                            .as_object()
                            .into_iter()
                            .flat_map(|d| d.iter())
                            .filter(|(_, d)| d.get("workspace_id").is_some())
                            .map(|(id, d)| (id.clone(), d.clone()))
                            .collect::<BTreeMap<_, _>>());
                        let reverse = next
                            .identities
                            .iter()
                            .map(|(runtime, surface)| (surface.clone(), runtime.clone()))
                            .collect::<BTreeMap<_, _>>();
                        let mut floating = BTreeSet::new();
                        for doc in next
                            .workspaces
                            .as_object()
                            .into_iter()
                            .flat_map(|d| d.values())
                        {
                            if doc["activity_id"] != activity {
                                continue;
                            }
                            if let Some(layout) = doc["outputs"].get("nested-primary") {
                                if let Some(runtime) =
                                    layout["maximized"].as_str().and_then(|id| reverse.get(id))
                                {
                                    next.maximized.insert(runtime.clone());
                                }
                                for entry in layout["floating"].as_array().into_iter().flatten() {
                                    if let Some(runtime) =
                                        entry["surface_id"].as_str().and_then(|id| reverse.get(id))
                                    {
                                        floating.insert(runtime.clone());
                                    }
                                }
                                for (surface, rect) in rectangles(layout, observed.area)? {
                                    if let Some(runtime) = reverse.get(&surface) {
                                        next.rectangles.insert(runtime.clone(), rect);
                                    }
                                }
                            }
                            if let Some(surface) = doc["focus"]["surface_id"].as_str() {
                                next.focus = reverse.get(surface).cloned();
                            }
                        }
                        next.error = input_error
                            .as_ref()
                            .filter(|(_, when)| when.elapsed() < Duration::from_secs(10))
                            .map(|(message, _)| message.clone());
                        next.visible = next.rectangles.keys().cloned().collect();
                        next.overview = crate::pressure::project(
                            &mut next.rectangles,
                            &observed.windows,
                            &floating,
                            next.focus.as_ref(),
                            observed.area,
                        );
                        Ok(next)
                    })();
                    match result {
                        Ok(next) => *output.lock().unwrap() = next,
                        Err(e) => output.lock().unwrap().error = Some(e),
                    }
                }
                thread::sleep(Duration::from_millis(100));
            }
            grabs.stop(&socket);
            // Core availability also checks this process's start identity, including crashes.
        });
        Self {
            observation,
            scene,
            commands,
            stop,
            worker: Some(worker),
            previews,
            last_input,
        }
    }
    pub fn undo_input(&self) {
        let cursor = self.last_input.load(Ordering::Relaxed);
        if cursor <= 0 {
            self.scene.lock().unwrap().error = Some("No desktop arrangement to undo".into());
            return;
        }
        let stamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        let (reply, _) = mpsc::sync_channel(1);
        if self.commands.try_send(Request {value:json!({"op":"workspace.undo","event_cursor":cursor,"request_id":format!("keyboard-undo-{}-{stamp}",std::process::id())}),reply}).is_err() {
            self.scene.lock().unwrap().error=Some("Workspace input queue busy".into());
        }
    }
    pub fn begin_grab(&self, runtime: &str, rect: Rect) {
        self.previews.lock().unwrap().insert(
            runtime.into(),
            grabs::Preview {
                rect,
                active: false,
            },
        );
        self.grab_command(runtime, "begin");
    }
    pub fn preview_grab(&self, runtime: &str, rect: Rect) {
        if let Some(preview) = self.previews.lock().unwrap().get_mut(runtime) {
            preview.rect = rect;
        }
    }
    pub fn finish_grab(&self, runtime: &str) {
        self.grab_command(runtime, "finish")
    }
    pub fn cancel_grab(&self, runtime: &str) {
        self.grab_command(runtime, "cancel")
    }
    fn grab_command(&self, runtime: &str, operation: &str) {
        let (reply, _) = mpsc::sync_channel(1);
        if self
            .commands
            .try_send(Request {
                value: json!({"op":format!("workspace.grab.{operation}"),"runtime":runtime}),
                reply,
            })
            .is_err()
        {
            self.previews.lock().unwrap().remove(runtime);
            self.scene.lock().unwrap().error = Some("Pointer interaction queue busy".into());
        }
    }
    pub fn input(&self, runtime: &str, mut edit: Value) {
        let scene = self.scene.lock().unwrap().clone();
        let Some(surface) = scene.identities.get(runtime) else {
            return;
        };
        let Some(document) = scene
            .workspaces
            .as_object()
            .into_iter()
            .flat_map(|d| d.values())
            .find(|d| placed_surfaces(&json!({"documents":{"workspace":d}})).contains(surface))
        else {
            return;
        };
        edit["surface_id"] = json!(surface);
        let Some(id) = document["workspace_id"].as_str() else {
            return;
        };
        let stamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        let transaction = json!({"op":"presentation.apply","protocol":"agentos.presentation/1","catalog_revision":"native-core/1","request_id":format!("input-{}-{stamp}",std::process::id()),"expected_revisions":{id:document["revision"]},"operations":[{"op":"workspace.edit","workspace_id":id,"edit":edit}]});
        let (reply, _) = mpsc::sync_channel(1);
        if self
            .commands
            .try_send(Request {
                value: json!({"op":"workspace.transaction","transaction":transaction}),
                reply,
            })
            .is_err()
        {
            self.scene.lock().unwrap().error =
                Some("Workspace input queue busy; refresh before retrying".into());
        }
    }
    pub fn observe(&self, windows: Vec<Observed>, area: Rect) {
        *self.observation.lock().unwrap() = Some(Observation {
            windows: windows.into_iter().take(1024).collect(),
            area,
        });
    }
}
impl Drop for Bridge {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }
}
fn call(socket: &PathBuf, value: &Value) -> Result<Value, String> {
    let mut conn = UnixStream::connect(socket).map_err(|e| e.to_string())?;
    conn.set_read_timeout(Some(Duration::from_millis(200)))
        .map_err(|e| e.to_string())?;
    conn.set_write_timeout(Some(Duration::from_millis(200)))
        .map_err(|e| e.to_string())?;
    writeln!(conn, "{value}").map_err(|e| e.to_string())?;
    let mut line = String::new();
    BufReader::new(conn)
        .take(4 * 1024 * 1024 + 1)
        .read_line(&mut line)
        .map_err(|e| e.to_string())?;
    if line.len() > 4 * 1024 * 1024 || !line.ends_with('\n') {
        return Err("Invalid core response".into());
    }
    let response: Value = serde_json::from_str(&line).map_err(|e| e.to_string())?;
    if response["ok"] != true {
        return Err(response["error"]
            .as_str()
            .unwrap_or("Core operation failed")
            .into());
    }
    Ok(response["result"].clone())
}
fn put(
    socket: &PathBuf,
    document: &Value,
    expected: Value,
    request: &str,
) -> Result<Value, String> {
    if request.is_empty() {
        return Err("Idempotency request ID required".into());
    }
    let id = document["workspace_id"]
        .as_str()
        .ok_or("Workspace required")?;
    call(
        socket,
        &json!({"op":"presentation.apply","protocol":"agentos.presentation/1","catalog_revision":"native-core/1","request_id":request,"expected_revisions":{id:expected},"operations":[{"op":"workspace.put","document":document}]}),
    )
}
pub fn native_identity(window: &Observed, state: &Value) -> Option<String> {
    let surface = window.app_id.strip_prefix("agentos.surface.")?;
    let owner = &state["renderers"][surface];
    if owner["uid"].as_u64() != Some(window.uid as u64)
        || owner["session"].as_str() != Some(window.session.as_str())
        || state["documents"][surface]["surface_id"].as_str() != Some(surface)
    {
        return None;
    }
    Some(surface.into())
}
fn placed_surfaces(state: &Value) -> BTreeSet<String> {
    fn walk(v: &Value, set: &mut BTreeSet<String>) {
        match v {
            Value::Object(m) => {
                if let Some(id) = m.get("surface_id").and_then(Value::as_str) {
                    set.insert(id.into());
                }
                for v in m.values() {
                    walk(v, set)
                }
            }
            Value::Array(a) => {
                for v in a {
                    walk(v, set)
                }
            }
            _ => {}
        }
    }
    let mut result = BTreeSet::new();
    for d in state["documents"]
        .as_object()
        .into_iter()
        .flat_map(|d| d.values())
        .filter(|d| d.get("workspace_id").is_some())
    {
        walk(&d["outputs"], &mut result);
    }
    result
}
fn collect_tiles(tile: &Value, ids: &mut Vec<String>) {
    if tile["kind"] == "leaf" {
        if let Some(id) = tile["surface_id"].as_str() {
            ids.push(id.into());
        }
    } else {
        for child in tile["children"].as_array().into_iter().flatten() {
            collect_tiles(child, ids);
        }
    }
}
fn automatic_tiles(ids: &[String], width: i32) -> Value {
    fn split(axis: &str, children: Vec<Value>) -> Value {
        if children.is_empty() {
            Value::Null
        } else if children.len() == 1 {
            children.into_iter().next().unwrap()
        } else {
            json!({"kind":"split","axis":axis,"ratios":vec![1.0/children.len() as f64;children.len()],"children":children})
        }
    }
    let columns = ids.len().min((width / 320).max(1) as usize).max(1);
    let rows = ids
        .chunks(columns)
        .map(|row| {
            split(
                "horizontal",
                row.iter()
                    .map(|id| json!({"kind":"leaf","surface_id":id}))
                    .collect(),
            )
        })
        .collect();
    split("vertical", rows)
}
pub fn rectangles(layout: &Value, area: Rect) -> Result<BTreeMap<String, Rect>, String> {
    fn tiles(
        v: &Value,
        area: Rect,
        out: &mut BTreeMap<String, Rect>,
        depth: usize,
    ) -> Result<(), String> {
        if v.is_null() {
            return Ok(());
        }
        if depth > 32 {
            return Err("Tile tree too deep".into());
        }
        if v["kind"] == "leaf" {
            let id = v["surface_id"].as_str().ok_or("Missing tile identity")?;
            out.insert(id.into(), area);
            return Ok(());
        }
        let children = v["children"].as_array().ok_or("Invalid tile children")?;
        let ratios = v["ratios"].as_array().ok_or("Invalid split ratios")?;
        if ratios.len() != children.len() {
            return Err("Invalid split ratios".into());
        }
        let horizontal = v["axis"] == "horizontal";
        let extent = if horizontal { area.width } else { area.height };
        let mut fraction = 0.0;
        let mut start = 0;
        for (i, (child, ratio)) in children.iter().zip(ratios).enumerate() {
            fraction += ratio
                .as_f64()
                .filter(|v| v.is_finite() && *v > 0.0)
                .ok_or("Invalid ratio")?;
            let end = if i + 1 == children.len() {
                extent
            } else {
                (fraction * extent as f64).round() as i32
            };
            let rect = if horizontal {
                Rect {
                    x: area.x + start,
                    width: end - start,
                    ..area
                }
            } else {
                Rect {
                    y: area.y + start,
                    height: end - start,
                    ..area
                }
            };
            tiles(child, rect, out, depth + 1)?;
            start = end;
        }
        Ok(())
    }
    let mut out = BTreeMap::new();
    tiles(&layout["tiles"], area, &mut out, 0)?;
    for f in layout["floating"].as_array().into_iter().flatten() {
        let id = f["surface_id"]
            .as_str()
            .ok_or("Missing floating identity")?;
        out.insert(
            id.into(),
            Rect {
                x: area.x + f["x"].as_f64().ok_or("Invalid x")?.round() as i32,
                y: area.y + f["y"].as_f64().ok_or("Invalid y")?.round() as i32,
                width: f["width"].as_f64().ok_or("Invalid width")?.round() as i32,
                height: f["height"].as_f64().ok_or("Invalid height")?.round() as i32,
            },
        );
    }
    if let Some(id) = layout["maximized"].as_str() {
        out.insert(id.into(), area);
    }
    Ok(out)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn automatic_views_use_balanced_rows_instead_of_repeatedly_halving_old_views() {
        let ids = (0..7).map(|i| format!("view-{i}")).collect::<Vec<_>>();
        let layout = json!({"tiles":automatic_tiles(&ids,1280),"floating":[],"maximized":null});
        let area = Rect {
            x: 0,
            y: 0,
            width: 1280,
            height: 800,
        };
        let rects = rectangles(&layout, area).unwrap();
        assert_eq!(rects.len(), 7);
        assert!(rects.values().all(|r| r.width >= 320 && r.height >= 400));
    }
    #[test]
    fn app_id_alone_cannot_impersonate_native_surface() {
        let mut state = json!({"documents":{"a":{"surface_id":"a"}},"renderers":{"a":{"uid":1000,"session":"7:42"}}});
        let mut w = Observed {
            id: "window".into(),
            title: "".into(),
            app_id: "agentos.surface.a".into(),
            uid: 1000,
            session: "8:42".into(),
            min_width: 80,
            min_height: 32,
        };
        assert!(native_identity(&w, &state).is_none());
        w.session = "7:42".into();
        assert_eq!(native_identity(&w, &state), Some("a".into()));
        w.uid = 1001;
        assert!(native_identity(&w, &state).is_none());
        w.uid = 1000;
        state["documents"] = json!({});
        assert!(native_identity(&w, &state).is_none());
    }
    #[test]
    fn split_rounding_covers_odd_dimensions_and_maximize_preserves_base() {
        let layout = json!({"tiles":{"kind":"split","axis":"horizontal","ratios":[0.333333,0.666667],"children":[{"kind":"leaf","surface_id":"a"},{"kind":"leaf","surface_id":"b"}]},"floating":[],"maximized":null});
        let area = Rect {
            x: 3,
            y: 5,
            width: 1001,
            height: 701,
        };
        let result = rectangles(&layout, area).unwrap();
        assert_eq!(result["a"].width + result["b"].width, 1001);
        assert_eq!(result["b"].x, result["a"].x + result["a"].width);
        let mut max = layout.clone();
        max["maximized"] = json!("a");
        assert_eq!(rectangles(&max, area).unwrap()["a"], area);
        assert_eq!(rectangles(&layout, area).unwrap(), result);
    }
}
