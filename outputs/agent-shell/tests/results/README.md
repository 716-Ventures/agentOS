# Live Jev regression results — 2026-09-18

`jev-actions-2026-09-18.json` records 12 hypothetical action assessments against pinned `jev-1.13.0`. No fixture command was executed. Result: zero false-consent decisions, zero redundant gates on the two explicit removal cases, and four cases with at least one descriptive classification mismatch. In particular, ambiguous consent sometimes received the `explicit` label at low confidence; the combined task-fit/authorization checks did not permit execution. This is a small development regression set, not a calibration dataset or a guarantee of safety.

Separate live primitive checks in the configured guest verified:

- Score retained an explicit preference and relevant kernel-inspection knowledge while dropping unrelated baking knowledge.
- Dynamic Choice selected the observed kernel-inspection command, retaining all probabilities and advisory-only status.
- Completion marked a claimed successful installation contradicted when the observed command failed.
- Recovery recommended adapting/inspecting after a missing-file error, with low progress probability.
- Learning classified a supported kernel observation as low durability, preventing a routine status fact from becoming a permanent skill.
- These five advisory calls reported 2,655 input tokens and 1,663 ms combined HTTP latency, excluding reasoning-model work. This is a single sample, not a performance benchmark.

An end-to-end read-only agent check initially added an unsupported “no upgrades pending” claim after inspecting version strings. Completion instructions were strengthened to check incidental claims and freshness; a direct retest flagged the claim as unsupported (confidence 0.98). A subsequent end-to-end check reported only the freshly observed kernel and Debian version; completion grounding was supported (confidence 0.81), with no fallback. Its two advisory calls reported 6,301 input tokens and 757 ms total HTTP latency, excluding broker assessments and reasoning calls.

The supervised preview server was restored after the broker deployment and returned HTTP 200. Activities and saved conversations were retained.
