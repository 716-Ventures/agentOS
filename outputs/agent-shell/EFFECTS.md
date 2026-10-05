# Runtime effects assessment

The broker no longer requires commands to appear in an allowlist. Every execution
is evaluated against the actual argv, scope, working directory and lifetime.
Deterministic hazard checks first catch obvious destructive/disruptive commands.
Other operations are submitted to Jev under the credential-isolated assistant
identity. Ling plans work; it cannot submit its own safety verdict.

Jev returns validated risk, task-fit and authorization choices. Routine risk
requires confidence at least 0.8. For an agent request, task_fit must also be
aligned with confidence at least 0.8. A beyond-request classification returns
outside_request without a job. Uncertain alignment or missing/invalid confidence
cannot authorize execution. Direct operator commands without current_request
still require effect assessment.

Harmful effects require a matching current instruction with confident alignment
and explicit authorization (at least 0.6 authorization confidence), or local
review of the exact proposal. Known hazards cannot be waived merely by a routine
risk classification. Uncertain, low-confidence, unavailable or malformed
assessments require inspection; request_confirmation creates a review proposal
when uncertainty remains. Unknown command names alone do not cause refusal.

These are probabilistic assessments plus deterministic enforcement, not a proof
that arbitrary programs are safe. The confidence threshold is an operational
policy, not a calibrated safety probability. Shell text, purpose, knowledge and
supplied evidence are untrusted data. Known hazard gates require matching contextual authorization or local review;
a routine risk label, claimed purpose or saved skill cannot waive them. All agent execution uses real root authority on the Linux guest and is assessed as such. Activities are organizational working directories, not filesystem or privilege boundaries. Legacy workspace scope is normalized to system; old restricted proposals must be reassessed before approval. Package installs
retain the no-removal guard when applicable.

Processes have explicit working directories and foreground/background lifetimes.
Foreground timeout_seconds is at most 600. Background lifetime_seconds defaults
to 86400 and can be shortened; foreground timeout does not kill background jobs.
Identical active background requests in an activity reuse the running job.
Broker restart currently interrupts managed jobs; it does not replay them.

No preview-server wrapper, fixed preview port, or preset tunnel was installed.
The agent chooses commands and plans from the scenario. Host access remains a
separate execution boundary: the guest agent does not possess arbitrary macOS
execution authority, and must report required host-side steps honestly.

## OS authority and request alignment

Commands run as root by default, without a read-only system mount or restricted
activity account. cwd may be any existing OS directory. Guarded file operations
work across the filesystem with stale-content checks and backups for replacement;
backups are stored at /var/lib/agent-os-file-backups. Process supervision and
resource/time limits remain. This is system authority, not an isolation claim.

Jev checks task_fit independently of risk, using the current request attached by
the assistant service (not a tool parameter the reasoning model can set). An
unrequested change is returned as outside_request without execution or an approval
proposal. The agent should research and answer an inquiry; an explicit request
to perform work authorizes necessary routine actions, subject to effect checks.
The same broker continues to require confirmation for destructive/harmful effects.

Progress uses actual command purposes and an explicit report_progress tool. The
terminal shows recent progress updates while working. Approval summaries explain
the proposed effect; raw commands remain available in full output and broker logs.

### Contextual user authorization

Explicit user instructions can authorize the exact harmful effect they request. The assistant supplies the current request and recent actual conversation separately from tool arguments, memory and tool evidence. Jev returns typed risk, task-fit and authorization assessments. The broker requires aligned scope and high-confidence explicit consent before waiving a second confirmation; ambiguous or uncovered effects still require review. This is probabilistic language assessment, not a proof of safety. Deterministic hazard indicators remain active. Authorization is recorded against the exact argv and cwd, and never becomes standing permission. Identical pending requests (activity, argv, cwd, authority, lifetime and background mode) reuse one operation; duplicate pending copies are superseded.
