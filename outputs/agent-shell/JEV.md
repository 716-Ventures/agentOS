# Jev decision layer

**Future native presentation:** [Windowing specification §10](../agent-os-windowing-specification.md#10-jev-and-the-reasoning-model) extends this division of responsibilities to referent selection, component candidates and arrangement choices. These graphical uses are specified, not deployed. Jev remains probabilistic; deterministic code validates documents and enforces authority, revisions and interaction ownership.

The implementation plan is in [JEV-IMPLEMENTATION-PLAN.md](JEV-IMPLEMENTATION-PLAN.md). Jev is pinned to `jev-1.13.0`. Ling remains responsible for research, open-ended planning, commands, writing and conversation. Jev supplies probabilistic typed judgments; deterministic code validates results and enforces lifecycle and authorization rules.

## Integrated uses

- **Actions:** risk, request alignment and explicit contextual authorization are evaluated together. Full probabilities, model identity and provisional thresholds are retained in the broker record. Provider failure is not reported as a user request mismatch.
- **Memory and skills:** Score ranks relevant entries; explicit user preferences are retained. This selects working context without deleting stored knowledge.
- **Conversation context:** Score selects older complete exchanges from the last 20; the last two exchanges and original requests in that window remain available. Entire tool-call/result groups are retained or omitted together. The full conversation is saved, and `conversation_read` retrieves earlier exchanges. History deleted by older releases cannot be recovered by this change.
- **Dynamic choices:** `choose_next` lets the planner supply 2–32 options from current evidence. Jev chooses among them or `none_of_these`. A selection is advice, never executable output or authorization.
- **Recovery and progress:** After failures, review requirements or repeated commands, Choice recommends inspect/adapt/wait/human/continue, while Noul assesses whether observations show progress. The planner works out the next concrete action.
- **Completion:** Choice independently evaluates grounding, outcome and whether work should continue. Unsupported or low-confidence grounding judgments receive at most two verification/correction rounds, then an honest unverified report. Provider failure is disclosed. This is an additional model check, not a proof; actual system observations remain essential.
- **Learning:** Choice checks the basis of proposed memories; Noul checks durability and sensitive content. Unsupported, transient, sensitive or unavailable assessments do not write knowledge. A completion-stage learning signal can remind the planner once to preserve useful learning.

## Budgets, failure behavior and observability

`decisions.py` validates Choice distributions, Score ranges/weighted values and Noul probabilities. Missing fields, NaN, booleans posing as numbers, unknown selections and invalid distributions fail closed. Credential-pattern and input-size checks run before requests; these are heuristic filters, not a comprehensive secret detector.

Advisory judgments have per-task caps of 12 calls and 300,000 serialized input characters. Each provider payload is at most 100,000 characters. Advisory evidence excerpts are explicitly marked when truncated. The broker's action checks are separate and remain bounded by the agent's tool budget; they do not borrow cached approvals. HTTP calls have deadlines.

Private task traces include decision purpose, probabilities, model, latency, reported usage, fallback reason and aggregate advisory counts, plus final verification status. The Models panel includes all actual provider requests. Dollar accounting and cross-process per-task billing totals are not implemented; reported token counts are not billing guarantees.

## Evaluation

Offline: `python3 -m unittest discover -s tests -p '*_test.py'`.

Read-only, billable live evaluation inside the configured guest:

```sh
sudo runuser -u agentos-ai -g agentos -G agentos-ai -- python3 tests/evaluate_jev.py --live
```

This sends hypothetical fixture commands to Jev and **never executes them**. It reports classification mismatches, false consent and redundant gates. Grounding and learning support currently require confidence of at least 0.6; these are provisional operating thresholds, not accuracy guarantees. The initial 12-case regression set is too small to claim calibrated accuracy. Preserve difficult cases and add withheld examples before changing thresholds.

References: [primitives](https://docs.typesafe.ai/introduction), [confidence](https://docs.typesafe.ai/confidence), [Choice](https://docs.typesafe.ai/primitives/choice), [Score](https://docs.typesafe.ai/primitives/score).
