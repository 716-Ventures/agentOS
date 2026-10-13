//! Core-owned workspaces. IPC and document reconciliation never run on the render thread.
use crate::{control::Request, policy::Rect};
use serde_json::{json, Value};
use std::{
    collections::{BTreeMap, BTreeSet},
    io::Read,
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
#[path = "../../native-shell/src/presentation_pages.rs"]
mod pages;
#[path = "../../native-shell/src/state_pages.rs"]
mod runtime_pages;
#[derive(Clone, Debug, PartialEq)]
pub struct Observed {
    pub id: String,
    pub title: String,
    pub app_id: String,
    pub uid: u32,
    pub session: String,
    pub system_control: bool,
    pub min_width: i32,
    pub min_height: i32,
}
#[derive(Clone, Default)]
pub struct Scene {
    pub rectangles: BTreeMap<String, Rect>,
    pub output_areas: BTreeMap<String, Rect>,
    pub surface_outputs: BTreeMap<String, String>,
    pub identities: BTreeMap<String, String>,
    pub workspaces: Value,
    pub focus: Option<String>,
    pub maximized: BTreeSet<String>,
    pub error: Option<String>,
    pub overview: Value,
    pub visible: BTreeSet<String>,
}
/// Immutable published scenes keep workspace history off the render thread's
/// copy path. Readers retain one consistent revision while the worker publishes
/// its successor; only explicit diagnostic errors use copy-on-write.
#[derive(Clone, Default)]
pub struct SceneStore(Arc<Mutex<Arc<Scene>>>);
impl SceneStore {
    pub fn snapshot(&self) -> Arc<Scene> {
        self.0.lock().unwrap().clone()
    }
    fn publish(&self, scene: Scene) {
        let next=Arc::new(scene);
        let retired=std::mem::replace(&mut *self.0.lock().unwrap(),next);
        // Destruction of a large old history must not hold up a snapshot reader.
        drop(retired);
    }
    fn set_error(&self, error: String) {
        Arc::make_mut(&mut *self.0.lock().unwrap()).error=Some(error);
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct OutputObservation {
    pub id: String,
    pub area: Rect,
    pub metadata: Value,
}
#[derive(Clone, PartialEq)]
struct Observation {
    windows: Vec<Observed>,
    outputs: Vec<OutputObservation>,
}
fn project_outputs(
    rectangles: &mut BTreeMap<String, Rect>,
    assignments: &BTreeMap<String, String>,
    windows: &[Observed],
    floating: &BTreeSet<String>,
    focus: Option<&String>,
    outputs: &BTreeMap<String, Rect>,
    primary: &str,
    recovered: &BTreeSet<String>,
    recovery_destinations: &BTreeSet<String>,
    recovery_surfaces: &BTreeSet<String>,
) -> Value {
    let mut overviews = serde_json::Map::new();
    for (id, area) in outputs {
        let mut subset = rectangles
            .iter()
            .filter(|(runtime, _)| assignments.get(*runtime).map(String::as_str) == Some(id))
            .map(|(id, r)| (id.clone(), *r))
            .collect::<BTreeMap<_, _>>();
        let recovering = recovery_destinations.contains(id);
        // Recover original floating work into the reachable overview, but keep
        // newly opened floating controls above it so restoration is usable.
        let recovery_floating = floating.difference(recovery_surfaces).cloned().collect();
        let original_ids = subset.keys().cloned().collect::<Vec<_>>();
        let overview = crate::pressure::project_recovery(
            &mut subset,
            windows,
            if recovering { &recovery_floating } else { floating },
            focus,
            *area,
            recovering,
        );
        for id in original_ids {
            rectangles.remove(&id);
        }
        rectangles.extend(subset);
        if !overview.is_null() {
            overviews.insert(id.clone(), overview);
        }
    }
    // Preserve the existing single-output overview shape for current native hosts.
    if outputs.len() == 1 {
        let mut result = overviews.remove(primary).unwrap_or(Value::Null);
        if !recovered.is_empty() {
            result["recovered_outputs"] = json!(recovered);
        }
        result
    } else if overviews.is_empty() {
        Value::Null
    } else {
        json!({"outputs":overviews,"recovered_outputs":recovered})
    }
}
pub struct Bridge {
    observation: Arc<Mutex<Option<Observation>>>,
    pub scene: SceneStore,
    pub commands: SyncSender<Request>,
    stop: Arc<AtomicBool>,
    last_input: Arc<AtomicI64>,
    worker: Option<thread::JoinHandle<()>>,
    pub previews: Arc<Mutex<BTreeMap<String, grabs::Preview>>>,
}
impl Bridge {
    pub fn start(socket: PathBuf) -> Self {
        let observation = Arc::new(Mutex::new(None::<Observation>));
        let scene = SceneStore::default();
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
            let mut output_areas = BTreeMap::<String, OutputObservation>::new();
            let mut projected: Option<(Arc<Value>,Observation,Option<String>)> = None;
            let mut document_cache = pages::Cache::live();
            let mut runtime_cache = runtime_pages::Cache::default();
            let mut recovery = crate::output_recovery::Recovery::default();
            let mut selected_activity = None::<String>;
            // A switch can precede restoration in this batch, before Recovery
            // observes the new activity. Reject that stale control immediately.
            let mut activity_pending = false;
            let mut first_seen = BTreeMap::<String, std::time::Instant>::new();
            let mut nonce = [0u8; 16];
            if std::fs::File::open("/dev/urandom")
                .and_then(|mut f| f.read_exact(&mut nonce))
                .is_err()
            {
                return;
            }
            let prefix = nonce.iter().map(|b| format!("{b:02x}")).collect::<String>();
            let mut ready=None;
            while !stopping.load(Ordering::Relaxed) {
                // Bounded command queue; each operation has exact core revision checks.
                for req in ready.take().into_iter().chain(rx.try_iter()).take(8) {
                    if req.expired() {
                        continue;
                    }
                    let scene = output.snapshot();
                    let result = if let Some(result) = grabs.handle(&socket, &scene, &req.value) {
                        result
                    } else {
                        match req.value["op"].as_str() {
                            Some("workspace.restore_outputs") => {
                                let available=input.lock().unwrap().as_ref().map(|observed|observed.outputs.iter().map(|o|o.id.clone()).collect::<BTreeSet<_>>()).unwrap_or_default();
                                if !recovery.context_matches(&available,if activity_pending {selected_activity.as_deref()} else {None}) {Err("Outputs or activity changed; review the current restoration offer".into())}
                                else {recovery.restore(&req.value["recovery"]).map_err(String::from)}
                            }
                            Some("workspace.transaction") => {
                                if let Some(baseline) = req.value.get("input_baseline") {
                                    call(&socket, &json!({"op":"presentation.get","document_id":baseline["workspace_id"]}))
                                        .and_then(|current| call(&socket, &crate::input_revision::refresh(req.value["transaction"].clone(), baseline, &current)))
                                } else {
                                    call(&socket, &req.value["transaction"])
                                }
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
                                    activity_pending = true;
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
                        output.set_error(e.clone());
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
                    let result = (|| -> Result<Option<Scene>, String> {
                        let _timing=crate::timings::Span::new("bridge.reconcile");
                        let mut state = {let _read=crate::timings::Span::new("bridge.metadata");document_cache.read(
                            |value| call(&socket, value),
                            None,
                            || stopping.load(Ordering::Relaxed),
                        )?};
                        if input_error.is_none() && output.snapshot().error.is_none() && observed.windows.iter().all(|window|output.snapshot().identities.contains_key(&window.id)) && projected.as_ref().is_some_and(|(prior,observation,activity)|Arc::ptr_eq(prior,&state) && observation==&observed && activity==&selected_activity) {
                            return Ok(None);
                        }
                        let current_outputs = observed
                            .outputs
                            .iter()
                            .map(|o| (o.id.clone(), o.clone()))
                            .collect::<BTreeMap<_, _>>();
                        for id in output_areas
                            .keys()
                            .filter(|id| !current_outputs.contains_key(*id))
                        {
                            call(&socket, &json!({"op":"outputs.disconnect","output_id":id}))?;
                        }
                        for (id, head) in &current_outputs {
                            if output_areas.get(id) != Some(head) {
                                call(
                                    &socket,
                                    &json!({"op":"outputs.register","output_id":id,"width":head.area.width,"height":head.area.height,"x":head.area.x,"y":head.area.y,"scale":head.metadata["scale"],"transform":head.metadata["transform"]}),
                                )?;
                            }
                        }
                        output_areas = current_outputs;
                        let primary = observed.outputs.first().ok_or("No connected outputs")?;
                        let primary_id = primary.id.as_str();
                        let primary_area = primary.area;
                        let activities = runtime_cache.read(|query| call(&socket,query), None, || stopping.load(Ordering::Relaxed))?;
                        let available = activities["activities"]
                            .as_array()
                            .ok_or("No active activity")?;
                        let activity = selected_activity
                            .as_ref()
                            .filter(|id| available.iter().any(|a| a["id"].to_string() == **id))
                            .cloned()
                            .or_else(|| available.first().map(|a| a["id"].to_string()))
                            .ok_or("No active activity")?;
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
                        let _placement=crate::timings::Span::new("bridge.placement_and_projection");
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
                                if !system_floating(w) && seen.elapsed() < Duration::from_millis(300) {
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
                                let mut observation = json!({"op":"host.surface","surface_id":entry.0,"activity_id":entry.1,"title":entry.2,"app_id":entry.3,"connected":true});
                                if !w.session.is_empty() && w.uid != u32::MAX {
                                    observation["client_uid"] = json!(w.uid);
                                    observation["client_session"] = json!(w.session);
                                }
                                let receipt = call(&socket, &observation)?;
                                entry.0 = receipt["surface_id"]
                                    .as_str()
                                    .ok_or("Invalid host identity receipt")?
                                    .to_string();
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
                        let mut placement_error = None;
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
                            if doc["outputs"].get(primary_id).is_none() {
                                doc["outputs"][primary_id] =
                                    json!({"tiles":null,"floating":[],"maximized":null});
                            }
                            let (controls, surfaces): (Vec<_>, Vec<_>) = surfaces.into_iter().partition(|surface| {
                                observed.windows.iter().any(|window| system_floating(window) && identities.get(&window.id)==Some(surface))
                            });
                            place_new_views(&mut doc, primary_id, primary_area, surfaces);
                            for surface in controls {
                                if let Some(size)=observed.windows.iter().find(|window|identities.get(&window.id)==Some(&surface)).and_then(control_size) {
                                    place_control(&mut doc,primary_id,primary_area,surface,size);
                                }
                            }
                            counter += 1;
                            if let Err(error) =
                                put(&socket, &doc, expected, &format!("host-{prefix}-{counter}"))
                            {
                                // Automatic placement may conflict with an active draft.
                                // Keep projecting fresh committed state (including human
                                // focus) instead of freezing the whole prior scene.
                                placement_error = Some(error);
                            }
                        }
                        state = document_cache.read(
                            |value| call(&socket, value),
                            None,
                            || stopping.load(Ordering::Relaxed),
                        )?;
                        let mut next = Scene {
                            identities,
                            output_areas: observed
                                .outputs
                                .iter()
                                .map(|o| (o.id.clone(), o.area))
                                .collect(),
                            ..Scene::default()
                        };
                        // Input routing needs the selected activity and other
                        // activities with mapped clients, not all retained history.
                        let mut relevant=BTreeSet::from([activity.clone()]);
                        for surface in next.identities.values() {
                            if let Some(owner)=state["documents"][surface]["activity_id"].as_str() {relevant.insert(owner.into());}
                        }
                        for (runtime,(_,owner,_,_)) in &registrations {
                            if next.identities.contains_key(runtime) {relevant.insert(owner.clone());}
                        }
                        next.workspaces=live_workspaces(&state,&relevant);
                        let reverse = next
                            .identities
                            .iter()
                            .map(|(runtime, surface)| (surface.clone(), runtime.clone()))
                            .collect::<BTreeMap<_, _>>();
                        let mut floating = BTreeSet::new();
                        let available_outputs=next.output_areas.keys().cloned().collect();
                        recovery.observe(&activity,&next.workspaces,&available_outputs,primary_id);
                        activity_pending = false;
                        let recovered_outputs=recovery.recovered_outputs();
                        for doc in next
                            .workspaces
                            .as_object()
                            .into_iter()
                            .flat_map(|d| d.values())
                        {
                            if doc["activity_id"] != activity {
                                continue;
                            }
                            for (id, layout) in doc["outputs"].as_object().into_iter().flatten() {
                                let workspace=doc["workspace_id"].as_str().ok_or("Workspace identity missing")?;
                                let routed=recovery.destination(workspace,id).unwrap_or(id);
                                let actual = output_areas.get(routed);
                                let area = actual.map(|o| o.area).unwrap_or(primary_area);
                                let destination=actual.map(|o|o.id.as_str()).unwrap_or(primary_id);
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
                                for (surface, rect) in rectangles(layout, area)? {
                                    if let Some(runtime) = reverse.get(&surface) {
                                        next.rectangles.insert(runtime.clone(), rect);
                                        next.surface_outputs
                                            .insert(runtime.clone(), destination.to_owned());
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
                            .map(|(message, _)| message.clone())
                            .or(placement_error);
                        next.visible = next.rectangles.keys().cloned().collect();
                        next.overview = project_outputs(
                            &mut next.rectangles,
                            &next.surface_outputs,
                            &observed.windows,
                            &floating,
                            next.focus.as_ref(),
                            &next.output_areas,
                            primary_id,
                            &recovered_outputs,
                            &recovery.destinations(),
                            &recovery.surfaces().iter().filter_map(|id| reverse.get(id).cloned()).collect(),
                        );
                        if let Some(offer)=recovery.offer() {
                            if next.overview.is_null() {next.overview=json!({});}
                            next.overview["restoration"]=offer;
                            next.overview["reason"]=json!("A preferred display is available. Work stays here until you restore preferred placement in Agent Monitor.");
                        }
                        projected=Some((state,observed.clone(),selected_activity.clone()));
                        Ok(Some(next))
                    })();
                    match result {
                        Ok(Some(next)) => output.publish(next),
                        Ok(None) => {},
                        Err(e) => output.set_error(e),
                    }
                }
                // Incoming human commands wake the worker immediately; only
                // idle state reconciliation uses the polling interval.
                ready=rx.recv_timeout(Duration::from_millis(100)).ok();
            }
            grabs.stop(&socket);
            for id in output_areas.keys() {
                let _ = call(&socket, &json!({"op":"outputs.disconnect","output_id":id}));
            }
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
            self.scene.set_error("No desktop arrangement to undo".into());
            return;
        }
        let stamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        let (reply, _) = mpsc::sync_channel(1);
        if self.commands.try_send(Request {peer_pid:None,value:json!({"op":"workspace.undo","event_cursor":cursor,"request_id":format!("keyboard-undo-{}-{stamp}",std::process::id())}),reply,deadline:None}).is_err() {
            self.scene.set_error("Workspace input queue busy".into());
        }
    }
    pub fn begin_grab(&self, runtime: &str, rect: Rect) {
        self.previews.lock().unwrap().insert(
            runtime.into(),
            grabs::Preview {
                rect,
                // A serial-validated human drag previews locally immediately.
                // The worker still acquires a lease before any durable edit;
                // denial removes this preview and restores the committed scene.
                active: true,
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
                peer_pid:None,
                value: json!({"op":format!("workspace.grab.{operation}"),"runtime":runtime}),
                reply,
                deadline: None,
            })
            .is_err()
        {
            self.previews.lock().unwrap().remove(runtime);
            self.scene.set_error("Pointer interaction queue busy".into());
        }
    }
    pub fn input(&self, runtime: &str, mut edit: Value) {
        let scene = self.scene.snapshot();
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
        if edit["kind"] == "float" {
            if let Err(error) = localize_edit(&scene, &mut edit) {
                self.scene.set_error(error);
                return;
            }
        }
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
                peer_pid:None,
                value: json!({"op":"workspace.transaction","transaction":transaction,"input_baseline":document}),
                reply,
                deadline: None,
            })
            .is_err()
        {
            self.scene.set_error("Workspace input queue busy; refresh before retrying".into());
        }
    }
    pub fn observe(&self, windows: Vec<Observed>, outputs: Vec<OutputObservation>) {
        *self.observation.lock().unwrap() = Some(Observation {
            windows: windows.into_iter().take(1024).collect(),
            outputs: outputs.into_iter().take(64).collect(),
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
    let _timing=crate::timings::Span::new("bridge.core_roundtrip");
    let conn = UnixStream::connect(socket).map_err(|e| e.to_string())?;
    let line = crate::core_ipc::exchange(conn, format!("{value}\n").as_bytes())?;
    let response: Value = serde_json::from_slice(&line).map_err(|e| e.to_string())?;
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
fn live_workspaces(state:&Value, activities:&BTreeSet<String>)->Value {
    json!(state["documents"].as_object().into_iter().flat_map(|d|d.iter())
        .filter(|(_,d)|d.get("workspace_id").is_some() && d["activity_id"].as_str().is_some_and(|a|activities.contains(a)))
        .map(|(id,d)|(id.clone(),d.clone())).collect::<BTreeMap<_,_>>())
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
// Preserve every existing placement when a human has constrained the workspace.
// New windows still need durable geometry so they can be focused and managed.
fn system_monitor(window: &Observed) -> bool {window.system_control && window.app_id=="agentos.monitor"}
fn system_floating(window: &Observed) -> bool {control_size(window).is_some()}

pub fn control_size(window: &Observed) -> Option<(i32,i32)> {
    if system_monitor(window) {return Some((920,680));}
    if !window.system_control {return None;}
    if window.app_id.starts_with("agentos.local-terminal."){return Some((880,560));}
    match window.app_id.as_str() {
        "agentos.welcome" => Some((560,320)),
        "agentos.settings" => Some((760,540)),
        _ => None,
    }
}

pub fn initial_control_geometry(window: &Observed, area: Rect) -> Option<Rect> {
    let (width,height)=control_size(window)?;
    let width=width.min(area.width).max(1);let height=height.min(area.height).max(1);
    Some(Rect{x:area.x+(area.width-width)/2,y:area.y+(area.height-height)/2,width,height})
}

/// A host-authenticated monitor opens over existing work. This preference is
/// applied once; subsequent human placement and saved workspace state win.
fn place_control(doc:&mut Value,output:&str,area:Rect,surface:String,size:(i32,i32)) {
        let width=area.width.min(size.0).max(1); let height=area.height.min(size.1).max(1);
        doc["outputs"][output]["floating"].as_array_mut().unwrap().push(json!({
            "surface_id":surface,"x":(area.width-width)/2,"y":(area.height-height)/2,"width":width,"height":height
        }));
}
fn place_new_views(doc: &mut Value, output: &str, area: Rect, surfaces: Vec<String>) {
    let constrained = doc["constraints"]
        .as_array()
        .into_iter()
        .flatten()
        .any(|c| c["provenance"] != "inferred_preference");
    if constrained {
        let width = area.width.min(720).max(1);
        let height = area.height.min(600).max(1);
        for surface in surfaces {
            doc["outputs"][output]["floating"]
                .as_array_mut()
                .unwrap()
                .push(json!({
                    "surface_id":surface,"x":(area.width-width)/2,
                    "y":(area.height-height)/2,"width":width,"height":height
                }));
        }
    } else {
        let mut tiled = Vec::new();
        collect_tiles(&doc["outputs"][output]["tiles"], &mut tiled);
        tiled.extend(surfaces);
        doc["outputs"][output]["tiles"] = automatic_tiles(&tiled, area.width);
    }
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
    fn multi_output_pressure_is_local_and_hidden_views_leave_the_scene() {
        let left = Rect {
            x: -800,
            y: 0,
            width: 800,
            height: 600,
        };
        let right = Rect {
            x: 0,
            y: 0,
            width: 800,
            height: 600,
        };
        let outputs = BTreeMap::from([("left".into(), left), ("right".into(), right)]);
        let assignments = BTreeMap::from([
            ("a".into(), "left".into()),
            ("b".into(), "right".into()),
            ("c".into(), "right".into()),
        ]);
        let windows = [("a", 80), ("b", 900), ("c", 80)]
            .into_iter()
            .map(|(id, width)| Observed {
                id: id.into(),
                title: id.into(),
                app_id: "fixture".into(),
                uid: 1000,
                session: "1:1".into(),
                system_control: false,
                min_width: width,
                min_height: 32,
            })
            .collect::<Vec<_>>();
        let mut rectangles = BTreeMap::from([
            ("a".into(), left),
            (
                "b".into(),
                Rect {
                    width: 400,
                    ..right
                },
            ),
            (
                "c".into(),
                Rect {
                    x: 400,
                    width: 400,
                    ..right
                },
            ),
        ]);
        let overview = project_outputs(
            &mut rectangles,
            &assignments,
            &windows,
            &BTreeSet::new(),
            Some(&"b".into()),
            &outputs,
            "left",
            &BTreeSet::new(),
            &BTreeSet::new(),
            &BTreeSet::new(),
        );
        assert_eq!(
            rectangles["a"], left,
            "A healthy separate output must not be projected into the pressured output"
        );
        assert_eq!(rectangles["b"].x, 0);
        assert_eq!(rectangles["b"].width, 900);
        assert!(
            !rectangles.contains_key("c"),
            "Hidden overview views must be removed from visible geometry"
        );
        assert!(overview["outputs"].get("left").is_none());
        assert_eq!(overview["outputs"]["right"]["selected"], "b");
    }
    #[test]
    fn healthy_multiple_outputs_preserve_their_coordinates() {
        let left = Rect {
            x: -800,
            y: 0,
            width: 800,
            height: 600,
        };
        let right = Rect {
            x: 0,
            y: 0,
            width: 1000,
            height: 700,
        };
        let outputs = BTreeMap::from([("left".into(), left), ("right".into(), right)]);
        let assignments =
            BTreeMap::from([("a".into(), "left".into()), ("b".into(), "right".into())]);
        let windows = ["a", "b"]
            .into_iter()
            .map(|id| Observed {
                id: id.into(),
                title: id.into(),
                app_id: "fixture".into(),
                uid: 1000,
                session: "1:1".into(),
                system_control: false,
            min_width: 80,
                min_height: 32,
            })
            .collect::<Vec<_>>();
        let mut rectangles = BTreeMap::from([("a".into(), left), ("b".into(), right)]);
        let saved = rectangles.clone();
        assert!(project_outputs(
            &mut rectangles,
            &assignments,
            &windows,
            &BTreeSet::new(),
            None,
            &outputs,
            "left",
            &BTreeSet::new(),
            &BTreeSet::new(),
            &BTreeSet::new()
        )
        .is_null());
        assert_eq!(rectangles, saved);
    }
    #[test]
    fn input_routing_retains_live_background_activities_without_copying_retired_history() {
        let state=json!({"documents":{"old":{"workspace_id":"old","activity_id":"1"},"active":{"workspace_id":"active","activity_id":"2"},"background":{"workspace_id":"background","activity_id":"3"},"view":{"surface_id":"view","activity_id":"2"}}});
        let projected=live_workspaces(&state,&BTreeSet::from(["2".into(),"3".into()]));
        assert!(projected.get("active").is_some());assert!(projected.get("background").is_some());
        assert!(projected.get("old").is_none());assert!(projected.get("view").is_none());
        assert!(state["documents"].get("old").is_some(),"Projection must preserve retained core history");
    }
    #[test]
    fn published_scenes_share_history_and_keep_each_readers_revision_consistent() {
        let store=SceneStore::default();
        store.publish(Scene {focus:Some("editor".into()),workspaces:json!({"revision":1,"draft":"retained"}),..Scene::default()});
        let original=store.snapshot();
        assert!(Arc::ptr_eq(&original,&store.snapshot()),"Reading a scene must not copy its workspace history");
        store.publish(Scene {focus:Some("monitor".into()),workspaces:json!({"revision":2,"draft":"retained"}),..Scene::default()});
        let successor=store.snapshot();
        assert!(!Arc::ptr_eq(&original,&successor));
        assert_eq!(original.focus.as_deref(),Some("editor"));
        assert_eq!(original.workspaces["revision"],1);
        assert_eq!(successor.workspaces["revision"],2);
        store.set_error("Queue busy".into());
        assert!(successor.error.is_none(),"Error publication must not mutate an in-flight scene");
        assert_eq!(store.snapshot().error.as_deref(),Some("Queue busy"));
        assert_eq!(store.snapshot().focus.as_deref(),Some("monitor"));
    }
    #[test]
    fn snapshot_cost_does_not_copy_retained_workspace_history() {
        let workspaces=(0..1000).map(|i|(format!("workspace-{i}"),json!({"revision":i,"constraints":"x".repeat(1024)}))).collect::<serde_json::Map<_,_>>();
        let store=SceneStore::default();store.publish(Scene{workspaces:Value::Object(workspaces),..Scene::default()});
        let original=store.snapshot();
        let start=std::time::Instant::now();
        for _ in 0..64 {std::hint::black_box((*original).clone());}
        let old=start.elapsed();let start=std::time::Instant::now();
        for _ in 0..64 {let current=store.snapshot();assert!(Arc::ptr_eq(&original,&current));std::hint::black_box(current);}
        println!("Scene history copy diagnostic: old_64_deep_copies_us={} shared_64_snapshots_us={}",old.as_micros(),start.elapsed().as_micros());
    }
    #[test]
    fn recovery_keeps_new_floating_controls_reachable_above_original_work() {
        let area = Rect { x:1280,y:60,width:1024,height:708 };
        let mut rectangles=BTreeMap::from([
            ("editor".into(),Rect{x:1380,y:180,width:400,height:300}),
            ("monitor".into(),Rect{x:1560,y:160,width:720,height:600}),
        ]);
        let assignments=BTreeMap::from([("editor".into(),"right".into()),("monitor".into(),"right".into())]);
        let floats=BTreeSet::from(["editor".into(),"monitor".into()]);
        let overview=project_outputs(&mut rectangles,&assignments,&[],&floats,Some(&"editor".into()),
            &BTreeMap::from([("right".into(),area)]),"right",&BTreeSet::from(["left".into()]),
            &BTreeSet::from(["right".into()]),&BTreeSet::from(["editor".into()]));
        assert_eq!(rectangles["editor"],area);
        assert_eq!(rectangles["monitor"],Rect{x:1560,y:160,width:720,height:600});
        assert_eq!(overview["selected"],"editor");
    }
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
    fn monitor_floats_without_replacing_work_or_focus() {
        let area=Rect{x:0,y:49,width:1280,height:751};
        let mut doc=json!({"outputs":{"head":{"tiles":{"kind":"leaf","surface_id":"work"},"floating":[],"maximized":null}},"constraints":[],"focus":{"surface_id":"work"}});
        let tiles=doc["outputs"]["head"]["tiles"].clone();
        place_control(&mut doc,"head",area,"monitor".into(),(920,680));
        assert_eq!(doc["outputs"]["head"]["tiles"],tiles);
        assert_eq!(doc["focus"]["surface_id"],"work");
        assert_eq!(doc["outputs"]["head"]["floating"][0]["width"],920);
        assert_eq!(doc["outputs"]["head"]["floating"][0]["height"],680);
        let mut window=Observed{id:"w".into(),title:"Agent Monitor".into(),app_id:"agentos.monitor".into(),uid:1000,session:"test".into(),system_control:false,min_width:80,min_height:32};
        assert!(!system_monitor(&window));window.system_control=true;assert!(system_monitor(&window));
        window.app_id="agentos.settings".into();window.system_control=false;assert!(!system_floating(&window));
        assert!(initial_control_geometry(&window,area).is_none());
        window.system_control=true;assert!(system_floating(&window));
        assert_eq!(initial_control_geometry(&window,area),Some(Rect{x:260,y:154,width:760,height:540}));
        assert_eq!(initial_control_geometry(&window,Rect{x:-800,y:51,width:640,height:400}),Some(Rect{x:-800,y:51,width:640,height:400}));
        window.app_id="agentos.local-terminal.00000000000000000000000000000001".into();window.system_control=false;
        assert!(control_size(&window).is_none());window.system_control=true;assert_eq!(control_size(&window),Some((880,560)));
    }
    #[test]
    fn new_windows_remain_manageable_in_manually_constrained_workspaces() {
        let original =
            json!({"tiles":{"kind":"leaf","surface_id":"old"},"floating":[],"maximized":null});
        let mut doc = json!({"outputs":{"left":original},"constraints":[{"provenance":"direct_manipulation"}],"focus":{"surface_id":"old"}});
        let constraints = doc["constraints"].clone();
        let focus = doc["focus"].clone();
        let area = Rect {
            x: -800,
            y: 40,
            width: 800,
            height: 700,
        };
        place_new_views(&mut doc, "left", area, vec!["monitor".into()]);
        assert_eq!(doc["outputs"]["left"]["tiles"], original["tiles"]);
        assert_eq!(doc["constraints"], constraints);
        assert_eq!(doc["focus"], focus);
        let views = rectangles(&doc["outputs"]["left"], area).unwrap();
        assert_eq!(views["old"], area);
        assert_eq!(
            views["monitor"],
            Rect {
                x: -760,
                y: 90,
                width: 720,
                height: 600
            }
        );
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
            system_control: false,
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

/// Compositor previews and hit tests are global; WorkspaceDocument geometry is
/// local to its output work area. Keep the conversion at the IPC boundary.
fn local_rect(rect: Rect, area: Rect) -> Result<Rect, String> {
    Ok(Rect {
        x: rect
            .x
            .checked_sub(area.x)
            .ok_or("Output coordinate overflow")?,
        y: rect
            .y
            .checked_sub(area.y)
            .ok_or("Output coordinate overflow")?,
        ..rect
    })
}
fn localize_edit(scene: &Scene, edit: &mut Value) -> Result<(), String> {
    let area = scene
        .output_areas
        .get(edit["output_id"].as_str().ok_or("Output required")?)
        .ok_or("Output work area unavailable")?;
    for (key, origin) in [("x", area.x), ("y", area.y)] {
        let coordinate = edit[key]
            .as_i64()
            .ok_or("Integer compositor coordinate required")?;
        edit[key] = json!(coordinate
            .checked_sub(origin as i64)
            .ok_or("Output coordinate overflow")?);
    }
    Ok(())
}
#[cfg(test)]
mod work_area_input_tests {
    use super::*;
    #[test]
    fn global_keyboard_geometry_roundtrips_through_output_local_workspace_coordinates() {
        for (x, y) in [(0, 60), (-1280, 60), (1280, -600)] {
            let area = Rect {
                x,
                y,
                width: 1280,
                height: 740,
            };
            let mut scene = Scene::default();
            scene.output_areas.insert("display".into(), area);
            let mut edit = json!({"kind":"float","output_id":"display","x":x+20,"y":y+30,"width":320,"height":240});
            localize_edit(&scene, &mut edit).unwrap();
            assert_eq!(
                (edit["x"].as_i64(), edit["y"].as_i64()),
                (Some(20), Some(30))
            );
            let layout = json!({"tiles":null,"floating":[{"surface_id":"view","x":edit["x"],"y":edit["y"],"width":320,"height":240}],"maximized":null});
            assert_eq!(
                rectangles(&layout, area).unwrap()["view"],
                Rect {
                    x: x + 20,
                    y: y + 30,
                    width: 320,
                    height: 240
                }
            );
        }
        assert!(localize_edit(
            &Scene::default(),
            &mut json!({"kind":"float","output_id":"removed","x":0,"y":0})
        )
        .is_err());
    }
}
