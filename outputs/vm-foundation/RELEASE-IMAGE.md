# Experimental integrated image

`build_release_image.py` constructs a new ARM64 disk from the exact Debian base in `image-lock.json`. It never exports the running development disk. The dedicated Linux builder supplies only manifest-verified immutable runtime files, the recorded dependency profile and hash-verified offline speech assets. Activities, provider settings, personal accounts, SSH authorized keys, logs and other running-VM state are not inputs.

The initial image includes the complete development dependency profile. It is an experimental VM release, not a minimal production distribution or a physical-hardware qualification. A repeat build identifies the exact base, dependency profile, runtime release, image-building sources and resulting disk hash; package installation and filesystem creation do not promise bit-for-bit identical disk bytes.

The private build directory lives beside the requested output so final publication can hard-link the completed, fsynced image exclusively. This avoids a third disk-sized copy while refusing existing files and symlinks, including ones created during the build. The build still needs space for its sparse raw filesystem and converted qcow2 at the same time. A failed build cannot be packaged without complete metadata and signature verification.

## Build

Use a dedicated Debian 13 ARM64 Linux VM with the verified runtime installed. The builder needs `qemu-img`, `growpart`, `losetup`, `e2fsck`, `resize2fs`, `mount`, `lsblk`, `udevadm`, `fstrim`, OpenSSL and systemd tools. Do not run it against a physical disk. It accepts only a new output path and a checksum-matching regular upstream base image, creates its own private sparse disk and loop device, and detaches that device after unmounting its private filesystems.

Provision an Ed25519 update **public** key as a build input. Keep its private signing key outside the builder and outside the image. A development-generated key qualifies the development workflow; production trust needs an independently provisioned verification key and controlled signing operations.

```sh
sudo python3 outputs/vm-foundation/build_release_image.py \
  --dedicated-builder \
  --base /path/to/pinned-base.qcow2 \
  --output /path/to/new-agentos-release.qcow2 \
  --bootstrap outputs/agent-shell/bootstrap.py \
  --update-key /path/to/update-signing-key.pem
```

Transfer the new disk and adjacent `.json` metadata to the packaging host. Package with the matching private key:

```sh
python3 outputs/vm-foundation/package_release_image.py create \
  --image /path/to/new-agentos-release.qcow2 \
  --metadata /path/to/new-agentos-release.json \
  --signing-key /private/path/image-signing.pem \
  --output /path/to/new-agentos-release.utm
python3 outputs/vm-foundation/package_release_image.py verify \
  /path/to/new-agentos-release.utm --trusted-key /separately/trusted/public.pem
```

Packaging signs the image metadata and the exact VM configuration. The bundle has a new VM identity and MAC address, one disk, no development seed, no host directory/clipboard sharing and no SSH port forwarding. An incomplete bundle retains an `INCOMPLETE` marker. Verify before importing or booting; normal VM execution changes its disk and may change its configuration. The public key included with an artifact does not by itself establish its authenticity.

## First run and recovery

The image starts a root-owned setup service on `/dev/console`. It asks for a personal account name and password locally; it never writes the password to a setup journal. The ordinary account gets password-protected sudo. Runtime activation uses that selected login identity. Only after health checks succeed does normal console login become available on the setup console. TTY 2 becomes a rescue login as soon as account setup succeeds, so an activation failure can be repaired without models.

Account creation and activation are resumable. Setup refuses to adopt an unrelated account or recycled UID. Root login is locked, SSH is disabled, cloud-init does not consume a development seed, and machine identifiers and SSH host keys are not cloned. Speech recognition is included; a physical microphone/speaker signal and live speech quality still require qualification.

After login, run `agent-os` or start `agent-os-session` from a local graphical login. `sudo agent-os-configure` provisions providers; `agent-os setup` reports network/audio/provider readiness. Signed runtime updates can be staged from local bundles or explicit HTTPS URLs and activated deliberately. Runtime rollback preserves activities and credentials; it does not roll back Debian packages, kernel, arbitrary file effects or the VM disk. An incompatible state contract remains refused until an explicit migration is implemented and qualified.

The original distribution artifact remains untouched during first-boot testing: boot a separate copy, create a fixture account there, and remove or archive that verification copy afterward. Do not promote a disk that has been booted with developer credentials or real provider configuration.

Qualification evidence is recorded in [image-verification.json](image-verification.json). It identifies the exact image/runtime and development signing boundary. The qualification copy exercised fresh firmware, first-run console account/sudo, DHCP/HTTPS, direct KMS/kernel input/clipboard/undo/Save/VT, offline speech, reboot persistence, no-network cold boot and a real failed activation followed by account-preserving recovery. Distribution bytes remained unbooted and separately signature-verified.

UTM can retain an in-memory VM configuration after its bundle file is edited. For a qualification-only disk, seed or network change, stop all guests and restart the owned UTM app before starting the changed guest. Verify the actual guest block-device and network inventory; the saved plist alone is not evidence that a seed or adapter is absent. Keep the development disk/configuration/EFI backed up until the qualification copy is stopped and restore them before finishing.

The latest clean image includes the same runtime that passed the full 48-check UTM reproduction, including public 716 UI alpha.21 and the compositor transport/input ownership fixes. Qualification stages a signed compatible older runtime, activates it, then rolls back to the clean image runtime while preserving activity/file state. The image runtime also passes direct input, speech fixtures, reboot and offline setup recovery. Exact image/runtime and rollback-probe identities are retained in `image-verification.json`; all artifacts retain the development signing authority boundary.
