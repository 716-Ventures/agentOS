# Native desktop client

Rust/GTK 4 client over the authenticated, durable presentation contract in `../agent-shell`. Reusable controls come from a versioned public 716 UI release. Documents contain inert data; the renderer keeps stable native widgets, preserves selected text and local drafts, reads live core job bindings, and dispatches opaque host action references. IPC runs separately from GTK input/rendering.

The shell includes activity selection/creation, explicit agent requests, actual core/broker job monitoring, output inspection and direct cancellation. Local microphone capture requires transcript review; the submitted request retains its original activity, selected output and stop generation. Appearance, text scaling and reduced-motion controls are local and persistent. `agent-os-setup` provides deliberate network/audio/provider setup in an ordinary Linux terminal.

Build on ARM64 Linux with Rust 1.85.1, GTK ≥4.12 and the locked dependencies:

```sh
cargo build --locked
cargo build --release --locked --manifest-path ../agent-shell/Cargo.toml
dbus-run-session -- python3 tests/native_desktop.py
```

`--socket PATH` selects an isolated core; `--activity ID` sets the initial activity. The normal core socket is `/run/agent-os/runtime.sock`. The explicit verification mode requires a fixture and a private graphical display; it never submits real model requests. Tests always reap their display, core, compositor and app processes.

`tests/native_desktop.py --compositor` also requires a built `../native-compositor` and tests mixed native/conventional Wayland clients, floating/maximized/tiled placement, exact revisions, undo and no focus stealing. Add `--shared` to exercise core-owned workspaces, authenticated renderer identities, durable focus, journal undo and activity visibility. CI evidence is ARM64 Linux nested graphical verification, not a UTM release qualification.

The native monitor includes typed workspace arrangement controls, proposal review/rejection/approval, conventional terminal attachment and a local rescue terminal. Unsaved local text has a private atomic recovery cache in XDG_STATE_HOME. Output inspection uses bounded pages and preserves a selection while a new page is pending. These newer paths still require guest qualification.

Still required: output removal/recovery, complete pointer grabs and layout pressure, shared terminal projection, paged/virtualized large collections, complete callback parameter editing, agent-generated composition quality, full keyboard/pointer/assistive journeys, reference parity and integrated guest/session installation. The current compositor uses a nested renderer; direct display/session ownership and full VM evidence remain outstanding.
