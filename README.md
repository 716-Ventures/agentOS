# agentOS

An agent-first operating system built on Linux. The operating system is the agent's workspace: it can inspect the machine, plan and execute requested work, and retain useful knowledge. Explicit user authorization is required for harmful effects that the request does not already cover.

The current prototype is a complete Debian ARM64 virtual machine with a tiling terminal interface, persistent activities, a Rust runtime, and Python services. Ling through Vercel AI Gateway handles reasoning; Jev supplies typed action assessments that the execution broker validates and applies. Voice and a custom graphical desktop are planned.

## Source map

- [Agent runtime, terminal, services and tests](outputs/agent-shell/)
- [Linux VM build and launch tooling](outputs/vm-foundation/)
- [Interactive design prototype](outputs/dark-interaction/)
- [GUI concepts and design assets](outputs/gui-concepts/)
- [White paper](outputs/agentic-operating-system-white-paper.md)
- [Terminal release plan](outputs/terminal-first-release-plan.md)
- [Product principles](PRODUCT.md) and [design direction](DESIGN.md)

Start with the [VM foundation instructions](outputs/vm-foundation/README.md), then the [agent installation and deployment guide](outputs/agent-shell/README.md). Configure provider keys inside the guest using `sudo agent-os-configure`.

VM disks, generated SSH keys, credentials, caches, build products, runtime state and local test captures are excluded from version control. A fresh checkout requires building the VM and configuring its providers.

## Tests

```sh
python3 -m unittest discover -s outputs/agent-shell/tests -p '*_test.py'
cargo test --manifest-path outputs/agent-shell/Cargo.toml
```

Guest integration and terminal tests are under `outputs/agent-shell/tests`; these require the running development VM and can modify its state.

## License

Original agentOS code and documentation are licensed under the [Apache License 2.0](LICENSE). Third-party components and assets retain their own licenses; see [THIRD_PARTY.md](THIRD_PARTY.md). The repository license does not relicense the Linux kernel or Debian packages used to build the guest.
