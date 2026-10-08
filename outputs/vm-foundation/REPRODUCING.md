# Rebuild and verify agentOS

The reproducible development recipe combines the SHA-512-pinned Debian ARM64 base, the checked-in UTM configuration, a dated Debian package snapshot, Cargo.lock, and the runtime source. It captures the build tools plus Weston, Mesa, ALSA, seatd and QEMU guest-agent packages previously installed by hand. Provider keys and a graphical desktop application are not bundled.

Run from the repository root on an Apple silicon Mac with UTM, Python 3, Homebrew `qemu-img`, OpenSSL 3 and `hdiutil` available. Use a separate runtime directory and unused SSH port so the existing guest keeps its disk and identity:

```sh
python3 outputs/vm-foundation/reproduce.py \
  --runtime outputs/vm-foundation/runtime/fresh-verification \
  --ssh-port 22221 --prepare-only \
  --base outputs/vm-foundation/runtime/base.qcow2
```

Omit `--base` to download and verify the pinned base. Existing disks are never overwritten. Open the printed `.utm` bundle once in UTM to register it. This is the one manual registration step: UTM's CLI controls registered guests but has no import command. Then run the full build and acceptance path:

```sh
python3 outputs/vm-foundation/reproduce.py \
  --runtime outputs/vm-foundation/runtime/fresh-verification \
  --ssh-port 22221
```

This command provisions dependencies, compiles and installs the runtime, runs the Python and Rust suites and real guest/terminal checks, kills the installer at two activation checkpoints, recovers, reboots and cold-starts the VM, checks persisted state, and repeats installation. It always requests orderly guest shutdown, including after failure. UTM can be closed once shutdown finishes. Do not run this acceptance path on a guest with ongoing work: it deliberately restarts services and the VM.

Logs, package versions, host tool versions, release identity and acceptance results are saved in that guest's runtime directory. `reproduction.json` reports pass only after all checks complete; shutdown failures mark the run failed. Generated disks, SSH identities, console credentials and reports remain outside version control.

## Dependency inputs

`outputs/agent-shell/dependencies.json` selects Debian and Debian Security snapshot `20261006T000000Z` and the required packages. `bootstrap.py` uses isolated APT sources and lists for this invocation, retains Debian archive signature verification, and scopes expiry relaxation to the fixed snapshot. Normal guest security-update sources are preserved. See the [Debian snapshot instructions](https://snapshot.debian.org/).

The pinned base determines already installed packages; snapshot metadata determines additional dependencies. The complete installed package/version manifest is recorded under `/var/lib/agent-os-install/dependencies.json` and included in each staged runtime release. Existing newer packages are not automatically downgraded. A fresh base is the acceptance environment for reproducibility. Deliberate dependency updates require updating the snapshot/profile and rerunning fresh-guest acceptance.

Cargo builds with `--locked` and verifies registry crate checksums. First provisioning requires access to Debian snapshots and crates.io. Repeated installation skips APT when the dependency profile and installed package versions are unchanged. This is a repeatable provisioning and verification recipe, not a claim that VM disks or binaries are bit-for-bit reproducible: machine identities, credentials, boot state and compiler/environment details can differ.

## Runtime installation and recovery

`deploy.py` stages an exact source tree, retains the previous copied tree and reuses its Cargo build cache, then invokes `install.sh`; the same guest-side script performs dependency setup, the locked Cargo build, and runtime activation. It can now install on the clean foundation without manual package commands.

The installer validates Python syntax and the ARM64 Linux executable, then stages a complete content-addressed release under `/usr/local/lib/agent-os/releases/<SHA256>`. It verifies every staged file before stopping services. `/usr/local/lib/agent-os/current` selects the active release atomically; stable command and service paths refer to that release. Prior releases are retained. Existing installations with a real services directory retain that directory as a legacy copy during migration.

The root-only `/var/lib/agent-os-install/transaction.json` records staged, stopped, activated and complete phases. Installation is serialized by a file lock. After an interruption, use the ordinary guest shell:

```sh
sudo python3 /usr/local/lib/agent-os/install-recovery.py --recover
```

Recovery validates the staged manifest, finishes activation, starts all runtime services and checks their sockets plus the core API before recording completion. It needs neither a source checkout nor another compilation. Rerunning `install.sh` also completes an unfinished transaction before installing the newly built source. If compilation was interrupted before staging/recovery-script creation, rerun `install.sh` from the copied source. APT/dpkg interruptions are outside the staged runtime transaction; complete Debian package-manager recovery (starting with `sudo dpkg --configure -a`) before retrying dependency setup. Health failures retain the journal for inspection and retry.

Recovery completes the recorded installation; it does not provide automatic OS/package rollback or restore arbitrary command effects. Interrupted runtime jobs are reconciled by the existing supervisors and are not replayed. Activities, logs, layouts, pending proposals, user files and provider configuration are preserved. Provider content, owner and permissions are never rewritten by runtime installation.

## Verified acceptance

The clean UTM guest built on 2026-10-07 used the pinned base and this dependency recipe, without additional package setup. Checks cover local Python/Rust tests; real core, broker, guarded-file, layout and lifecycle behavior; real SSH terminal controls and interactive PTYs (prompts, full-screen curses, resize, Ctrl-C, reconnect, cancellation and restart); forced installer termination at stopped and activated phases; recovery from staged files; retained state and configuration; guest reboot/cold start; and stable release identity on repeated installation.

Live provider inference, microphone/speaker signal quality, graphical application behavior, physical hardware and OS update rollback remain separate acceptance work. Installed graphics/audio packages reproduce the platform prerequisites; they do not constitute an agentOS desktop or voice implementation.
