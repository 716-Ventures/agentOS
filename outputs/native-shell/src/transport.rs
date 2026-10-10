//! IPC runs on a worker, never on GTK's input/render thread.
use serde_json::{json, Value};
use std::{
    collections::BTreeMap,
    io::{BufRead, BufReader, Write},
    os::unix::net::UnixStream,
    path::PathBuf,
    sync::{
        mpsc::{self, Receiver, Sender},
        Arc, Mutex,
    },
    thread,
    time::{Duration, Instant},
};
const LIMIT: usize = 4 * 1024 * 1024;
pub fn request(socket: &PathBuf, value: &Value) -> Result<Value, String> {
    request_timeout(socket, value, Duration::from_secs(3))
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
    pub broker: Value,
    pub usage: Value,
    pub activity: Option<String>,
    pub inspection: Option<String>,
    pub notice: Option<String>,
    pub connected: bool,
    pub error: Option<String>,
}
#[derive(Debug)]
pub enum Command {
    RegisterRenderer(String),
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
}
impl Backend {
    pub fn start(socket: PathBuf, activity: Option<String>) -> Self {
        let (commands, rx) = mpsc::channel();
        let frame = Arc::new(Mutex::new(Frame::default()));
        let drafts = Arc::new(Mutex::new(BTreeMap::new()));
        let (view, edits) = (frame.clone(), drafts.clone());
        let worker = thread::spawn(move || run(socket, activity, rx, view, edits));
        Self {
            commands,
            frame,
            drafts,
            worker: Some(worker),
        }
    }
    pub fn close(&mut self) {
        let _ = self.commands.send(Command::Quit);
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
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
) {
    let mut leases = BTreeMap::<(String, String), Instant>::new();
    let mut last = Instant::now() - Duration::from_secs(1);
    loop {
        match rx.recv_timeout(Duration::from_millis(50)) {
            Ok(Command::Quit) => {
                flush(&socket, &drafts, &frame);
                break;
            }
            Ok(command) => {
                let result=match command {
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
                                if surface!="native-launcher" {
                                    let snapshot=request(&socket,&json!({"op":"presentation.snapshot"}));
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
                        let result=request(&if source=="core"{socket.clone()}else{broker_socket()},&json!({"op":if source=="core"{"log"}else{"poll"},"job_id":job,"offset":0}));
                        if let Ok(data)=&result {frame.lock().unwrap().inspection=Some(data[if source=="core"{"text"}else{"output"}].as_str().unwrap_or("No output available").into());}result
                    },
                    Command::Lease{surface,element,begin}=>{
                        let key=(surface.clone(),element.clone());
                        if begin {leases.insert(key,Instant::now());}else{leases.remove(&key);}
                        request(&socket,&json!({"op":if begin{"interaction.begin"}else{"interaction.end"},"surface_id":surface,"element_id":element}))
                    }
                    Command::Action{reference,key}=>request(&socket,&json!({"op":"action.metadata","reference":reference})).and_then(|info|request(&socket,&json!({"op":"action.invoke","reference":reference,"request_id":key,"expected_source_revision":info["source_revision"]}))),
                    Command::Close{surface}=>close_surface(&socket,&surface),
                    Command::Quit=>unreachable!(),
                };
                let mut view = frame.lock().unwrap();
                match result {
                    Err(e) => view.error = Some(e),
                    Ok(value) => {
                        view.error = None;
                        view.notice = Some(if let Some(id) = value.get("id") {
                            format!(
                                "Work {} · {}",
                                id,
                                value["status"].as_str().unwrap_or("accepted")
                            )
                        } else {
                            value["status"].as_str().unwrap_or("Done").to_string()
                        });
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
        flush(&socket, &drafts, &frame);
        match request(&socket, &json!({"op":"presentation.snapshot"})) {
            Ok(state) => {
                let mut next = Frame {
                    connected: true,
                    ..Frame::default()
                };
                next.core = request(&socket, &json!({"op":"snapshot"}))
                    .unwrap_or_else(|e| json!({"unavailable":e}));
                next.broker = request(&broker_socket(), &json!({"op":"list"}))
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
                next.activity = activity.clone();
                if let Some(documents) = state["documents"].as_object() {
                    for (id, doc) in documents {
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
                                if node["type"] == "TextField@1" {
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
                next.error = old.error.take();
                next.inspection = old.inspection.take();
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
}
fn flush(
    socket: &PathBuf,
    drafts: &Arc<Mutex<BTreeMap<(String, String), Draft>>>,
    frame: &Arc<Mutex<Frame>>,
) {
    let pending = drafts.lock().unwrap().clone();
    for ((surface, element), draft) in pending.into_iter().filter(|(_, d)| d.dirty) {
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
    let state = request(socket, &json!({"op":"presentation.snapshot"}))?;
    let revision = state["documents"][surface]["revision"].clone();
    if revision.is_null() {
        return Err("Surface is already closed".into());
    }
    // Placement removal is explicit and atomic with closure. A compositor can perform
    // richer tree collapse; this first client refuses to orphan a placed surface.
    for doc in state["documents"]
        .as_object()
        .into_iter()
        .flat_map(|m| m.values())
    {
        if doc.get("workspace_id").is_some()
            && doc["outputs"]
                .to_string()
                .contains(&format!("\"{surface}\""))
        {
            return Err(
                "Use workspace close-view to remove a placed surface; its draft is retained".into(),
            );
        }
    }
    request(
        socket,
        &json!({"op":"presentation.apply","protocol":"agentos.presentation/1","catalog_revision":"native-core/1","request_id":format!("close-{}",super::nonce()),"expected_revisions":{surface:revision},"operations":[{"op":"surface.close","surface_id":surface}]}),
    )
}

fn broker_socket() -> PathBuf {
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
        if local.dirty {
            let receipt = request(
                socket,
                &json!({"op":"draft.save","surface_id":surface,"element_id":element,"expected_draft_revision":local.expected,"draft":local.text}),
            )?;
            saved = json!({"draft_revision":receipt["draft_revision"],"draft":local.text});
        } else if saved["draft_revision"].as_u64() != Some(local.expected) {
            return Err("Draft changed in another editor; recover before resolving it".into());
        }
    }
    let snapshot = request(socket, &json!({"op":"presentation.snapshot"}))?;
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
        let text = doc["elements"][element]["props"]["value"]
            .as_str()
            .unwrap_or("")
            .to_string();
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
