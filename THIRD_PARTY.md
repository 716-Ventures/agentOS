# Third-party licensing

The Apache-2.0 license applies to original agentOS work, not to third-party software or assets with their own terms.

- `outputs/dark-interaction/assets/Commissioner.ttf` is distributed under the SIL Open Font License 1.1. Preserve the accompanying `OFL.txt`, including its copyright notices.
- Rust dependencies resolved through `outputs/agent-shell/Cargo.lock`, including bundled SQLite, retain their upstream licenses and notices.
- The VM build downloads Debian and Linux rather than storing them in this repository. Linux is GPL-2.0-only with its syscall exception; Debian packages retain their individual licenses. Distributing a built image requires satisfying the applicable licenses and source-distribution obligations for the included components.

This file describes license boundaries; it is not a complete license inventory for a built operating-system image.
