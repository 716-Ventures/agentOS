//! Opt-in, bounded aggregate rendering diagnostics. No document/input content is recorded.
use serde_json::{json, Value};
use std::{
    cell::RefCell,
    collections::{BTreeMap, VecDeque},
    io::Write,
    os::unix::fs::OpenOptionsExt,
    path::PathBuf,
    time::{Duration, Instant},
};
const SAMPLES: usize = 256;
#[derive(Default)]
struct Samples {
    total: u64,
    discarded: u64,
    sum_ms: f64,
    recent: VecDeque<f64>,
}
impl Samples {
    fn record(&mut self, value: f64) {
        if !value.is_finite() || !(0.0..=60000.0).contains(&value) {
            self.discarded = self.discarded.saturating_add(1);
            return;
        }
        self.total = self.total.saturating_add(1);
        self.sum_ms += value;
        if self.recent.len() == SAMPLES {
            self.recent.pop_front();
        }
        self.recent.push_back(value);
    }
    fn snapshot(&self) -> Value {
        let mut sorted = self.recent.iter().copied().collect::<Vec<_>>();
        sorted.sort_by(f64::total_cmp);
        let percentile = |p: f64| {
            sorted
                .get(((sorted.len() as f64 * p).ceil() as usize).saturating_sub(1))
                .copied()
        };
        json!({"samples_total":self.total,"discarded":self.discarded,"retained":sorted.len(),"mean_all_ms":if self.total>0 {Some(self.sum_ms/self.total as f64)}else{None},"p50_recent_ms":percentile(0.5),"p95_recent_ms":percentile(0.95),"max_recent_ms":sorted.last()})
    }
}
struct Recorder {
    directory: Option<PathBuf>,
    stages: BTreeMap<&'static str, Samples>,
}
impl Recorder {
    fn new() -> Self {
        Self {
            directory: std::env::var_os("AGENT_OS_METRICS_DIR")
                .map(PathBuf::from)
                .filter(|p| p.is_absolute() && p.is_dir()),
            stages: BTreeMap::new(),
        }
    }
    fn record(&mut self, name: &'static str, duration: Duration) {
        if self.directory.is_none() || (!self.stages.contains_key(name) && self.stages.len() >= 8) {
            return;
        }
        self.stages
            .entry(name)
            .or_default()
            .record(duration.as_secs_f64() * 1000.0);
    }
    fn snapshot(&self) -> Value {
        let stages = self
            .stages
            .iter()
            .map(|(name, values)| (*name, values.snapshot()))
            .collect::<BTreeMap<_, _>>();
        json!({"format":1,"pid":std::process::id(),"sample_limit_per_stage":SAMPLES,"stages":stages,"meaning":"CPU reconciliation/render-submit durations; not input-to-display latency or hardware presentation evidence"})
    }
}
impl Drop for Recorder {
    fn drop(&mut self) {
        let Some(directory) = &self.directory else {
            return;
        };
        if self.stages.is_empty() {
            return;
        }
        let pid = std::process::id();
        let temporary = directory.join(format!(
            ".render-{pid}-{}.tmp",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_nanos()
        ));
        let result = (|| -> std::io::Result<()> {
            let mut file = std::fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .mode(0o600)
                .open(&temporary)?;
            file.write_all(self.snapshot().to_string().as_bytes())?;
            std::fs::rename(&temporary, directory.join(format!("render-{pid}.json")))
        })();
        if let Err(error) = result {
            let _ = std::fs::remove_file(temporary);
            eprintln!("Rendering diagnostics unavailable: {error}");
        }
    }
}
thread_local! {static RECORDER:RefCell<Recorder>=RefCell::new(Recorder::new());}
pub struct Span {
    name: &'static str,
    started: Option<Instant>,
}
impl Span {
    pub fn new(name: &'static str) -> Self {
        Self {
            name,
            started: RECORDER.with(|r| r.borrow().directory.as_ref().map(|_| Instant::now())),
        }
    }
}
impl Drop for Span {
    fn drop(&mut self) {
        if let Some(started) = self.started {
            RECORDER.with(|r| r.borrow_mut().record(self.name, started.elapsed()));
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn percentiles_are_bounded_recent_samples_and_cumulative_mean_is_explicit() {
        let mut values = Samples::default();
        for value in 1..=300 {
            values.record(value as f64);
        }
        values.record(f64::NAN);
        values.record(60001.0);
        let report = values.snapshot();
        assert_eq!(report["samples_total"], 300);
        assert_eq!(report["retained"], 256);
        assert_eq!(report["discarded"], 2);
        assert_eq!(report["p95_recent_ms"], 288.0);
        assert_eq!(report["max_recent_ms"], 300.0);
        assert_eq!(report["mean_all_ms"], 150.5);
    }
    #[test]
    fn disabled_diagnostics_do_not_collect_stages_or_files() {
        let mut recorder = Recorder {
            directory: None,
            stages: BTreeMap::new(),
        };
        recorder.record("fixture", Duration::from_millis(1));
        assert!(recorder.stages.is_empty());
    }
}
