//! IPC runs on a worker, never on GTK's input/render thread.
use serde_json::{json, Value};
use std::{
    collections::BTreeMap,
    io::{BufRead, BufReader, Write},
    os::unix::net::UnixStream,
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc::{self, Receiver, Sender},
        Arc, Mutex,
    },
    thread,
    time::{Duration, Instant},
};
const LIMIT: usize = 4 * 1024 * 1024;
pub fn request(socket: &PathBuf, value: &Value) -> Result<Value, String> {
    request_timeout(socket, value, Duration::from_millis(500))
}
pub fn request_timeout(
    socket: &PathBuf,
    value: &Value,
    timeout: Duration,
) -> Result<Value, String> {
    let mut conn = UnixStream::connect(socket).map_err(|e| e.to_string())?;
    conn.set_read_timeout(Some(timeout))
        .map_err(|e| e.to_string())?;
    conn.set_write_timeout(Some(timeout))
        .map_err(|e| e.to_string())?;
    let bytes = serde_json::to_vec(value).map_err(|e| e.to_string())?;
    if bytes.len() > LIMIT {
        return Err("Presentation request exceeds its limit".into());
    }
    conn.write_all(&bytes)
        .and_then(|_| conn.write_all(b"\n"))
        .map_err(|e| e.to_string())?;
    let mut line = String::new();
    BufReader::new(conn)
        .take(16 * LIMIT as u64 + 1)
        .read_line(&mut line)
        .map_err(|e| e.to_string())?;
    if line.len() > 16 * LIMIT || !line.ends_with('\n') {
        return Err("Invalid presentation response".into());
    }
    let response: Value = serde_json::from_str(&line).map_err(|e| e.to_string())?;
    if response["ok"] != true {
        return Err(response["error"]
            .as_str()
            .unwrap_or("Presentation request failed")
            .into());
    }
    Ok(response["result"].clone())
}
use std::io::Read;
#[derive(Clone, Debug)]
pub struct Draft {
    pub text: String,
    pub expected: u64,
    pub dirty: bool,
    pub resolved: Option<u64>,
}
#[derive(Clone, Default, Debug)]
pub struct Frame {
    pub documents: BTreeMap<String, Value>,
    pub bindings: BTreeMap<String, Value>,
    pub actions: BTreeMap<String, Value>,
    pub drafts: BTreeMap<(String, String), Value>,
    pub core: Value,
    pub host_surfaces: Value,
    pub outputs: Value,
    pub compositor: Value,
    pub workspace_undo: Option<i64>,
    pub broker: Value,
    pub usage: Value,
    pub activity: Option<String>,
    pub inspection: Option<super::log_view::Page>,
    pub notice: Option<String>,
    pub connected: bool,
    pub error: Option<String>,
}
#[derive(Debug)]
pub enum Command {
    RegisterRenderer(String),
    Approve(Value),
    Resume(Value),
    ReviewInput {
        proposal: Value,
        reply: Sender<Result<Value, String>>,
    },
    Attach(Value),
    OpenTerminal,
    PageOutput(i8),
    FollowOutput(bool),
    FreezeOutput(u64),
    WorkspaceEdit {
        workspace: String,
        revision: u64,
        edit: Value,
    },
    WorkspaceUndo(i64),
    ResolveDraft {
        surface: String,
        element: String,
        commit: bool,
    },
    Preferences(Value),
    Setup,
    SelectActivity(String),
    CreateActivity(String),
    Ask {
        activity: i64,
        prompt: String,
        grounding: Option<Value>,
    },
    Stop {
        source: String,
        job: Value,
    },
    Inspect {
        source: String,
        job: Value,
    },
    Lease {
        surface: String,
        element: String,
        begin: bool,
    },
    Action {
        reference: String,
        key: String,
        surface: String,
        revision: u64,
        action: String,
        parameters: Value,
    },
    Close {
        surface: String,
    },
    Quit,
}
pub struct Backend {
    pub commands: Sender<Command>,
    pub frame: Arc<Mutex<Frame>>,
    pub drafts: Arc<Mutex<BTreeMap<(String, String), Draft>>>,
    worker: Option<thread::JoinHandle<()>>,
    stop: Arc<AtomicBool>,
}
impl Backend {
    pub fn start(socket: PathBuf, activity: Option<String>) -> Self {
        let (commands, rx) = mpsc::channel();
        let frame = Arc::new(Mutex::new(Frame::default()));
        let drafts = Arc::new(Mutex::new(super::draft_cache::load(
            &super::draft_cache::path(),
        )));
        let (view, edits) = (frame.clone(), drafts.clone());
        let stop = Arc::new(AtomicBool::new(false));
        let stopping = stop.clone();
        let worker = thread::spawn(move || run(socket, activity, rx, view, edits, stopping));
        Self {
            commands,
            frame,
            drafts,
            worker: Some(worker),
            stop,
        }
    }
    pub fn close(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        let _ = self.commands.send(Command::Quit);
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
            if let Err(error) = super::draft_cache::encode(&self.drafts.lock().unwrap())
                .and_then(|bytes| super::draft_cache::save(&super::draft_cache::path(), &bytes))
            {
                eprintln!("Draft recovery: {error}");
            }
        }
    }
}
impl Drop for Backend {
    fn drop(&mut self) {
        self.close();
    }
}
fn run(
    socket: PathBuf,
    mut activity: Option<String>,
    rx: Receiver<Command>,
    frame: Arc<Mutex<Frame>>,
    drafts: Arc<Mutex<BTreeMap<(String, String), Draft>>>,
    stop: Arc<AtomicBool>,
) {
    let mut presentation_cache = super::presentation_pages::Cache::default();
    let mut output_view = None::<super::log_view::LogView>;
    let mut leases = BTreeMap::<(String, String), Instant>::new();
    let mut last = Instant::now() - Duration::from_secs(1);
    let mut shown_activity = None::<String>;
    let mut ensured = std::collections::BTreeSet::<i64>::new();
    let mut ensured_sources = std::collections::BTreeSet::<String>::new();
    let mut source_scan = (None::<String>, String::new());
    let mut recovered = drafts.lock().unwrap().keys().cloned().collect::<Vec<_>>();
    let mut saved_cache = Vec::new();
    let approval_pending = Arc::new(AtomicBool::new(false));
    let mut approvals = Vec::<thread::JoinHandle<()>>::new();
    while !stop.load(Ordering::Relaxed) {
        match super::draft_cache::encode(&drafts.lock().unwrap()) {
            Ok(bytes) if bytes != saved_cache => {
                match super::draft_cache::save(&super::draft_cache::path(), &bytes) {
                    Ok(()) => saved_cache = bytes,
                    Err(error) => {
                        frame.lock().unwrap().error =
                            Some(format!("Local draft recovery unavailable: {error}"))
                    }
                }
            }
            Err(error) => frame.lock().unwrap().error = Some(error),
            _ => {}
        }
        let mut pending = Vec::new();
        for task in approvals.drain(..) {
            if task.is_finished() {
                let _ = task.join();
            } else {
                pending.push(task);
            }
        }
        approvals = pending;
        match rx.recv_timeout(Duration::from_millis(50)) {
            Ok(Command::Quit) => {
                flush(&socket, &drafts, &frame, &stop);
                break;
            }
            Ok(command) => {
                if let Command::ReviewInput { proposal, reply } = command {
                    if approvals.len() >= 4 {
                        let _ = reply.send(Err("Four broker review requests are pending".into()));
                        continue;
                    }
                    let stopping = stop.clone();
                    approvals.push(thread::spawn(move || {
                        let _ = reply.send(super::broker_controls::input(
                            broker_socket(),
                            proposal,
                            stopping,
                        ));
                    }));
                    continue;
                }
                if let Command::Approve(proposal) = command {
                    if approval_pending
                        .compare_exchange(false, true, Ordering::Relaxed, Ordering::Relaxed)
                        .is_err()
                    {
                        frame.lock().unwrap().error = Some("An approval is already pending".into());
                        continue;
                    }
                    let (pending, view, stopping) =
                        (approval_pending.clone(), frame.clone(), stop.clone());
                    let core_socket = socket.clone();
                    approvals.push(thread::spawn(move || {
                        let result =
                            super::broker_controls::approve(broker_socket(), proposal, stopping.clone()).and_then(|job|{
                                if stopping.load(Ordering::Relaxed){return Ok(json!({"notice":"Approved"}));}
                                match super::broker_controls::continuation_request(&job){
                                    Some(query)=>request(&core_socket,&query).map(|work|json!({"notice":format!("Approved · continuing the original request in work {}",work["id"])})).map_err(|error|format!("Approved, but continuation could not start: {error}. Use Continue request to retry.")),
                                    None=>Ok(json!({"notice":"Approved · inspect the existing work for its result"})),
                                }
                            });
                        let mut frame = view.lock().unwrap();
                        match result {
                            Ok(result) => {
                                frame.error = None;
                                frame.notice = result["notice"].as_str().map(String::from);
                            }
                            Err(error) => frame.error = Some(error),
                        }
                        pending.store(false, Ordering::Relaxed);
                    }));
                    continue;
                }
                let result=match command {
                    Command::Approve(_)|Command::ReviewInput{..}=>unreachable!(),
                    Command::Resume(job)=>super::broker_controls::job_id(&job).and_then(|id|request(&broker_socket(),&json!({"op":"poll","job_id":id}))).and_then(|current|super::broker_controls::continuation_request(&current).ok_or("No approved agent request is associated with this work".into())).and_then(|query|request(&socket,&query)),
                    Command::Attach(job)=>super::broker_controls::attach(&job),
                    Command::OpenTerminal=>super::broker_controls::open_terminal(),
                    Command::WorkspaceEdit{workspace,revision,edit}=>request(&socket,&json!({"op":"presentation.apply","protocol":"agentos.presentation/1","catalog_revision":"native-core/1","request_id":format!("workspace-{}",super::nonce()),"expected_revisions":{workspace.clone():revision},"operations":[{"op":"workspace.edit","workspace_id":workspace,"edit":edit}]})).map(|receipt|{frame.lock().unwrap().workspace_undo=receipt["event_cursor"].as_i64();receipt}),
                    Command::WorkspaceUndo(cursor)=>request(&socket,&json!({"op":"presentation.undo","event_cursor":cursor,"request_id":format!("undo-{}",super::nonce())})).map(|receipt|{frame.lock().unwrap().workspace_undo=None;receipt}),
                    Command::RegisterRenderer(surface)=>request(&socket,&json!({"op":"host.renderer","surface_id":surface})),
                    Command::ResolveDraft{surface,element,commit}=>resolve_draft(&socket,&surface,&element,commit,&drafts),
                    Command::Preferences(value)=>super::preferences::save(&value),
                    Command::Setup=>std::process::Command::new("weston-terminal").args(["--shell","/usr/local/bin/agent-os-setup"]).spawn().map(|mut child|{std::thread::spawn(move||{let _=child.wait();});json!({"status":"Setup opened"})}).map_err(|e|e.to_string()),
                    Command::SelectActivity(id)=>{activity=Some(id);Ok(json!({"status":"Activity selected"}))},
                    Command::CreateActivity(name)=>request(&socket,&json!({"op":"create","name":name})).map(|created|{activity=Some(created["id"].to_string());created}),
                    Command::Ask{activity,prompt,grounding}=>{
                        if prompt.trim().is_empty() || prompt.len()>16000 {Err("Enter a request up to 16 KiB".into())}
                        else {
                            let mut argv=vec!["/usr/bin/python3".to_string(),"-u".into(),"/usr/local/lib/agent-os/services/worker.py".into(),"ask".into(),activity.to_string(),prompt];
                            if let Some(context)=grounding {
                                let surface=context["surface_id"].as_str().unwrap_or("");
                                if surface=="native-monitor" {
                                    let reference=&context["job_ref"];
                                    let valid=if let Some(id)=reference.as_i64() {
                                        request(&socket,&json!({"op":"job.get","job_id":id})).map(|job|job["id"]==id && job["activity_id"]==activity).unwrap_or(false)
                                    }else if let Some(id)=reference.as_str().and_then(|r|r.strip_prefix("broker:")) {
                                        request(&broker_socket(),&json!({"op":"poll","job_id":id})).map(|job|job["activity"]==activity).unwrap_or(false)
                                    }else{false};
                                    if !valid {frame.lock().unwrap().error=Some("The recorded work is unavailable or belongs to another activity; record a new request".into());continue;}
                                }else if surface!="native-launcher" {
                                    let snapshot=super::presentation_pages::read(|value|request(&socket,value),None,||stop.load(Ordering::Relaxed));
                                    if snapshot.as_ref().map(|s|s["documents"][surface]["activity_id"].as_str()!=Some(activity.to_string().as_str())).unwrap_or(true) {
                                        frame.lock().unwrap().error=Some("The recorded view was closed or moved; record a new request".into());continue;
                                    }
                                }
                                argv.extend(["--grounding".into(),context.to_string()]);
                            }
                            request(&socket,&json!({"op":"run","activity_id":activity,"argv":argv}))
                        }
                    },
                    Command::Stop{source,job}=>request(&if source=="core"{socket.clone()}else{broker_socket()},&json!({"op":"cancel","job_id":job})),
                    Command::Inspect{source,job}=>{
                        let current=frame.lock().unwrap().clone();
                        let rows=if source=="core"{current.core["jobs"].as_array()}else{current.broker.as_array()};
                        let metadata=rows.and_then(|rows|rows.iter().find(|row|row["id"]==job));
                        match metadata.and_then(|row|row[if source=="core"{"activity_id"}else{"activity"}].as_i64().map(|activity|(activity,row["argv"].to_string()))) {
                            Some((activity,title))=>super::log_view::LogView::new(source,job,activity,title).and_then(|mut view|{view.following=true;let page=view.read(&socket,0)?;frame.lock().unwrap().inspection=Some(page);output_view=Some(view);Ok(json!({"status":"Output page loaded"}))}),
                            None=>Err("This work is no longer available in the current snapshot".into()),
                        }
                    },
                    Command::PageOutput(direction)=>match output_view.as_mut(){Some(view)=>{view.following=false;view.read(&socket,direction).map(|page|{frame.lock().unwrap().inspection=Some(page);json!({"status":"Output page loaded"})})},None=>Err("Select work to inspect first".into())},
                    Command::FollowOutput(following)=>match output_view.as_mut(){Some(view)=>{view.following=following;if let Some(page)=frame.lock().unwrap().inspection.as_mut(){page.following=following;}Ok(json!({"status":if following{"Following output"}else{"Output paused"}}))},None=>Err("Select work to inspect first".into())},
                    Command::FreezeOutput(offset)=>{if let Some(view)=output_view.as_mut(){view.pause_at(offset);}if let Some(page)=frame.lock().unwrap().inspection.as_mut(){page.following=false;}Ok(json!({"status":"Output paused for selection"}))},
                    Command::Lease{surface,element,begin}=>{
                        let key=(surface.clone(),element.clone());
                        if begin {leases.insert(key,Instant::now());}else{leases.remove(&key);}
                        request(&socket,&json!({"op":if begin{"interaction.begin"}else{"interaction.end"},"surface_id":surface,"element_id":element}))
                    }
                    Command::Action{reference,key,surface,revision,action,parameters}=>request(&socket,&json!({"op":"action.metadata","reference":reference})).and_then(|info|{
                        let current=frame.lock().unwrap().clone();
                        let edits=drafts.lock().unwrap();
                        let values=super::action_parameters::resolve(&parameters,&info["parameter_schema"],|element|edits.get(&(surface.clone(),element.into())).map(|d|d.text.clone()).or_else(||current.documents.get(&surface).and_then(|doc|doc["elements"][element]["props"]["value"].as_str().map(String::from))))?;
                        drop(edits);
                        let receipt=match request(&socket,&json!({"op":"action.invoke","reference":reference,"request_id":key,"expected_source_revision":info["source_revision"],"surface_id":surface,"expected_surface_revision":revision,"action_id":action,"parameters":values})) {
                            Ok(receipt)=>receipt,
                            Err(original)=>request(&socket,&json!({"op":"action.status","request_id":key})).map_err(|_|original)?,
                        };
                        if ["job.read_output","broker.read_output"].contains(&info["operation"].as_str().unwrap_or("")) && receipt["status"]=="succeeded" {
                            let (source,job)=if let Some(id)=info["target"]["source"].as_str().and_then(|source|source.strip_prefix("broker:")){("broker",json!(id))}else{("core",info["target"]["job_id"].clone())};let activity=info["activity_id"].as_str().and_then(|a|a.parse::<i64>().ok()).ok_or("Action activity unavailable")?;
                            let mut view=super::log_view::LogView::new(source.into(),job,activity,"Callback output".into())?;
                            view.start_at(values["offset"].as_u64().unwrap_or(0));
                            frame.lock().unwrap().inspection=Some(view.read(&socket,0)?);output_view=Some(view);
                        }
                        Ok(receipt)
                    }),
                    Command::Close{surface}=>{flush(&socket,&drafts,&frame,&stop);if drafts.lock().unwrap().iter().any(|((id,_),draft)|id==&surface && draft.dirty){Err("The view remains open because its latest draft could not be saved".into())}else{close_surface(&socket,&surface).map(|receipt|{frame.lock().unwrap().workspace_undo=receipt["event_cursor"].as_i64();receipt})}},
                    Command::Quit=>unreachable!(),
                };
                let mut view = frame.lock().unwrap();
                match result {
                    Err(e) => view.error = Some(e),
                    Ok(value) => {
                        view.error = None;
                        view.notice = Some(
                            if value["observed_target"]["source"]
                                .as_str()
                                .is_some_and(|source| source.starts_with("file:"))
                            {
                                let observed = &value["observed_target"];
                                let values = &observed["values"];
                                format!(
                                    "Last observed {} · {} · {} · permissions {} · measured {}",
                                    values["path"].as_str().unwrap_or("File"),
                                    values["kind"].as_str().unwrap_or("unavailable"),
                                    values["size_text"].as_str().unwrap_or("Unavailable"),
                                    values["mode_text"].as_str().unwrap_or("Unavailable"),
                                    observed["observed_at"]
                                )
                            } else if let Some(id) = value.get("id") {
                                format!(
                                    "Work {} · {}",
                                    id,
                                    value["status"].as_str().unwrap_or("accepted")
                                )
                            } else {
                                value["status"].as_str().unwrap_or("Done").to_string()
                            },
                        );
                    }
                }
            }
            Err(mpsc::RecvTimeoutError::Disconnected) => break,
            Err(mpsc::RecvTimeoutError::Timeout) => {}
        }
        for ((surface, element), at) in &mut leases {
            if at.elapsed() > Duration::from_secs(5) {
                let _ = request(
                    &socket,
                    &json!({"op":"interaction.renew","surface_id":surface,"element_id":element}),
                );
                *at = Instant::now();
            }
        }
        if last.elapsed() < Duration::from_millis(250) {
            continue;
        }
        last = Instant::now();
        if let Some(view) = output_view.as_mut() {
            match view.follow(&socket) {
                Ok(Some(page)) => frame.lock().unwrap().inspection = Some(page),
                Err(error) => {
                    frame.lock().unwrap().error =
                        Some(format!("Live output temporarily unavailable: {error}"))
                }
                _ => {}
            }
        }
        recovered.retain(|(surface, element)| {
            if stop.load(Ordering::Relaxed) {
                return true;
            }
            request(
                &socket,
                &json!({"op":"interaction.begin","surface_id":surface,"element_id":element}),
            )
            .is_err()
        });
        flush(&socket, &drafts, &frame, &stop);
        match presentation_cache.read(
            |value| request(&socket, value),
            activity.as_deref(),
            || stop.load(Ordering::Relaxed),
        ) {
            Ok(state) => {
                let mut next = Frame {
                    connected: true,
                    ..Frame::default()
                };
                next.host_surfaces = state["host_surfaces"].clone();
                next.outputs = state["outputs"].clone();
                if let Some(path) = std::env::var_os("AGENT_OS_COMPOSITOR_SOCKET") {
                    next.compositor = request(&PathBuf::from(path), &json!({"op":"snapshot"}))
                        .map(|v| v["shared"].clone())
                        .unwrap_or_else(|error| json!({"unavailable":error}));
                }
                next.core = super::state_pages::read(
                    |query| request(&socket, query),
                    activity.as_ref().and_then(|id| id.parse().ok()),
                    || stop.load(Ordering::Relaxed),
                )
                .unwrap_or_else(|e| json!({"unavailable":e}));
                next.broker = super::broker_pages::read(
                    |query| request(&broker_socket(), query),
                    activity.as_ref().and_then(|id| id.parse().ok()),
                    || stop.load(Ordering::Relaxed),
                )
                .unwrap_or_else(|e| json!({"unavailable":e}));
                next.usage = std::fs::read_to_string(
                    std::env::var("AGENT_OS_MODEL_USAGE")
                        .unwrap_or_else(|_| "/run/agent-os-ai/model-usage.json".into()),
                )
                .ok()
                .filter(|s| s.len() <= 1024 * 1024)
                .and_then(|s| serde_json::from_str(&s).ok())
                .unwrap_or_else(|| json!({"unavailable":true}));
                if activity.is_none() {
                    activity = next.core["activities"]
                        .as_array()
                        .and_then(|a| a.first())
                        .map(|a| a["id"].to_string());
                }
                if shown_activity != activity {
                    if let (Some(path), Some(id)) = (
                        std::env::var_os("AGENT_OS_COMPOSITOR_SOCKET"),
                        activity.as_ref(),
                    ) {
                        if let Err(error) = request(
                            &PathBuf::from(path),
                            &json!({"op":"workspace.activity","activity_id":id}),
                        ) {
                            next.error = Some(format!("Activity placement unavailable: {error}"));
                        } else {
                            shown_activity = activity.clone();
                        }
                    }
                }
                next.activity = activity.clone();
                if let Some(id) = activity.as_ref().and_then(|id| id.parse::<i64>().ok()) {
                    let jobs = next.core["jobs"]
                        .as_array()
                        .into_iter()
                        .flatten()
                        .filter(|job| job["activity_id"].as_i64() == Some(id))
                        .filter_map(|job| job["id"].as_i64())
                        .filter(|id| !ensured.contains(id))
                        .take(64)
                        .collect::<Vec<_>>();
                    if !jobs.is_empty() && !stop.load(Ordering::Relaxed) {
                        if request(
                            &socket,
                            &json!({"op":"action.ensure","activity_id":id,"job_ids":jobs}),
                        )
                        .is_ok()
                        {
                            if ensured.len() > 4096 {
                                ensured.clear();
                            }
                            ensured.extend(jobs);
                        }
                    }
                }
                if let Some(id) = activity.as_ref().and_then(|id| id.parse::<i64>().ok()) {
                    if source_scan.0 != activity {
                        source_scan = (activity.clone(), String::new());
                    }
                    if !stop.load(Ordering::Relaxed) {
                        if let Ok(page) = request(
                            &socket,
                            &json!({"op":"source.list","activity_id":id.to_string(),"after":source_scan.1,"limit":64}),
                        ) {
                            let sources = page["sources"]
                                .as_array()
                                .into_iter()
                                .flatten()
                                .filter_map(|row| row["source"].as_str())
                                .filter(|source| {
                                    source.starts_with("broker:") || source.starts_with("file:")
                                })
                                .filter(|source| !ensured_sources.contains(*source))
                                .map(String::from)
                                .collect::<Vec<_>>();
                            let registered=sources.is_empty() || request(&socket,&json!({"op":"action.ensure_sources","activity_id":id,"sources":sources})).is_ok();
                            if registered {
                                if ensured_sources.len() > 4096 {
                                    ensured_sources.clear();
                                }
                                ensured_sources.extend(sources);
                                source_scan.1 = if page["has_more"] == true {
                                    page["next"].as_str().unwrap_or("").into()
                                } else {
                                    String::new()
                                };
                            }
                        }
                    }
                }
                if let Some(documents) = state["documents"].as_object() {
                    for (id, doc) in documents {
                        if stop.load(Ordering::Relaxed) {
                            break;
                        }
                        if activity
                            .as_ref()
                            .map(|a| Some(a.as_str()) != doc["activity_id"].as_str())
                            .unwrap_or(false)
                        {
                            continue;
                        }
                        next.documents.insert(id.clone(), doc.clone());
                        if doc.get("surface_id").is_none() {
                            continue;
                        }
                        if let Ok(bindings) =
                            request(&socket, &json!({"op":"binding.snapshot","surface_id":id}))
                        {
                            next.bindings.insert(id.clone(), bindings);
                        }
                        if let Some(actions) = doc["actions"].as_object() {
                            for action in actions.values() {
                                if stop.load(Ordering::Relaxed) {
                                    break;
                                }
                                if let Some(reference) = action["ref"].as_str() {
                                    if let Ok(info) = request(
                                        &socket,
                                        &json!({"op":"action.metadata","reference":reference}),
                                    ) {
                                        next.actions.insert(reference.into(), info);
                                    }
                                }
                            }
                        }
                        if let Some(elements) = doc["elements"].as_object() {
                            for (element, node) in elements {
                                if stop.load(Ordering::Relaxed) {
                                    break;
                                }
                                if ["TextField@1", "Choice@1", "Toggle@1"]
                                    .iter()
                                    .any(|kind| node["type"] == *kind)
                                {
                                    if let Ok(draft) = request(
                                        &socket,
                                        &json!({"op":"draft.get","surface_id":id,"element_id":element}),
                                    ) {
                                        next.drafts.insert((id.clone(), element.clone()), draft);
                                    }
                                }
                            }
                        }
                    }
                }
                let mut old = frame.lock().unwrap();
                next.workspace_undo = old.workspace_undo;
                if next.error.is_none() {
                    next.error = old.error.take();
                }
                next.inspection = old.inspection.clone();
                next.notice = old.notice.take();
                *old = next;
            }
            Err(e) => {
                let mut current = frame.lock().unwrap();
                current.connected = false;
                current.error = Some(e);
            }
        }
    }
    for approval in approvals {
        let _ = approval.join();
    }
}
fn flush(
    socket: &PathBuf,
    drafts: &Arc<Mutex<BTreeMap<(String, String), Draft>>>,
    frame: &Arc<Mutex<Frame>>,
    stop: &AtomicBool,
) {
    let pending = drafts.lock().unwrap().clone();
    for ((surface, element), draft) in pending.into_iter().filter(|(_, d)| d.dirty) {
        if stop.load(Ordering::Relaxed) {
            break;
        }
        let result = request(
            socket,
            &json!({"op":"draft.save","surface_id":surface,"element_id":element,"expected_draft_revision":draft.expected,"draft":draft.text}),
        );
        match result {
            Ok(receipt) => {
                if let Some(current) = drafts.lock().unwrap().get_mut(&(surface, element)) {
                    current.expected = receipt["draft_revision"].as_u64().unwrap_or(draft.expected);
                    if current.text == draft.text {
                        current.dirty = false;
                    }
                }
            }
            Err(e) => {
                frame.lock().unwrap().error = Some(format!("Draft retained locally: {e}"));
            }
        }
    }
}
fn close_surface(socket: &PathBuf, surface: &str) -> Result<Value, String> {
    let state = super::presentation_pages::read(|value| request(socket, value), None, || false)?;
    let revision = state["documents"][surface]["revision"].clone();
    if revision.is_null() {
        return Err("Surface is already closed".into());
    }
    let mut expected = json!({surface:revision});
    let mut operations = Vec::new();
    fn contains(value: &Value, id: &str) -> bool {
        match value {
            Value::Object(m) => {
                m.get("surface_id").and_then(Value::as_str) == Some(id)
                    || m.values().any(|v| contains(v, id))
            }
            Value::Array(a) => a.iter().any(|v| contains(v, id)),
            _ => false,
        }
    }
    for doc in state["documents"]
        .as_object()
        .into_iter()
        .flat_map(|m| m.values())
    {
        if doc.get("workspace_id").is_some() && contains(&doc["outputs"], surface) {
            let id = doc["workspace_id"]
                .as_str()
                .ok_or("Invalid workspace identity")?;
            expected[id] = doc["revision"].clone();
            operations.push(json!({"op":"workspace.edit","workspace_id":id,"edit":{"kind":"remove","surface_id":surface}}));
        }
    }
    operations.push(json!({"op":"surface.close","surface_id":surface}));
    let transaction = json!({"op":"presentation.apply","protocol":"agentos.presentation/1","catalog_revision":"native-core/1","request_id":format!("close-{}",super::nonce()),"expected_revisions":expected,"operations":operations});
    // An ambiguous acknowledgement retries the identical durable request, never a new action.
    request(socket, &transaction).or_else(|_| request(socket, &transaction))
}

