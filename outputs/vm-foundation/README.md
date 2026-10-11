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

UTM 4.7.5's stock controller always launches the app hidden, then its VM console path calls `makeMain()`. On this macOS 27.0.1 host that intermittently asserted before QEMU started. Build the pinned controller workaround once (requires Swift/Xcode):

```sh
python3 build_utmctl.py
```

This builds the official v4.7.5 controller sources with two launch changes: remove the unconditional `.andHide` flag, and disable saved-window restoration for a cold app launch using the process argument `-ApplePersistenceIgnoreState YES`. The second change addresses an observed empty scripting library after restoring the app; an explicit launch with this argument restored both existing registered guests without changing their configuration or disks. It does not change persistent app preferences and does not relaunch an already running app. Sources are hash checked, ArgumentParser is revision pinned, and third-party licenses accompany the private binary under `runtime/utmctl-control-v2/`. The installed signed UTM app is retained. All `vm.py` control operations prefer this build and verify its binary digest; without it they use the stock controller. Three guest startup/readiness/orderly-shutdown cycles passed, including repeated cold UTM app launches, with the host locked. This is evidence for the workaround, not a fix to Apple's AppKit itself.

`start` now keeps the library visible by default. `start --hide` explicitly hides only the library, not the VM console. The wrapper checks the observed guest state after a successful CLI exit and never retries an uncertain start automatically. Inspect the selected guest and any owned stalled UTM process before another attempt. The controller behavior is documented in the [official UTM source](https://github.com/utmapp/UTM/blob/v4.7.5/utmctl/UTMCtl.swift).

For an existing stopped guest made by the earlier runner, `python3 vm.py bundle` moves its disk into a UTM bundle and retains its seed and SSH identity. Stop the old runner first. `runtime/utm.json` selects the authoritative UTM guest.

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

UTM status, start and shutdown acknowledgements have bounded 10/30/15-second timeouts. A cold app can briefly answer `Virtual machine not found` before its saved VM list loads. Only that exact read-only lookup error is retried within the same total 10-second status budget; other failures and all lifecycle mutations are not replayed. Empty/unrecognized status replies leave the guest state unknown. A timed-out status is unknown rather than stopped; an uncertain start is never retried automatically. Inspect the selected VM before another start, and retain reproduction failure logs. A responsive status command does not guarantee that UTM can start a VM while the Mac screen is locked.

The October 10 native reproduction passed all 45 checks, including installed systemd PNG preview with model byte denial, the full native rendering/session matrix, direct KMS frames and VT resume, signed graphical staging, interrupted install/rollback recovery and repeat-install/cold-boot state preservation. See `native-verification.json` for the tested archive digest and qualification boundaries. The direct-display probe owns an unused VT in the dedicated development VM and cleans up its exact PAM session scope, including activated accessibility daemons.

The additional cold-app saved-list race is covered by bounded read-only lookup tests and two actual cold app/start/readiness/orderly shutdown cycles; see [UTM startup evidence](utm-startup-verification.json). Neither lookup recovery nor a successful startup cycle guarantees that the underlying AppKit path cannot fail.

The runtime dependency recipe includes Firefox ESR, xdg-utils and desktop-file-utils from the same pinned Debian snapshot. The 49-check reproduction includes native Link → GIO → real Firefox → shared workspace verification with a local HTTP page and disposable profile, followed by explicit browser/window/process cleanup. An additional `browser_links.py --installed` check exercises immutable release binaries. Debian/Mozilla package licenses remain with the installed packages. Remote websites, physical browser input, hardware acceleration and mail account/client setup are outside this check.

Console-only guests use `python3 vm.py start --console-only`, `python3 vm.py status --state-only`, `python3 vm.py console` and `python3 vm.py stop`. These operations still validate the selected bundle UUID and use bounded read-only status lookup before startup; they do not require or change SSH/network configuration. Normal startup and every SSH operation retain exact forwarded-port checks. An uncertain lifecycle outcome is never automatically replayed. The offline image qualification uses this wrapper instead of bypassing startup readiness with a raw controller call.

The complete reproduction closes UTM when it cold-launched the app, after verifying every registered guest is stopped. It identifies the executable and process start time independently of launch arguments and observes its exit. A preexisting UTM app is preserved. An unavailable saved library or a running/unknown guest prevents app termination.


The reproduction matrix includes explicit session-owned Orca normal/logout and compositor-loss checks, plus `direct-display-screen-reader`. The direct reader fixture uses a private home and null speech sink, exercises kernel navigation and learn mode, preserves rescue VT access during full grabs, and rejects unrelated registration and spoofed monitor identities. Ordinary sessions log no speech content. See the targeted evidence in `native-verification.json`; the expanded 67-check matrix passes from clean committed source `2e018ed` at runtime `1889db878666b71ac8b9f0e377ec2d030dab4bb824bebd7ebe5493dc17bee8f2`, including reboot, interrupted installation, rollback, repeat install and exact guest/app shutdown. Helper-crash recovery, human Save reconciliation, restored-source cache invalidation and bounded input-frame preparation are included. The signed v11 distribution retains its distinct image identity.

The trusted on-screen keyboard now passes the complete 68-check UTM reproduction from clean committed source `7b7fcb06aa7fb42f4a0b3ff2b31376085fd6c506` at runtime `212c0bb724b9696bf36024bc7462ee03b1f380194cf8708fdab65296c2e70742`, with kernel pointer typing, physical held-key isolation, workspace restoration, session-owned Orca learn mode and exact guest/app exit. CI run 38134725194 passes. Historical reader timeout and prior complete/image identities remain separately recorded.

Clean source 6695be8 passes all 69 checks at runtime de02fdba74bc2e07cc08590a2e06bb2c36c16b4d71a0bdbbd8c096003e1a3a08, including display zoom, scaled kernel pointer/wheel access, keyboard and reader. Editor p95 is 39 ms idle, 41 ms under two broker CPU jobs and 45 ms rotated, with 60 completed receipts and no discarded/invalid/pending samples. Exact guest/app exit and CI 38136072885 pass. Signed v11 and earlier complete runs retain their identities.

Fresh signed v12 qualification caught a keyboard-height failure at 200% zoom (266 pixels on a 400-pixel logical output). The artifact and failure evidence are preserved. A window-sizing correction passes native dark/light doubled-text/reader profiles and three first-run journeys using replacement binaries on an image copy, with actual 640×200 allocations. The full suite adds a fresh-profile input journey (70 checks). These targeted results do not qualify an unmodified v12 or a new signed image.

Clean source f2e5499 passes all 70 checks at runtime 30e85503131b11d8d73e0acbb8f717563fde6b7c0a8fd3e664206cf08675fb42, including the compositor-owned keyboard height request, per-step zoom bounds, final native allocation capture, fresh-profile kernel input, scaled pointer/wheel access and reader. Editor p95 is 44 ms idle, 40 ms under two broker CPU jobs and 43 ms rotated, with 60 completed receipts and no discarded/invalid/pending samples. Exact guest/app exit and CI 38139410556 pass. Signed v11 and earlier complete runs retain their identities.

Signed candidate-v13 passes fresh-image and loopback-only cold-boot qualification with the exact 70-check runtime `30e85503131b11d8d73e0acbb8f717563fde6b7c0a8fd3e664206cf08675fb42`, including first-run keyboard/zoom and offline reader/zoom. Original development disk/EFI identities and config bytes are restored; the owned guest/app is closed, test credentials removed and unbooted signatures reverified. See `image-verification.json`; failed v12 remains separately preserved.

The reproduction runner now captures UTM application ownership at each initiating controller call, including a controller that launches the app and then fails. Cleanup uses that captured PID/start identity. A replacement app or recycled PID is neither operated nor closed, preexisting apps are preserved, and unverified exit fails the report. Seven isolated ownership regressions and an actual stopped-guest controller-launch/owned-app-exit probe pass; full runtime reproduction remains separate evidence.

Clean source c550d0e passes all 70 runtime checks with 716 UI alpha.35 at 5ce4bab4c7d1931d2ab2c9ab068cb21baecf01397d1414a69a47231ded1a12c2. Editor presentation p95 is 43 ms idle, 42 ms loaded and 44 ms rotated. Launch-boundary UTM ownership and exact guest/app exit pass; private CI 38147114470 and public CI 38146772296 are green. The earlier browser-default pollution failure and baseline restoration are retained. The signed v13 image keeps its separate alpha.32 identity; historical rare focus/geometry observations remain unresolved.

Clean source f53d0b9 passes all 70 runtime checks with typed 716 UI alpha.36 buttons and nested dependency notices at ebc8f4be3fc669080c2a9a14481ceab4fbc4288afb78d4f9659b6d6df0039209. Editor presentation p95 is 41 ms idle, 40 ms loaded and 44 ms rotated. Reboot, repeat install and exact owned guest/app exit pass; private CI 38150499965 and public CI 38149743897 are green. The signed v13 image retains its separate alpha.32 identity pending a new image qualification. The earlier intermittent Ubuntu accessible Save failure remains unexplained with bounded diagnostics retained; passing repeats do not establish a fix. Historical rare PRIMARY-focus and collection geometry observations remain unresolved.

Clean source 3b88d50 passes all 70 runtime checks with typed 716 UI alpha.36 buttons, nested dependency notices and saved-property rollback guards at 99eebefaa36f5112a446ded70e2d770ad306d6f3748574f18f5f9cb902ba1ccf. Editor presentation p95 is 45 ms idle, 42 ms loaded and 38 ms rotated. Reboot, repeat install and exact owned guest/app exit pass; private CI 38152277278 and public CI 38149743897 are green. The signed v13 image retains its separate alpha.32 identity pending a new image qualification. The earlier intermittent Ubuntu accessible Save failure remains unexplained with bounded diagnostics retained; passing repeats do not establish a fix. Historical rare PRIMARY-focus and collection geometry observations remain unresolved.

Signed candidate-v14 passes fresh account/password sudo, compatible signed update/rollback, installed keyboard/zoom, collections, VTE/IME, typed button accessibility, reader, browser, reboot, loopback-only cold boot and activation recovery at exact full70 runtime 99eebefaa36f5112a446ded70e2d770ad306d6f3748574f18f5f9cb902ba1ccf (image SHA-256 bca15fc2e32c6461088d8a0c8686dfb37f8333c29b44cb63134624eb7f719463). Original disk/EFI inode identities and config bytes restored; test SSH/sudo authority and password file removed; owned guest/app stopped and unbooted signature reverified. The prior v13 image and unresolved historical observations remain distinct.

Clean source a5f2f9d passes all 70 runtime checks with 716 UI alpha.37 inline validation at db0002f315f4f3f875fe871f3dab8dc2c0aa2c2025bfd888043e2b517d490248. Editor presentation p95 is 39 ms idle, 41 ms loaded and 43 ms rotated; all 60 receipts completed without invalid, discarded or pending receipts. Reboot, repeat install, saved validation-property rollback refusal and exact owned guest/app exit pass. Private CI 38157700960 and public CI 38157261378 pass. Signed v14 retains its separately qualified alpha.36 identity. Historical rare PRIMARY-focus, collection geometry and accessible Save observations remain distinct; passing current checks do not establish their causes.

Clean source b049091 passes all 70 runtime checks with 716 UI alpha.38 text/choice/toggle validation at 26486fa38bd1de7034f34baa5256b75f7b668259feae05e7d041eb84037a97f1. Editor presentation p95 is 40 ms idle, 46 ms loaded and 42 ms rotated; all 60 receipts completed without invalid, discarded or pending receipts. Reboot, repeat install, saved validation-property rollback refusal and exact owned guest/app exit pass. Private CI 38161410554 and public CI 38159271662 pass. Signed v14 retains its separately qualified alpha.36 identity. Historical rare PRIMARY-focus, collection geometry, accessible Save and validation Discard observations remain distinct; passing current checks do not establish their causes. Choice reconciliation still overrides the library’s field-plus-option name with a label-only name; an independent follow-up probe and guarded library label API are next.

Clean source 452cf7e passes all 70 runtime checks with 716 UI alpha.39 guarded Choice labels at 2f0abf04f083455464a5e0fc505097524a6a0abae1370ff0cc4a7f4ff161a490. Editor presentation p95 is 43 ms idle, 40 ms loaded and 43 ms rotated; all 60 receipts completed without invalid, discarded or pending receipts. Actual core feedback revisions retain Choice field-plus-option accessible names; selected heading replacement defers in all four mapped profiles. Reboot, repeat install, saved validation-property rollback refusal and exact owned guest/app exit pass. Private CI 38163143826 and public CI 38162549698 pass. Signed v14 retains its separately qualified alpha.36 identity. Historical rare PRIMARY-focus, collection geometry, accessible Save and validation Discard observations remain distinct; passing current checks do not establish their causes.

Signed candidate-v15 passes fresh account/password sudo, compatible signed update/rollback, installed keyboard/zoom, collections, VTE/IME, typed button and form-validation accessibility, reader, browser, reboot, loopback-only cold boot and activation recovery at exact full70 runtime 2f0abf04f083455464a5e0fc505097524a6a0abae1370ff0cc4a7f4ff161a490 (image SHA-256 34b83941912b33ff19e859934e56d8207d2297f8477732b42a68b2ee5f73ba8f). Original disk/EFI inode identities and config bytes restored; test SSH/sudo authority and password file removed; owned guest/app stopped and unbooted signature reverified. The prior v14 image and unresolved historical observations remain distinct.
