# Durable learning

The agent can autonomously list, read, create and revise memory and skills through
knowledge tools. A bounded catalog is supplied on each new request; full entries
can be retrieved as needed. The agent is instructed to retain preferences,
verified environment observations, successful procedures and corrections, and
not credentials, chatter, or unverified claims of success.

Each entry records its kind, title, basis (user_preference / observed / inferred),
source, originating activity, revision, timestamp and reference-only authority.
Basis and source are agent-authored provenance, not an independent truth oracle.
Writes require the current revision. History is retained; archive and restore are
reversible. Knowledge never authorizes a command or bypasses Jev/broker checks.

Inspect from the shell:

    agent-os knowledge
    agent-os knowledge read KEY
    agent-os knowledge history KEY
    agent-os knowledge archive KEY --expected-revision N
    agent-os knowledge restore KEY --revision OLD --expected-revision CURRENT

Ask the agent to correct or revise a memory or skill in conversation. Knowledge
is stored in /var/lib/agent-os-ai/knowledge.json and survives service restarts.
Only a bounded excerpt catalog enters context automatically. Learning updates
are chosen by the agent during work; this is persistent learned context and
procedures, not training new model weights. It does not run a background learner
or guarantee every useful observation is captured.
