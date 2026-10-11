# Third-party material

The native client dynamically uses GTK4 Layer Shell 1.0.4 (MIT), by William Wold and contributors, through its public C API. The complete upstream notice is retained in `licenses/gtk4-layer-shell-1.0.4-LICENSE-MIT.txt`. Debian supplies the runtime library and its package copyright file; Ubuntu 24.04 CI builds upstream commit `536ff516ed68b9bb34afc4c07f942a54b2b4b03f` and installs its license. Upstream linking requirements: https://github.com/wmww/gtk4-layer-shell/blob/v1.0.4/linking.md.

GTK, VTE, public 716 UI and locked Rust dependencies retain their respective licenses. The runtime's generated third-party notice collection covers locked Cargo dependencies. Original agentOS integration code remains Apache-2.0.