pub(crate) fn broker_socket() -> PathBuf {
    PathBuf::from(
        std::env::var("AGENT_OS_BROKER_SOCKET")
            .unwrap_or_else(|_| "/run/agent-os-broker/api.sock".into()),
    )
}

fn resolve_draft(
    socket: &PathBuf,
    surface: &str,
    element: &str,
    commit: bool,
    drafts: &Arc<Mutex<BTreeMap<(String, String), Draft>>>,
) -> Result<Value, String> {
    request(
        socket,
        &json!({"op":"interaction.begin","surface_id":surface,"element_id":element}),
    )?;
    let local = drafts
        .lock()
        .unwrap()
        .get(&(surface.into(), element.into()))
        .cloned();
    let mut saved = request(
        socket,
        &json!({"op":"draft.get","surface_id":surface,"element_id":element}),
    )?;
    if let Some(local) = &local {
        if local.dirty && commit {
            let receipt = request(
                socket,
                &json!({"op":"draft.save","surface_id":surface,"element_id":element,"expected_draft_revision":local.expected,"draft":local.text}),
            )?;
            saved = json!({"draft_revision":receipt["draft_revision"],"draft":local.text});
        } else if commit && saved["draft_revision"].as_u64() != Some(local.expected) {
            return Err("Draft changed in another editor; recover before resolving it".into());
        }
    }
    let snapshot = super::presentation_pages::read(|value| request(socket, value), None, || false)?;
    let doc = &snapshot["documents"][surface];
    let revision = doc["revision"].as_u64().ok_or("View unavailable")?;
    let expected = saved["draft_revision"]
        .as_u64()
        .ok_or("Draft unavailable")?;
    let (text, resolved, receipt) = if commit {
        let text = saved["draft"]
            .as_str()
            .ok_or("No draft to save")?
            .to_string();
        let payload = json!({"op":"presentation.apply","protocol":"agentos.presentation/1","catalog_revision":"native-core/1","request_id":format!("save-draft-{}",super::nonce()),"expected_revisions":{surface:revision},"operations":[{"op":"draft.commit","surface_id":surface,"element_id":element,"expected_draft_revision":expected}]});
        let receipt = request(socket, &payload).or_else(|_| request(socket, &payload))?;
        let resolved = receipt["revisions"][surface]
            .as_u64()
            .ok_or("Missing commit revision")?;
        (text, resolved, receipt)
    } else {
        let value = &doc["elements"][element]["props"]["value"];
        let text = value.as_str().map(String::from).unwrap_or_else(|| {
            value
                .as_bool()
                .map(|value| value.to_string())
                .unwrap_or_default()
        });
        let receipt = request(
            socket,
            &json!({"op":"draft.save","surface_id":surface,"element_id":element,"expected_draft_revision":expected,"draft":null}),
        )?;
        (text, revision, receipt)
    };
    let mut edits = drafts.lock().unwrap();
    if edits
        .get(&(surface.into(), element.into()))
        .map(|d| local.as_ref().map(|l| d.text != l.text).unwrap_or(true))
        .unwrap_or(false)
    {
        // Input typed while the worker committed belongs to the next draft revision.
        if let Some(draft) = edits.get_mut(&(surface.into(), element.into())) {
            draft.expected = expected + 1;
            draft.dirty = true;
            draft.resolved = None;
        }
    } else {
        edits.insert(
            (surface.into(), element.into()),
            Draft {
                text,
                expected: expected + 1,
                dirty: false,
                resolved: Some(resolved),
            },
        );
    }
    Ok(receipt)
}
