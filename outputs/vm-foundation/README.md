# Agent OS — bootable Linux development foundation

This is the first full-system milestone: a complete ARM64 Linux guest with UEFI boot, its own kernel, systemd, persistent storage, networking, login, and a small boot-record service. The upstream base is Debian 13, pinned to build `20260914-2601` and its published SHA-512 checksum.

**The running image now also includes M0.1: the activity and job environment.** Run `agent-os` inside the guest or use the [Agent launcher](../agent-shell/Open%20Agent.command). See the [agent-shell instructions](../agent-shell/README.md). The separately deployed runtime now includes Gateway reasoning and Jev assessments; offline English voice capture, deliberate review, grounding and cancellation are implemented and fixture-verified; physical speech quality remains unqualified. `vm.py prepare` builds the M0 foundation; `reproduce.py` provisions and verifies the current runtime on it. Debian identity is retained; current guest build metadata lives in `/etc/agent-os/release.json`.

For a fresh build with runtime dependencies, installation recovery and automated acceptance, follow [Rebuild and verify agentOS](REPRODUCING.md).

## Use the VM already built here

UTM is the development VM platform. The verified guest uses UTM’s QEMU backend with Apple Hypervisor Framework acceleration, accelerated VirtIO graphics, and Intel HDA audio. Runtime files are excluded from Git; inspect `python3 vm.py status` before assuming a guest exists.

- Open **Connect.command** to enter the guest through SSH.
- Open **Console.command** for the guest’s serial console using the PTY exposed by `utmctl attach`; press **Ctrl-]** to detach. The UTM window also provides display and serial access.
- For serial login, use the account and generated password in `runtime/console-credentials.txt`.
- If stopped, open **Start.command** to start the VM and enter it.

Use `AGENT_OS_VM_RUNTIME` and `AGENT_OS_VM_SSH_PORT` together to select an alternate guest for `vm.py`, deployment and terminal tests. The bundle UUID and forwarded port are checked before operations so lifecycle controls and SSH cannot silently select different guests.

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
| `runtime/agentOS.utm/` | UTM bundle: standalone guest disk, seed ISO, firmware state, display/audio configuration |
| `runtime/utm.json` | UUID and path of the active UTM bundle; the migrated verification guest retains its existing bundle name |
| `runtime/seed.iso` | First-boot account and guest configuration |
| `runtime/build.json` | Original foundation identity; inspect guest release metadata after deployments |
| `image-lock.json` | Pinned upstream URL, digest, resources, and SSH port |
| `utm-template.plist` | UTM-generated configuration structure, with instance identity supplied by the builder |
| `guest/` | Boot-record service and diagnostic command sources |
| `runtime/foundation-verification.json` | Lifecycle evidence for the selected guest |
| `runtime/reproduction.json` | Complete provisioning and acceptance results for the selected guest |

The VM has 4 vCPUs and 4 GB RAM and forwards host `127.0.0.1:22220` to guest SSH. UTM manages its bundled QEMU, UEFI and firmware variables. Graphics use `virtio-gpu-gl-pci`; audio uses `intel-hda`. Outbound networking uses emulated NAT. Host directory sharing and clipboard sharing are disabled. No physical disks are passed through.

The development account has passwordless sudo inside this guest. SSH accepts the locally generated key, not passwords; root SSH login is disabled. The serial-console password is generated locally. Runtime files contain credentials and machine identity: do not publish or distribute `runtime/` as a general release image. This directory is excluded by the supplied `.gitignore`.

## Reproduce the build

Requirements: Apple silicon macOS, Python 3, UTM, Homebrew `qemu-img` (provided by QEMU), OpenSSL 3, and `hdiutil`. Verified with UTM 4.7.5 on macOS 27.0.1 / M2 Ultra. UTM runs its own bundled QEMU; Homebrew QEMU is used only for disk preparation.

From a fresh checkout without `runtime/`:

```sh
brew install --cask utm
brew install qemu openssl@3
python3 vm.py prepare
```

Open the printed `.utm` bundle once in UTM to register it. Registration is a UTM application step; `utmctl` operates registered machines. Then:

