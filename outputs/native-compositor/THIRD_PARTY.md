# Third-party material

The compositor protocol handlers, grabs, input and nested renderer are adapted from Smithay smallvil at revision `f85d06a4629795f5008b573f6b48606db9ff6d71` (v0.6.0). They remain MIT-licensed; the full notice is in LICENSE-SMITHAY. Original agentOS policy and integration code is Apache-2.0. Smithay and other Rust dependencies retain their upstream licenses.

The current renderer uses Smithay’s nested Winit backend. Direct DRM/libinput session ownership, additional output backends and full graphical release qualification are still required.
