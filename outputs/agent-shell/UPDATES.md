# Runtime updates and recovery

`install.sh` builds a complete content-addressed runtime before activation. The root installer serializes changes with a file lock, validates the release hash and manifest, records a durable activation journal, stops services, atomically switches the runtime, installs release-specific units, and checks service/core readiness. User and service state stays outside immutable releases. An interrupted activation can be resumed from the staged release without its working source.

From the ordinary Linux rescue shell:

```sh
sudo agent-os-update --list-releases
sudo agent-os-update --recover
sudo agent-os-update --rollback
sudo agent-os-update --rollback RELEASE_ID
sudo agent-os-update --activate RELEASE_ID
sudo agent-os-update --fetch-bundle https://your-release-host/runtime.tar.gz
```

Rollback selects verified installed code, preserves live activities, drafts, credentials, files and external effects, and uses the same recoverable activation journal. Reinstalling the current release or recovering after the switch preserves the original previous-release pointer. Releases must declare the same state contract; incompatible formats are rejected before stopping services. Legacy releases without a contract cannot be rollback targets. A future incompatible schema requires an explicit forward/backward migration implementation and its own tests.

This mechanism covers runtime code and systemd units. Debian packages, kernel, VM disk contents and filesystem effects are not rolled back. Package bootstrap retains its authenticated snapshot profile and never silently downgrades installed packages. Staged releases remain local/root-owned. An administrator can fetch a signed bundle from an explicit HTTPS URL; redirects cannot downgrade HTTPS or add URL credentials. Downloads use private temporary storage, byte/time limits and the same Ed25519, manifest, ARM64 and host-compatibility checks as local bundles. A successful fetch stages the release and prints the explicit activation command; it never restarts services automatically. Provision `/etc/agent-os/update-signing-key.pem` from a separately trusted source, or pass `--trusted-key`. Release hosting and signing-key operations remain deployment responsibilities.

Host unit tests cover staging integrity, compatible rollback, incompatible state refusal, repeated activation, and recovery provenance. `tests/installation_guest.py rollbacks` verifies real systemd service replacement, state preservation and SIGKILL recovery in the development guest. Guest execution remains required before promoting a release image.
