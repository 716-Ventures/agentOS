//! Microphone capture is local, cancellable and never submits a transcript.
use super::*;
use std::{io::Read, thread};
#[derive(Clone, Default)]
pub struct State {
    pub phase: String,
    pub context: Value,
    pub token: Option<String>,
    pub text: Option<String>,
    pub error: Option<String>,
    epoch: u64,
}
#[derive(Clone)]
pub struct Voice {
    pub state: Arc<Mutex<State>>,
}
fn endpoint() -> PathBuf {
    std::env::var("AGENT_OS_VOICE_SOCKET")
        .unwrap_or_else(|_| "/run/agent-os-voice/api.sock".into())
        .into()
}
fn call(value: Value) -> Result<Value, String> {
    transport::request_timeout(&endpoint(), &value, Duration::from_secs(50))
}
impl Voice {
    pub fn new() -> Self {
        Self {
            state: Arc::new(Mutex::new(State {
                phase: "idle".into(),
                ..State::default()
            })),
        }
    }
    pub fn start(&self, mut context: Value) {
        let epoch = {
            let mut state = self.state.lock().unwrap();
            if state.phase != "idle" {
                return;
            }
            state.epoch += 1;
            state.phase = "starting".into();
            state.error = None;
            state.epoch
        };
        let current = self.state.clone();
        thread::spawn(move || {
            let result = (|| {
                let mut bytes = [0u8; 16];
                std::fs::File::open("/dev/urandom")
                    .and_then(|mut f| f.read_exact(&mut bytes))
                    .map_err(|e| e.to_string())?;
                context["input_id"] =
                    json!(bytes.iter().map(|b| format!("{b:02x}")).collect::<String>());
                context["captured_at"] = json!(SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .unwrap_or_default()
                    .as_secs_f64());
                context["modality"] = json!("voice");
                let broker: PathBuf = std::env::var("AGENT_OS_BROKER_SOCKET")
                    .unwrap_or_else(|_| "/run/agent-os-broker/api.sock".into())
                    .into();
                context["expected_generation"] = transport::request(
                    &broker,
                    &json!({"op":"activity_state","activity":context["activity_id"]}),
                )?["generation"]
                    .clone();
                call(json!({"op":"capture.start"}))
            })();
            let mut state = current.lock().unwrap();
            match result {
                Ok(value) => {
                    let token = value["token"].as_str().unwrap_or("").to_string();
                    if epoch != state.epoch {
                        drop(state);
                        let _ = call(json!({"op":"cancel","token":token}));
                    } else {
                        state.phase = "recording".into();
                        state.context = context;
                        state.token = Some(token);
                    }
                }
                Err(error) => {
                    if epoch == state.epoch {
                        state.phase = "error".into();
                        state.error = Some(error);
                    }
                }
            }
        });
    }
    pub fn finish(&self) {
        let (epoch, token) = {
            let mut state = self.state.lock().unwrap();
            if state.phase != "recording" {
                return;
            }
            state.phase = "transcribing".into();
            (state.epoch, state.token.clone())
        };
        let current = self.state.clone();
        thread::spawn(move || {
            let result = call(json!({"op":"capture.finish","token":token}));
            let mut state = current.lock().unwrap();
            if state.epoch != epoch {
                return;
            }
            match result {
                Ok(value) => {
                    state.phase = "review".into();
                    state.text = Some(value["text"].as_str().unwrap_or("").into());
                }
                Err(error) => {
                    state.phase = "error".into();
                    state.error = Some(error);
                }
            }
        });
    }
    pub fn cancel(&self) {
        let token = {
            let mut state = self.state.lock().unwrap();
            state.epoch += 1;
            let token = state.token.take();
            state.phase = "idle".into();
            state.text = None;
            state.error = None;
            state.context = Value::Null;
            token
        };
        if let Some(token) = token {
            thread::spawn(move || {
                let _ = call(json!({"op":"cancel","token":token}));
            });
        }
    }
    pub fn consume(&self) -> Option<Value> {
        let mut state = self.state.lock().unwrap();
        if state.phase != "review" {
            return None;
        }
        state.phase = "idle".into();
        state.token = None;
        state.text = None;
        Some(state.context.take())
    }
}
