# Agent OS — bootable Linux development foundation

This is the first full-system milestone: a complete ARM64 Linux guest with UEFI boot, its own kernel, systemd, persistent storage, networking, login, and a small boot-record service. The upstream base is Debian 13, pinned to build `20260914-2601` and its published SHA-512 checksum.

**The running image now also includes M0.1: the activity and job environment.** Run `agent-os` inside the guest or use the [Agent launcher](../agent-shell/Open%20Agent.command). See the [agent-shell instructions](../agent-shell/README.md). Jev, reasoning models, and voice remain pending. The build recipe in this folder reproduces the M0 foundation; apply the agent-shell deployment afterward to reproduce the current installed functionality. Debian identity is retained; current guest build metadata lives in `/etc/agent-os/release.json`.

## Use the VM already built here

The VM is left running after verification.

- Open **Connect.command** to enter the guest through SSH.
- Open **Console.command** for the guest's actual serial console; press **Ctrl-]** to detach.
- For serial login, use the account and generated password in `runtime/console-credentials.txt`.
- If stopped, open **Start.command** to start the VM and enter it.

From a terminal in this directory:

```sh
python3 vm.py status
python3 vm.py ssh
python3 vm.py console
python3 vm.py reboot
python3 vm.py stop
```

`stop` requests an orderly guest shutdown. Wait until `status` reports stopped before starting again. Leaving an SSH session or detaching the console does not power off the VM.

Inside the guest:

```sh
agent-os-status
systemctl --failed
journalctl -u agent-os-foundation
cat /etc/agent-os/release.json
sudo systemctl poweroff
```

## What was built

| Artifact | Role |
|---|---|
| `runtime/disk.qcow2` | Standalone bootable guest disk; 20 GB virtual capacity, sparse allocation |
| `runtime/uefi-code.fd`, `runtime/uefi-vars.fd` | Firmware and persistent firmware variables |
| `runtime/seed.iso` | First-boot account and guest configuration |
| `runtime/console.log` | Guest boot and serial-console output |
| `runtime/build.json` | Original foundation build identity; inspect guest release metadata for subsequent installations |
| `image-lock.json` | Pinned upstream URL, digest, resources, and SSH port |
| `guest/` | Custom boot-record service and diagnostic command sources |
| `verification.json` | Recorded checks against the running guest |

The VM has 2 vCPUs and 2 GB RAM, uses QEMU with Apple's Hypervisor Framework acceleration, and forwards host `127.0.0.1:22220` to guest SSH. It has outbound networking through QEMU's user-mode network. It has no host directory shares, host Docker socket, or physical disk passthrough.

The development account has passwordless sudo inside this guest. SSH accepts the locally generated key, not passwords; root SSH login is disabled. The serial-console password is generated locally. Runtime files contain credentials and machine identity: do not publish or distribute `runtime/` as a general release image. This directory is excluded by the supplied `.gitignore`.

## Reproduce the build

Requirements: Apple silicon macOS, Python 3, Homebrew QEMU, and `hdiutil`. Tested with QEMU 11.1.1 on macOS 27. Run these from a fresh copy of this directory without `runtime/`:

```sh
brew install qemu
python3 vm.py prepare
python3 vm.py start
python3 vm.py wait --seconds 60
python3 verify.py
```

Alternatively, reuse a downloaded base:

```sh
python3 vm.py prepare --base /absolute/path/to/debian-base.qcow2
```

The builder verifies the pinned digest before conversion. It creates a standalone disk rather than a fragile backing-file chain. First-boot configuration is carried on a NoCloud seed ISO. It does not install unpinned packages during provisioning. The base is checked against Debian's published checksum over HTTPS; no detached-signature verification was performed.

This is a reproducible provisioning recipe, not a claim of bit-for-bit image reproducibility: credentials, host keys, instance IDs, timestamps, and machine state are intentionally instance-specific. Firmware and QEMU versions also affect reproducibility. Preserve the tested host tool versions when comparing builds. `prepare` refuses to overwrite an existing guest disk.

## Verification

`verify.py` checks SSH login, the ARM64 kernel, systemd PID 1, ext4 root, cloud-init completion, system health, DNS, outbound HTTPS, and service restart. It writes a random test marker in the guest, reboots it, verifies persistence, powers it off, starts it again, and verifies persistence and new boot IDs. It leaves the VM running and writes `verification.json`.

This test intentionally restarts **this development VM**. Save guest work before rerunning it. The boot-record service records each boot once even when restarted within a boot.

Serial-console password login was additionally exercised during initial validation. The guest's ordinary shell provides recovery access independent of future model services.

Outside the original M0 validation: microphone/audio devices, agent behavior, Jev, OS update/rollback, installer, physical hardware, graphical compositor, or arbitrary process sandboxing. The separate agent-shell verification covers the subsequently installed activities and job supervisor. The current VM is isolated from the Mac, but its development account deliberately has administrative control over the guest.

## Host installation note

QEMU installed and successfully booted the guest. Homebrew's `glib`, `gnutls`, and `openssl@3` post-install hooks could not complete inside the automation sandbox (`sandbox-exec: sandbox_apply: Operation not permitted`). Finish those hooks in a normal macOS Terminal:

```sh
brew postinstall glib gnutls openssl@3
```

This is a host dependency-installation follow-up, not a guest boot failure. Homebrew installed QEMU and its dependencies and upgraded some existing dependency versions; it did not install UTM.

## Next implementation milestone

The environment core and terminal client are now installed: persistent activities, supervised jobs, action records, and cancellation. Next, integrate scoped Jev decisions and extended reasoning, with voice required before declaring the first usable release. The system image and lifecycle tests remain the acceptance environment throughout.

## Sources

- [Debian cloud images](https://cloud.debian.org/images/cloud/trixie/)
- [QEMU ARM virtual platform](https://www.qemu.org/docs/master/system/arm/virt)
- [cloud-init NoCloud datasource](https://docs.cloud-init.io/en/latest/reference/datasources/nocloud.html)
