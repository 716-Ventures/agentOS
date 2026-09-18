# Jev's role

Ling handles planning and dialogue. Jev performs runtime structured risk assessment
of actions submitted to the broker; deterministic broker code validates results
and enforces automatic execution versus confirmation. See EFFECTS.md.

The active path is broker.py → assess_action.py (credential-isolated subprocess)
→ jev.evaluate_action. Assessments include exact argv, scope, working directory,
process lifetime and explicitly untrusted supporting evidence. They are recorded
on the job policy. There is no command-specific server exception.

Legacy jev.review remains for historical fixtures; it is not the execution gate.