```sh
python3 vm.py start
python3 vm.py wait --seconds 60
python3 verify.py
```

`start --hide` runs without showing the display window. For an existing stopped guest made by the earlier runner, `python3 vm.py bundle` moves its disk into a UTM bundle and retains its seed and SSH identity. Stop the old runner first. The current migration used a verified copy and preserved the original disk; `runtime/utm.json` selects the authoritative UTM guest.

Alternatively, reuse a downloaded base:

```sh
python3 vm.py prepare --base /absolute/path/to/debian-base.qcow2
```

The builder verifies the pinned digest before conversion. It creates a standalone disk rather than a fragile backing-file chain. First-boot configuration is carried on a NoCloud seed ISO. It does not install unpinned packages during provisioning. The base is checked against Debian's published checksum over HTTPS; no detached-signature verification was performed.

This is a reproducible provisioning recipe, not a claim of bit-for-bit image reproducibility: credentials, host keys, instance IDs, timestamps, and machine state are intentionally instance-specific. UTM and its bundled firmware/QEMU versions also affect reproducibility. Preserve the tested host tool versions when comparing builds. `prepare` refuses to overwrite an existing guest disk.

## Verification

`verify.py` checks SSH login, the ARM64 kernel, systemd PID 1, ext4 root, cloud-init completion, system health, DNS, outbound HTTPS, and service restart. It writes a random test marker in the guest, reboots it, verifies persistence, powers it off, starts it again, and verifies persistence and new boot IDs. It leaves the VM running and writes `runtime/foundation-verification.json` for the selected guest.

This test intentionally restarts **this development VM**. Save guest work before rerunning it. The boot-record service records each boot once even when restarted within a boot.

Serial-console password login was additionally exercised during initial validation. The guest's ordinary shell provides recovery access independent of future model services.

UTM platform verification on 2026-10-05 passed UEFI boot, SSH, systemd health, guest reboot, graceful poweroff/cold start, and persistent data. Weston ran on the DRM backend with the GL renderer reporting `virgl (ANGLE (Apple, Apple M2 Ultra, OpenGL 4.1 Metal - 91.7))`. Its desktop and terminal rendered in the UTM window; pointer and keyboard events reached the guest. Rapid synthetic typing through UI automation dropped characters, so automated tests should use SSH rather than simulated typing.

ALSA enumerated capture/playback devices and completed two-second 48 kHz stereo capture and silent playback streams. This verifies guest audio plumbing, **not microphone signal quality, audible speaker routing, or end-to-end voice**. Host microphone permission and a real speech/playback check remain part of voice acceptance. Accelerated graphics remain an experimental UTM feature; the current tests establish feasibility, not production desktop performance.

Weston, Mesa, Wayland utilities, ALSA utilities, seatd, qemu-guest-agent and build tools were installed in the verification guest for these checks. They are now captured by the pinned runtime dependency recipe used by `reproduce.py`; the M0 cloud-init seed itself remains minimal. The transient Weston test session is not an implemented agentOS desktop. The separate agent-shell deployment and tests verify the installed runtime. Live model/provider behavior, OS updates/rollback and physical hardware remain separate acceptance work.

## Next implementation milestone

The environment core and terminal client are now installed: persistent activities, supervised jobs, action records, and cancellation. Gateway reasoning, general execution and Jev decisions are now implemented in agent-shell. Offline English voice capture, deliberate review, grounding and cancellation are implemented. Physical speech quality and the complete native desktop qualification remain required before declaring the first usable release. The system image and lifecycle tests remain the acceptance environment throughout.

## Sources

- [Debian cloud images](https://cloud.debian.org/images/cloud/trixie/)
- [QEMU ARM virtual platform](https://www.qemu.org/docs/master/system/arm/virt)
- [cloud-init NoCloud datasource](https://docs.cloud-init.io/en/latest/reference/datasources/nocloud.html)

- [UTM scripting and CLI](https://docs.getutm.app/scripting/scripting/)
- [UTM display configuration](https://docs.getutm.app/settings-qemu/devices/display/)
- [UTM audio configuration](https://docs.getutm.app/settings-qemu/devices/sound/)
