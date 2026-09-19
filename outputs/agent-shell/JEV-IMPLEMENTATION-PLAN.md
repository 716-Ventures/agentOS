# Jev integration plan

**Scope of delivery:** The delivery status below covers the current agent-loop integration. Additional native presentation uses are specified in the [windowing architecture](../agent-os-windowing-specification.md#10-jev-and-the-reasoning-model) and are future implementation work.

## Principle

Ling investigates, invents plans and commands, writes and communicates. Jev answers bounded questions against supplied evidence. Code validates answers, enforces authorization, preserves state and executes. The OS remains the workspace; no subsystem recipes or new application-specific command allowlists.

## Implementation sequence and acceptance criteria

1. **Shared decision API.** Pin Jev 1.13.0; validate Choice, Score and Noul responses, retain full distributions, omit suspected secrets, bound state and calls, and record latency and usage by decision purpose. Invalid/unavailable answers explicitly fall back without granting authority.
2. **Relevant context.** Rank durable memories and skills with Score. Select older complete exchanges for relevance while preserving recent exchanges and all original user requests in the selected recent window. Persist full conversation separately from the selected model context; selection never deletes history or turns memory into permission.
3. **General decision tool.** Let the planner construct fresh options from observed state and ask Jev to select among them. Results are advisory, never executable commands or authorization. This supports resource, tool, strategy and skill selection without hardcoded workflows.
4. **Recovery.** Supply live job state at turn start. After failed, blocked or repeated actions, batch recovery and progress judgments so the planner can inspect, adapt, wait or request genuinely missing input. The planner generates the actual next action; code retains bounded retries.
5. **Completion.** Independently assess whether the proposed answer is supported by observed results and whether it misrepresents unfinished work. Permit bounded verification/correction rounds. Honest partial or blocked reports are valid; unsupported claims cannot silently become verified success.
6. **Learning quality.** Assess proposed memories/skills against current user instructions and observed results for support, durability and credentials. Preserve user preferences; reject unsupported claimed observations and secrets. Revisions remain reversible and no memory grants authority.
7. **Action assessment.** Preserve separate risk, task-fit and authorization questions, retain distributions and explicit version/threshold metadata. Treat existing thresholds as provisional, not measured accuracy. Build a labeled consent/risk evaluation set and report false approvals and redundant gates; never silently tune thresholds to one example.
8. **Validation and rollout.** Offline tests for malformed output, fallbacks, budgets, context integrity, correction limits and memory checks; read-only live Jev evaluation and live agent smoke tests in the VM. Deploy changed services without resetting activities. Commit source, plan and results with chrisjdavis.

## Budget and measurement

Per task, bound advisory decision calls and serialized input in addition to existing planner action/round limits. Retain decision-purpose counts, latency, reported token usage and fallback reasons in the private task trace. Existing provider telemetry counts actual HTTP attempts. No invented dollar total: billing and per-task cross-process cost accounting require provider price data and request correlation and are not represented as implemented here.

## Guardrails on scope

Do not replace open-ended planning with a fixed task router. Do not automate model switching without measured quality and an explicitly configured model pool. Do not delete context on Jev's advice. Do not cache action authorization across changed system state. Provider failure is not evidence that a request is outside scope. Confidence thresholds require ongoing labeled evaluation, including withheld examples, before any claim of calibration.

## Delivery status

All eight implementation stages above are implemented and exercised. The offline suite has 74 passing tests, including invalid probability rejection, bounded retries, context integrity, memory rejection, failure recovery and continuation of unfinished work. Live regression findings and their limitations are recorded in [tests/results/README.md](tests/results/README.md). Per-task advisory metrics are available in the private trace; actual provider aggregates remain in the existing Models panel. No new subsystem-specific execution recipes were added.
