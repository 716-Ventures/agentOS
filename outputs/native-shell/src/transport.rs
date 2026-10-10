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
    let mut conn = UnixStream::connect(socket).map_err(|e| e.to_string())?;
    conn.set_read_timeout(Some(Duration::from_secs(3)))
        .map_err(|e| e.to_string())?;
    conn.set_write_timeout(Some(Duration::from_secs(3)))
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
}
#[derive(Clone, Default, Debug)]
pub struct Frame {
    pub documents: BTreeMap<String, Value>,
    pub bindings: BTreeMap<String, Value>,
    pub actions: BTreeMap<String, Value>,
    pub drafts: BTreeMap<(String, String), Value>,
    pub connected: bool,
    pub error: Option<String>,
}
#[derive(Debug)]
pub enum Command {
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
    activity: Option<String>,
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
                    Command::Lease{surface,element,begin}=>{
                        let key=(surface.clone(),element.clone());
                        if begin {leases.insert(key,Instant::now());}else{leases.remove(&key);}
                        request(&socket,&json!({"op":if begin{"interaction.begin"}else{"interaction.end"},"surface_id":surface,"element_id":element}))
                    }
                    Command::Action{reference,key}=>request(&socket,&json!({"op":"action.metadata","reference":reference})).and_then(|info|request(&socket,&json!({"op":"action.invoke","reference":reference,"request_id":key,"expected_source_revision":info["source_revision"]}))),
                    Command::Close{surface}=>close_surface(&socket,&surface),
                    Command::Quit=>unreachable!(),
                };
                if let Err(e) = result {
                    frame.lock().unwrap().error = Some(e);
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
