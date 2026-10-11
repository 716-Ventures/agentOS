# Third-party material

The compositor protocol handlers, grabs, input and nested renderer are adapted from Smithay smallvil at revision `f85d06a4629795f5008b573f6b48606db9ff6d71` (v0.6.0). They remain MIT-licensed; the full notice is in LICENSE-SMITHAY. Original agentOS policy and integration code is Apache-2.0. Smithay and other Rust dependencies retain their upstream licenses.

The current renderer uses Smithay’s nested Winit backend. Direct DRM/libinput session ownership, additional output backends and full graphical release qualification are still required.

The host system layers use Smithay's layer map, frame and popup helpers under the same MIT notice. The local integration includes a compatibility hook for Smithay 0.6's stale layer-size validation after layer-role destruction; it permits GTK's destroy-role/null-buffer hide sequence, restores defaults when the role is recreated, and does not bypass validation of live roles.
