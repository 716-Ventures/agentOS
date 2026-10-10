mod presentation;
mod presentation_actions;
mod presentation_hosts;
use rusqlite::{params, Connection};
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    fs::{self, File, OpenOptions},
    io::{BufRead, BufReader, Read, Seek, SeekFrom, Write},
    os::unix::{
        fs::PermissionsExt,
        net::{UnixListener, UnixStream},
        process::CommandExt,
    },
    path::PathBuf,
    process::{Command, Stdio},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    thread,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

type Result<T> = std::result::Result<T, String>;
const LOG_LIMIT: usize = 1024 * 1024;
// Withhold an incomplete UTF-8 suffix while a live producer can finish it.
fn log_text(bytes: &[u8], final_page: bool) -> (String, usize) {
    let mut consumed = bytes.len();
    if !final_page {
        let mut cursor = 0;
        while cursor < bytes.len() {
            match std::str::from_utf8(&bytes[cursor..]) {
                Ok(_) => break,
                Err(error) => {
                    cursor += error.valid_up_to();
                    if let Some(length) = error.error_len() {
                        cursor += length;
                    } else {
                        consumed = cursor;
                        break;
                    }
                }
            }
        }
    }
    (
        String::from_utf8_lossy(&bytes[..consumed]).into_owned(),
        consumed,
    )
}
struct Core {
    db: Mutex<Connection>,
    root: PathBuf,
    active: Mutex<HashMap<i64, Arc<AtomicBool>>>,
}
fn now() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs() as i64
}
fn err(e: impl std::fmt::Display) -> String {
    e.to_string()
}
fn field<'a>(v: &'a Value, k: &str) -> Result<&'a str> {
    v[k].as_str().ok_or(format!("Missing text field: {k}"))
}
fn id(v: &Value, k: &str) -> Result<i64> {
    v[k].as_i64()
        .filter(|x| *x > 0)
        .ok_or(format!("Invalid {k}"))
}
fn revision(db: &Connection) -> Result<i64> {
    db.query_row("SELECT value FROM meta WHERE key='revision'", [], |r| {
        r.get(0)
    })
    .map_err(err)
}
fn check_revision(db: &Connection, v: &Value) -> Result<()> {
    if let Some(expected) = v.get("expected_revision") {
        if expected.as_i64() != Some(revision(db)?) {
            return Err("State changed; refresh before submitting this action.".into());
        }
    }
    Ok(())
}
fn event(
    db: &Connection,
    activity: Option<i64>,
    job: Option<i64>,
    kind: &str,
    detail: &Value,
) -> Result<()> {
    db.execute(
        "INSERT INTO events(at,activity_id,job_id,kind,detail) VALUES(?,?,?,?,?)",
        params![now(), activity, job, kind, detail.to_string()],
    )
    .map_err(err)?;
    db.execute("UPDATE meta SET value=value+1 WHERE key='revision'", [])
        .map_err(err)?;
    Ok(())
}
fn job_value(r: &rusqlite::Row<'_>) -> rusqlite::Result<Value> {
    let argv: String = r.get(2)?;
    Ok(
        json!({"id":r.get::<_,i64>(0)?,"activity_id":r.get::<_,i64>(1)?,"argv":serde_json::from_str::<Value>(&argv).unwrap_or(Value::Null),"status":r.get::<_,String>(3)?,"exit_code":r.get::<_,Option<i32>>(4)?,"created_at":r.get::<_,i64>(5)?,"finished_at":r.get::<_,Option<i64>>(6)?,"error":r.get::<_,Option<String>>(7)?}),
    )
}
impl Core {
    fn open(root: PathBuf) -> Result<Arc<Self>> {
        fs::create_dir_all(root.join("workspaces")).map_err(err)?;
        fs::create_dir_all(root.join("logs")).map_err(err)?;
        let mut db = Connection::open(root.join("state.sqlite3")).map_err(err)?;
        db.execute_batch("PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; PRAGMA foreign_keys=ON;
          CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value INTEGER NOT NULL);
          INSERT OR IGNORE INTO meta VALUES('revision',0);
          CREATE TABLE IF NOT EXISTS removed_activities(activity_id INTEGER PRIMARY KEY,removed_at INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS activities(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,created_at INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY AUTOINCREMENT,activity_id INTEGER NOT NULL REFERENCES activities(id),argv TEXT NOT NULL,status TEXT NOT NULL,exit_code INTEGER,created_at INTEGER NOT NULL,finished_at INTEGER,error TEXT);
          CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,at INTEGER NOT NULL,activity_id INTEGER,job_id INTEGER,kind TEXT NOT NULL,detail TEXT NOT NULL);").map_err(err)?;
        presentation::init(&db)?;
        let tx = db.transaction().map_err(err)?;
        let stale: Vec<(i64, i64)> = {
            let mut s = tx.prepare("SELECT id,activity_id FROM jobs WHERE status IN ('starting','running','cancelling')").map_err(err)?;
            let rows = s
                .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))
                .map_err(err)?;
            rows.collect::<std::result::Result<_, _>>().map_err(err)?
        };
        for (job, activity) in stale {
            tx.execute("UPDATE jobs SET status='interrupted',finished_at=?,error='Service restarted; command was not replayed' WHERE id=?",params![now(),job]).map_err(err)?;
            event(
                &tx,
                Some(activity),
                Some(job),
                "job.interrupted",
                &json!({"reason":"service restart"}),
            )?;
        }
        tx.commit().map_err(err)?;
        Ok(Arc::new(Self {
            db: Mutex::new(db),
            root,
            active: Mutex::new(HashMap::new()),
        }))
    }
    fn snapshot(&self) -> Result<Value> {
        let db = self.db.lock().unwrap();
        let mut s = db
            .prepare("SELECT id,name,created_at FROM activities WHERE id NOT IN (SELECT activity_id FROM removed_activities) ORDER BY id DESC")
            .map_err(err)?;
        let activities=s.query_map([], |r| { let n:i64=r.get(0)?; Ok(json!({"id":n,"name":r.get::<_,String>(1)?,"created_at":r.get::<_,i64>(2)?,"workspace":self.root.join("workspaces").join(n.to_string())})) }).map_err(err)?.collect::<std::result::Result<Vec<_>,_>>().map_err(err)?;
        let mut s=db.prepare("SELECT id,activity_id,argv,status,exit_code,created_at,finished_at,error FROM jobs WHERE status IN ('starting','running','cancelling') OR id IN (SELECT id FROM jobs ORDER BY id DESC LIMIT 200) ORDER BY id DESC").map_err(err)?;
        let jobs = s
            .query_map([], job_value)
            .map_err(err)?
            .collect::<std::result::Result<Vec<_>, _>>()
            .map_err(err)?;
        Ok(
            json!({"revision":revision(&db)?,"activities":activities,"jobs":jobs,"version":env!("CARGO_PKG_VERSION"),"mode":"Gateway agent with effects-based broker; Jev typed advisory; separate offline voice service"}),
        )
    }
    fn create(&self, v: &Value) -> Result<Value> {
        let name = field(v, "name")?.trim();
        if name.is_empty() || name.len() > 100 || name.chars().any(char::is_control) {
            return Err("Use an activity name of 1–100 bytes without control characters.".into());
        }
        let mut db = self.db.lock().unwrap();
        check_revision(&db, v)?;
        let tx = db.transaction().map_err(err)?;
        tx.execute(
            "INSERT INTO activities(name,created_at) VALUES(?,?)",
            params![name, now()],
        )
        .map_err(err)?;
        let n = tx.last_insert_rowid();
        let workspace = self.root.join("workspaces").join(n.to_string());
        fs::create_dir_all(&workspace).map_err(err)?;
        event(
            &tx,
            Some(n),
            None,
            "activity.created",
            &json!({"name":name,"workspace":workspace}),
        )?;
        tx.commit().map_err(err)?;
        Ok(json!({"id":n,"name":name,"workspace":workspace}))
    }
    fn remove_activity(&self, v: &Value, restore: bool) -> Result<Value> {
        let activity = id(v, "activity_id")?;
        let mut db = self.db.lock().unwrap();
        check_revision(&db, v)?;
        db.query_row("SELECT id FROM activities WHERE id=?", [activity], |r| {
            r.get::<_, i64>(0)
        })
        .map_err(err)?;
        let tx = db.transaction().map_err(err)?;
        if restore {
            tx.execute(
                "DELETE FROM removed_activities WHERE activity_id=?",
                [activity],
            )
            .map_err(err)?;
        } else {
            tx.execute(
                "INSERT OR IGNORE INTO removed_activities VALUES(?,?)",
                params![activity, now()],
            )
            .map_err(err)?;
        }
        event(
            &tx,
            Some(activity),
            None,
            if restore {
                "activity.restored"
            } else {
                "activity.removed"
            },
            &json!({"retained":"files, history, layouts and existing jobs"}),
        )?;
        tx.commit().map_err(err)?;
        Ok(json!({"id":activity,"removed":!restore}))
    }
    fn run(self: &Arc<Self>, v: &Value) -> Result<Value> {
        let activity = id(v, "activity_id")?;
        let argv: Vec<String> = v["argv"]
            .as_array()
            .ok_or("argv must be an array")?
            .iter()
            .map(|a| {
                a.as_str()
                    .map(str::to_owned)
                    .ok_or("Every argument must be text".to_string())
            })
            .collect::<Result<_>>()?;
        if argv.is_empty()
            || argv.len() > 128
            || argv[0].is_empty()
            || argv.iter().any(|a| a.len() > 16384 || a.contains('\0'))
        {
            return Err("Invalid command arguments".into());
        }
        // active -> db is the common mutation lock order.
        let mut active = self.active.lock().unwrap();
        if active.len() >= 8 {
            return Err("Eight jobs are already active. Stop one before starting another.".into());
        }
        let mut db = self.db.lock().unwrap();
        check_revision(&db, v)?;
        db.query_row("SELECT id FROM activities WHERE id=? AND id NOT IN (SELECT activity_id FROM removed_activities)", [activity], |r| {
            r.get::<_, i64>(0)
        })
        .map_err(|_| "Activity not found".to_string())?;
        let tx = db.transaction().map_err(err)?;
        tx.execute(
            "INSERT INTO jobs(activity_id,argv,status,created_at) VALUES(?,?,'starting',?)",
            params![activity, serde_json::to_string(&argv).map_err(err)?, now()],
        )
        .map_err(err)?;
        let job = tx.last_insert_rowid();
        event(
            &tx,
            Some(activity),
            Some(job),
            "job.requested",
            &json!({"argv":argv,"authority":"explicit local user command"}),
        )?;
        tx.commit().map_err(err)?;
        let cancelled = Arc::new(AtomicBool::new(false));
        active.insert(job, cancelled.clone());
        drop(db);
        drop(active);
        let core = self.clone();
        thread::spawn(move || core.supervise(job, activity, argv, cancelled));
        Ok(json!({"id":job,"activity_id":activity,"status":"starting"}))
    }
    fn cancel(&self, v: &Value) -> Result<Value> {
        let job = id(v, "job_id")?;
        let active = self.active.lock().unwrap();
        let mut db = self.db.lock().unwrap();
        let activity = db
            .query_row("SELECT activity_id FROM jobs WHERE id=?", [job], |r| {
                r.get::<_, i64>(0)
            })
            .map_err(|_| "Job not found".to_string())?;
        if let Some(flag) = active.get(&job) {
            if !flag.swap(true, Ordering::SeqCst) {
                let tx = db.transaction().map_err(err)?;
                tx.execute("UPDATE jobs SET status='cancelling' WHERE id=?", [job])
                    .map_err(err)?;
                event(
                    &tx,
                    Some(activity),
                    Some(job),
                    "job.cancel_requested",
                    &json!({}),
                )?;
                tx.commit().map_err(err)?;
            }
            Ok(json!({"id":job,"status":"cancelling"}))
        } else {
            db.query_row("SELECT id,activity_id,argv,status,exit_code,created_at,finished_at,error FROM jobs WHERE id=?",[job],job_value).map_err(err)
        }
    }
    fn supervise(
        self: Arc<Self>,
        job: i64,
        activity: i64,
        argv: Vec<String>,
        cancel: Arc<AtomicBool>,
    ) {
        let result = self.execute(job, activity, &argv, &cancel);
        let mut active = self.active.lock().unwrap();
        let mut db = self.db.lock().unwrap();
        let (status, code, error) = match result {
            Ok(code) if cancel.load(Ordering::SeqCst) => ("cancelled", code, None),
            Ok(Some(0)) => ("succeeded", Some(0), None),
            Ok(code) => ("failed", code, None),
            Err(e) => ("failed", None, Some(e)),
        };
        let tx = db.transaction().expect("completion transaction");
        tx.execute(
            "UPDATE jobs SET status=?,exit_code=?,finished_at=?,error=? WHERE id=?",
            params![status, code, now(), error, job],
        )
        .expect("persist job result");
        event(
            &tx,
            Some(activity),
            Some(job),
            "job.finished",
            &json!({"status":status,"exit_code":code,"error":error}),
        )
        .expect("persist result event");
        tx.commit().expect("commit result");
        active.remove(&job);
    }
    fn execute(
        &self,
        job: i64,
        activity: i64,
        argv: &[String],
        cancel: &AtomicBool,
    ) -> Result<Option<i32>> {
        if cancel.load(Ordering::SeqCst) {
            return Ok(None);
        }
        let file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(self.root.join("logs").join(format!("{job}.log")))
            .map_err(err)?;
        let sink = Arc::new(Mutex::new((file, 0usize, false)));
        let mut command = Command::new(&argv[0]);
        command
            .args(&argv[1..])
            .current_dir(self.root.join("workspaces").join(activity.to_string()))
            .env_clear()
            .env("PATH", "/usr/local/bin:/usr/bin:/bin")
            .env("LANG", "C.UTF-8")
            .env("AGENT_OS_JOB_ID", job.to_string())
            .env(
                "HOME",
                self.root.join("workspaces").join(activity.to_string()),
            )
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .process_group(0);
        let mut child = command.spawn().map_err(err)?;
        let pid = child.id() as i32;
        {
            let mut db = self.db.lock().unwrap();
            let tx = db.transaction().map_err(err)?;
            tx.execute(
                "UPDATE jobs SET status='running' WHERE id=? AND status='starting'",
                [job],
            )
            .map_err(err)?;
            event(
                &tx,
                Some(activity),
                Some(job),
                "job.started",
                &json!({"pid":pid}),
            )?;
            tx.commit().map_err(err)?;
        }
        let out = pump(child.stdout.take().unwrap(), sink.clone());
        let stderr = pump(child.stderr.take().unwrap(), sink);
        let mut stopping = None;
        let status = loop {
            if cancel.load(Ordering::SeqCst) && stopping.is_none() {
                unsafe {
                    libc::kill(-pid, libc::SIGTERM);
                }
                stopping = Some(Instant::now());
            }
            if stopping
                .map(|t| t.elapsed() > Duration::from_millis(700))
                .unwrap_or(false)
            {
                unsafe {
                    libc::kill(-pid, libc::SIGKILL);
                }
            }
            // WNOWAIT keeps the leader unreaped so its PID cannot be reused while
            // cleaning up other processes in the same group.
            let mut info: libc::siginfo_t = unsafe { std::mem::zeroed() };
            let rc = unsafe {
                libc::waitid(
                    libc::P_PID,
                    pid as u32,
                    &mut info,
                    libc::WEXITED | libc::WNOHANG | libc::WNOWAIT,
                )
            };
            if rc < 0 {
                unsafe {
                    libc::kill(-pid, libc::SIGKILL);
                }
                let _ = child.wait();
                return Err(std::io::Error::last_os_error().to_string());
            }
            if unsafe { info.si_pid() } != 0 {
                unsafe {
                    libc::kill(-pid, libc::SIGKILL);
                }
                break child.wait().map_err(err)?;
            }
            thread::sleep(Duration::from_millis(30));
        };
        let _ = out.join();
        let _ = stderr.join();
        Ok(status.code())
    }
    fn handle(self: &Arc<Self>, v: &Value) -> Result<Value> {
        match field(v, "op")? {
            "snapshot" => self.snapshot(),
            "create" => self.create(v),
            "remove_activity" => self.remove_activity(v, false),
            "restore_activity" => self.remove_activity(v, true),
            "removed_activities" => {
                let db = self.db.lock().unwrap();
                let mut q=db.prepare("SELECT a.id,a.name FROM activities a JOIN removed_activities r ON a.id=r.activity_id ORDER BY r.removed_at DESC").map_err(err)?;
                let rows = q
                    .query_map([], |r| {
                        Ok(json!({"id":r.get::<_,i64>(0)?,"name":r.get::<_,String>(1)?}))
                    })
                    .map_err(err)?
                    .collect::<std::result::Result<Vec<_>, _>>()
                    .map_err(err)?;
                Ok(json!(rows))
            }
            "run" => self.run(v),
            "cancel" => self.cancel(v),
            "log" => {
                let job = id(v, "job_id")?;
                let offset = v["offset"]
                    .as_u64()
                    .unwrap_or(0)
                    .min((LOG_LIMIT + 100) as u64);
                let path = self.root.join("logs").join(format!("{job}.log"));
                if !path.exists() {
                    return Ok(json!({"text":"","offset":0}));
                }
                let mut f = File::open(path).map_err(err)?;
                f.seek(SeekFrom::Start(offset)).map_err(err)?;
                let mut buf = vec![0; 32768];
                let n = f.read(&mut buf).map_err(err)?;
                let length = f.metadata().map_err(err)?.len();
                let live:bool=self.db.lock().unwrap().query_row("SELECT EXISTS(SELECT 1 FROM jobs WHERE id=? AND status IN ('starting','running','cancelling'))",[job],|r|r.get(0)).map_err(err)?;
                let (text, consumed) = log_text(&buf[..n], !live && offset + n as u64 >= length);
                Ok(
                    json!({"text":text,"offset":offset+consumed as u64,"has_more":offset+(consumed as u64)<length}),
                )
            }
            "history" => {
                let activity = id(v, "activity_id")?;
                let db = self.db.lock().unwrap();
                let mut s=db.prepare("SELECT id,at,job_id,kind,detail FROM events WHERE activity_id=? ORDER BY id DESC LIMIT 100").map_err(err)?;
                let events=s.query_map([activity],|r|Ok(json!({"id":r.get::<_,i64>(0)?,"at":r.get::<_,i64>(1)?,"job_id":r.get::<_,Option<i64>>(2)?,"kind":r.get::<_,String>(3)?,"detail":serde_json::from_str::<Value>(&r.get::<_,String>(4)?).unwrap_or(Value::Null)}))).map_err(err)?.collect::<std::result::Result<Vec<_>,_>>().map_err(err)?;
                Ok(json!(events))
            }
            _ => Err("Unknown operation".into()),
        }
    }
}
fn pump<R: Read + Send + 'static>(
    mut input: R,
    sink: Arc<Mutex<(File, usize, bool)>>,
) -> thread::JoinHandle<()> {
    thread::spawn(move || {
        let mut buf = [0u8; 4096];
        while let Ok(n) = input.read(&mut buf) {
            if n == 0 {
                break;
            }
            let mut s = sink.lock().unwrap();
            let take = n.min(LOG_LIMIT.saturating_sub(s.1));
            if take > 0 {
                let _ = s.0.write_all(&buf[..take]);
                s.1 += take;
            }
            if take < n && !s.2 {
                let _ =
                    s.0.write_all(b"\n[Output capped at 1 MiB; remaining output discarded.]\n");
                s.2 = true;
            }
        }
    })
}
#[cfg(target_os = "linux")]
fn presentation_peer(stream: &UnixStream) -> Result<presentation::Principal> {
    use std::os::fd::AsRawFd;
    let mut cred: libc::ucred = unsafe { std::mem::zeroed() };
    let mut len = std::mem::size_of::<libc::ucred>() as libc::socklen_t;
    if unsafe {
        libc::getsockopt(
            stream.as_raw_fd(),
            libc::SOL_SOCKET,
            libc::SO_PEERCRED,
            &mut cred as *mut _ as *mut libc::c_void,
            &mut len,
        )
    } != 0
    {
        return Err("Cannot authenticate presentation peer".into());
    }
    // Include process start time so a reused PID cannot acquire another client's lease.
    let stat = fs::read_to_string(format!("/proc/{}/stat", cred.pid)).map_err(err)?;
    let start = stat
        .rsplit_once(')')
        .and_then(|(_, tail)| tail.split_whitespace().nth(19))
        .ok_or("Cannot authenticate presentation session")?;
    Ok(presentation::Principal {
        uid: cred.uid,
        session: format!("{}:{start}", cred.pid),
    })
}
#[cfg(not(target_os = "linux"))]
fn presentation_peer(_: &UnixStream) -> Result<presentation::Principal> {
    Err("Authenticated presentation IPC requires Linux SO_PEERCRED".into())
}
fn serve(core: Arc<Core>, mut stream: UnixStream) {
    let _ = stream.set_read_timeout(Some(Duration::from_secs(5)));
    let _ = stream.set_write_timeout(Some(Duration::from_secs(5)));
    let mut line = String::new();
    let result = BufReader::new(&stream)
        .take(4 * 1024 * 1024 + 1)
        .read_line(&mut line)
        .map_err(err)
        .and_then(|_| {
            if line.len() > 4 * 1024 * 1024 {
                return Err("Request too large".into());
            }
            let v: Value = serde_json::from_str(&line).map_err(err)?;
            let op = v["op"].as_str().unwrap_or("");
            if op == "catalog.get"
                || [
                    "presentation.",
                    "interaction.",
                    "draft.",
                    "binding.",
                    "outputs.",
                    "host.",
                    "action.",
                ]
                .iter()
                .any(|prefix| op.starts_with(prefix))
            {
                let principal = presentation_peer(&stream)?;
                if op=="action.invoke" {
                    let prepared=presentation_actions::prepare(&mut core.db.lock().unwrap(),&v,&principal)?;
                    match prepared {
                        presentation_actions::Prepared::Cached(receipt)=>Ok(receipt),
                        presentation_actions::Prepared::Run{request_id,job,operation,parameters}=>{
                            let result=if operation=="job.cancel" {core.cancel(&json!({"job_id":job}))} else if operation=="job.read_output" {core.handle(&json!({"op":"log","job_id":job,"offset":parameters["offset"].as_u64().unwrap_or(0)}))} else {
                                let db=core.db.lock().unwrap();
                                db.query_row("SELECT id,activity_id,argv,status,exit_code,created_at,finished_at,error FROM jobs WHERE id=?",[job],job_value).map_err(err)
                            };
                            presentation_actions::finish(&core.db.lock().unwrap(),&principal,&request_id,result,&operation)
                        }
                    }
                } else {presentation::handle(&mut core.db.lock().unwrap(), &v, &principal)}
            } else if line.len() > 65536 {
                Err("Request too large".into())
            } else {
                core.handle(&v)
            }
        });
    let response = match result {
        Ok(v) => json!({"ok":true,"result":v}),
        Err(e) => json!({"ok":false,"error":e}),
    };
    let _ = writeln!(stream, "{response}");
}
fn main() -> std::result::Result<(), Box<dyn std::error::Error>> {
    let root = PathBuf::from(
        std::env::var("AGENT_OS_STATE").unwrap_or("/var/lib/agent-os-runtime".into()),
    );
    let socket = PathBuf::from(
        std::env::var("AGENT_OS_SOCKET").unwrap_or("/run/agent-os/runtime.sock".into()),
    );
    let core = Core::open(root).map_err(std::io::Error::other)?;
    if socket.exists() {
        fs::remove_file(&socket)?;
    }
    let listener = UnixListener::bind(&socket)?;
    fs::set_permissions(&socket, fs::Permissions::from_mode(0o660))?;
    println!(
        "Agent OS core {} listening on {}",
        env!("CARGO_PKG_VERSION"),
        socket.display()
    );
    for stream in listener.incoming() {
        match stream {
            Ok(s) => {
                let c = core.clone();
                thread::spawn(move || serve(c, s));
            }
            Err(e) => eprintln!("accept: {e}"),
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    struct Fixture(PathBuf);
    impl Fixture {
        fn new() -> Self {
            let nonce = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos();
            static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
            loop {
                let sequence = NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                let root = std::env::temp_dir().join(format!(
                    "agent-os-test-{}-{nonce}-{sequence}",
                    std::process::id()
                ));
                match fs::create_dir(&root) {
                    Ok(()) => return Self(root),
                    Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
                    Err(error) => panic!("Create isolated fixture: {error}"),
                }
            }
        }
        fn open(&self) -> Arc<Core> {
            Core::open(self.0.clone()).unwrap()
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    #[test]
    fn log_pages_preserve_unicode_across_every_byte_boundary() {
        let text = "café λ 日本語";
        let bytes = text.as_bytes();
        for boundary in 0..=bytes.len() {
            let (first, consumed) = log_text(&bytes[..boundary], false);
            let (second, end) = log_text(&bytes[consumed..], true);
            assert_eq!(format!("{first}{second}"), text);
            assert_eq!(consumed + end, bytes.len());
        }
        assert_eq!(log_text(&[0xff, 0xe6, 0x97], false), ("�".into(), 1));
        assert_eq!(log_text(&[0xe6, 0x97], true), ("�".into(), 2));
    }
    #[test]
    fn activities_and_history_survive_reopen() {
        let fixture = Fixture::new();
        let core = fixture.open();
        let a = core.create(&json!({"name":"Research"})).unwrap();
        fs::write(
            fixture
                .0
                .join("workspaces")
                .join(a["id"].to_string())
                .join("note"),
            "retained",
        )
        .unwrap();
        drop(core);
        let core = fixture.open();
        assert_eq!(
            core.snapshot().unwrap()["activities"][0]["name"],
            "Research"
        );
        assert_eq!(
            fs::read_to_string(
                fixture
                    .0
                    .join("workspaces")
                    .join(a["id"].to_string())
                    .join("note")
            )
            .unwrap(),
            "retained"
        );
        let events = core
            .handle(&json!({"op":"history","activity_id":a["id"]}))
            .unwrap();
        assert_eq!(events[0]["kind"], "activity.created");
    }

    #[test]
    fn stale_mutations_leave_state_unchanged() {
        let fixture = Fixture::new();
        let core = fixture.open();
        let old = core.snapshot().unwrap()["revision"].clone();
        let a = core.create(&json!({"name":"Current"})).unwrap();
        let before = core.snapshot().unwrap();
        for request in [
            json!({"op":"create","name":"Stale","expected_revision":old}),
            json!({"op":"remove_activity","activity_id":a["id"],"expected_revision":old}),
            json!({"op":"run","activity_id":a["id"],"argv":["/bin/true"],"expected_revision":old}),
        ] {
            assert!(core.handle(&request).unwrap_err().contains("State changed"));
        }
        assert_eq!(core.snapshot().unwrap(), before);
    }

    #[test]
    fn removing_an_activity_preserves_files_and_can_be_reversed() {
        let fixture = Fixture::new();
        let core = fixture.open();
        let a = core.create(&json!({"name":"Keep"})).unwrap();
        let note = fixture
            .0
            .join("workspaces")
            .join(a["id"].to_string())
            .join("note");
        fs::write(&note, "work").unwrap();
        core.remove_activity(&json!({"activity_id":a["id"]}), false)
            .unwrap();
        assert!(core.snapshot().unwrap()["activities"]
            .as_array()
            .unwrap()
            .is_empty());
        assert!(core
            .run(&json!({"activity_id":a["id"],"argv":["/bin/true"]}))
            .is_err());
        assert_eq!(fs::read_to_string(&note).unwrap(), "work");
        core.remove_activity(&json!({"activity_id":a["id"]}), true)
            .unwrap();
        assert_eq!(core.snapshot().unwrap()["activities"][0]["id"], a["id"]);
    }

    #[test]
    fn restart_marks_unfinished_jobs_without_replaying_them() {
        let fixture = Fixture::new();
        let core = fixture.open();
        let a = core.create(&json!({"name":"Restart"})).unwrap();
        {
            let db = core.db.lock().unwrap();
            for status in ["starting", "running", "cancelling", "succeeded"] {
                db.execute(
                    "INSERT INTO jobs(activity_id,argv,status,created_at) VALUES(?,?,?,?)",
                    params![
                        a["id"].as_i64().unwrap(),
                        "[\"/does/not/exist\"]",
                        status,
                        now()
                    ],
                )
                .unwrap();
            }
        }
        drop(core);
        let core = fixture.open();
        let snapshot = core.snapshot().unwrap();
        let jobs = snapshot["jobs"].as_array().unwrap();
        assert_eq!(
            jobs.iter().filter(|j| j["status"] == "interrupted").count(),
            3
        );
        assert_eq!(
            jobs.iter().filter(|j| j["status"] == "succeeded").count(),
            1
        );
        let events = core
            .handle(&json!({"op":"history","activity_id":a["id"]}))
            .unwrap();
        assert_eq!(
            events
                .as_array()
                .unwrap()
                .iter()
                .filter(|e| e["kind"] == "job.interrupted")
                .count(),
            3
        );
        assert!(core.active.lock().unwrap().is_empty());
    }

    #[test]
    fn invalid_commands_create_no_jobs() {
        let fixture = Fixture::new();
        let core = fixture.open();
        let a = core.create(&json!({"name":"Validation"})).unwrap();
        for argv in [
            json!([]),
            json!([""]),
            json!(["/bin/echo", 1]),
            json!(["/bin/echo", "bad\u{0}argument"]),
        ] {
            assert!(core
                .run(&json!({"activity_id":a["id"],"argv":argv}))
                .is_err());
        }
        assert!(core.snapshot().unwrap()["jobs"]
            .as_array()
            .unwrap()
            .is_empty());
    }
    #[cfg(target_os = "linux")]
    fn finish(core: &Arc<Core>, job: i64) -> Value {
        let deadline = Instant::now() + Duration::from_secs(5);
        loop {
            let snapshot = core.snapshot().unwrap();
            let row = snapshot["jobs"]
                .as_array()
                .unwrap()
                .iter()
                .find(|j| j["id"] == job)
                .unwrap()
                .clone();
            if !["starting", "running", "cancelling"].contains(&row["status"].as_str().unwrap()) {
                return row;
            }
            assert!(Instant::now() < deadline, "job did not finish: {row}");
            thread::sleep(Duration::from_millis(20));
        }
    }

    #[test]
    #[cfg(target_os = "linux")]
    fn execution_records_real_exit_output_and_spawn_failure() {
        let fixture = Fixture::new();
        let core = fixture.open();
        let a = core.create(&json!({"name":"Execution"})).unwrap();
        let job = core
            .run(&json!({"activity_id":a["id"],"argv":["/bin/sh","-c","echo observed; exit 7"]}))
            .unwrap()["id"]
            .as_i64()
            .unwrap();
        let result = finish(&core, job);
        assert_eq!(result["status"], "failed");
        assert_eq!(result["exit_code"], 7);
        assert!(
            fs::read_to_string(fixture.0.join("logs").join(format!("{job}.log")))
                .unwrap()
                .contains("observed")
        );
        let missing = core
            .run(&json!({"activity_id":a["id"],"argv":["/does/not/exist"]}))
            .unwrap()["id"]
            .as_i64()
            .unwrap();
        let result = finish(&core, missing);
        assert_eq!(result["status"], "failed");
        assert!(result["error"].is_string());
    }

    #[test]
    #[cfg(target_os = "linux")]
    fn cancellation_is_idempotent_and_finishes_the_job() {
        let fixture = Fixture::new();
        let core = fixture.open();
        let a = core.create(&json!({"name":"Cancellation"})).unwrap();
        let job = core
            .run(&json!({"activity_id":a["id"],"argv":["/bin/sleep","60"]}))
            .unwrap()["id"]
            .as_i64()
            .unwrap();
        core.cancel(&json!({"job_id":job})).unwrap();
        assert_eq!(finish(&core, job)["status"], "cancelled");
        assert_eq!(
            core.cancel(&json!({"job_id":job})).unwrap()["status"],
            "cancelled"
        );
    }
}
