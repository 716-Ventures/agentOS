//! Real socket/protocol test: trusted IME preedit/commit and ordinary-client denial.
use crate::{state::ClientState, CalloopData, Smallvil};
use smithay::{
    reexports::{
        calloop::EventLoop,
        wayland_server::{protocol::wl_surface::WlSurface, Display},
    },
    wayland::{input_method::InputMethodManagerState, text_input::TextInputManagerState},
};
use std::{
    os::unix::net::UnixStream,
    sync::{mpsc, Arc},
    time::{Duration, Instant},
};
use wayland_client::{
    protocol::{wl_compositor, wl_registry, wl_seat, wl_surface},
    Connection, Dispatch, QueueHandle,
};
use wayland_protocols::wp::text_input::zv3::client::{
    zwp_text_input_manager_v3, zwp_text_input_v3,
};
use wayland_protocols_misc::zwp_input_method_v2::client::{
    zwp_input_method_manager_v2, zwp_input_method_v2,
};

#[derive(Default)]
struct Client {
    seat: Option<wl_seat::WlSeat>,
    compositor: Option<wl_compositor::WlCompositor>,
    text: Option<zwp_text_input_manager_v3::ZwpTextInputManagerV3>,
    ime: Option<zwp_input_method_manager_v2::ZwpInputMethodManagerV2>,
    ime_global: Option<u32>,
    entered: bool,
    preedit: Vec<String>,
    commits: Vec<String>,
    serial: u32,
}
impl Dispatch<wl_registry::WlRegistry, ()> for Client {
    fn event(
        state: &mut Self,
        registry: &wl_registry::WlRegistry,
        event: wl_registry::Event,
        _: &(),
        _: &Connection,
        qh: &QueueHandle<Self>,
    ) {
        if let wl_registry::Event::Global {
            name,
            interface,
            version,
        } = event
        {
            match interface.as_str() {
                "wl_seat" => state.seat = Some(registry.bind(name, version.min(7), qh, ())),
                "wl_compositor" => {
                    state.compositor = Some(registry.bind(name, version.min(4), qh, ()))
                }
                "zwp_text_input_manager_v3" => state.text = Some(registry.bind(name, 1, qh, ())),
                "zwp_input_method_manager_v2" => {
                    state.ime_global = Some(name);
                    state.ime = Some(registry.bind(name, 1, qh, ()));
                }
                _ => {}
            }
        }
    }
}
impl Dispatch<zwp_text_input_v3::ZwpTextInputV3, ()> for Client {
    fn event(
        state: &mut Self,
        _: &zwp_text_input_v3::ZwpTextInputV3,
        event: zwp_text_input_v3::Event,
        _: &(),
        _: &Connection,
        _: &QueueHandle<Self>,
    ) {
        match event {
            zwp_text_input_v3::Event::Enter { .. } => state.entered = true,
            zwp_text_input_v3::Event::Leave { .. } => state.entered = false,
            zwp_text_input_v3::Event::PreeditString { text, .. } => {
                state.preedit.push(text.unwrap_or_default())
            }
            zwp_text_input_v3::Event::CommitString { text } => {
                state.commits.push(text.unwrap_or_default())
            }
            _ => {}
        }
    }
}
impl Dispatch<zwp_input_method_v2::ZwpInputMethodV2, ()> for Client {
    fn event(
        state: &mut Self,
        _: &zwp_input_method_v2::ZwpInputMethodV2,
        event: zwp_input_method_v2::Event,
        _: &(),
        _: &Connection,
        _: &QueueHandle<Self>,
    ) {
        if let zwp_input_method_v2::Event::Done = event {
            state.serial += 1;
        }
    }
}
wayland_client::delegate_noop!(Client: ignore wl_seat::WlSeat);
wayland_client::delegate_noop!(Client: ignore wl_compositor::WlCompositor);
wayland_client::delegate_noop!(Client: ignore wl_surface::WlSurface);
wayland_client::delegate_noop!(Client: ignore zwp_text_input_manager_v3::ZwpTextInputManagerV3);
wayland_client::delegate_noop!(Client: ignore zwp_input_method_manager_v2::ZwpInputMethodManagerV2);

#[test]
fn private_input_method_delivers_unicode_and_cannot_be_bound_by_an_application() {
    let (app_server, app_socket) = UnixStream::pair().unwrap();
    let (ime_server, ime_socket) = UnixStream::pair().unwrap();
    let (commands, receive) = mpsc::channel::<Option<u32>>();
    let (ack, acknowledged) = mpsc::channel();
    let server = std::thread::spawn(move || {
        let runtime = std::env::temp_dir().join(format!("agentos-ime-test-{}", std::process::id()));
        std::fs::create_dir(&runtime).unwrap();
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&runtime, std::fs::Permissions::from_mode(0o700)).unwrap();
        let prior = std::env::var_os("XDG_RUNTIME_DIR");
        std::env::set_var("XDG_RUNTIME_DIR", &runtime);
        let mut event_loop = EventLoop::<CalloopData>::try_new().unwrap();
        let display = Display::<Smallvil>::new().unwrap();
        let mut dh = display.handle();
        let app = dh
            .insert_client(app_server, Arc::new(ClientState::default()))
            .unwrap();
        dh.insert_client(
            ime_server,
            Arc::new(ClientState {
                input_method: true,
                ..ClientState::default()
            }),
        )
        .unwrap();
        let _manager = InputMethodManagerState::new::<Smallvil, _>(&dh, |client| {
            client
                .get_data::<ClientState>()
                .is_some_and(|d| d.input_method)
        });
        let _text = TextInputManagerState::new::<Smallvil>(&dh);
        let state = Smallvil::new(&mut event_loop, display);
        let mut data = CalloopData {
            state,
            display_handle: dh.clone(),
        };
        let deadline = Instant::now() + Duration::from_secs(10);
        'dispatch: while Instant::now() < deadline {
            event_loop
                .dispatch(Duration::from_millis(2), &mut data)
                .unwrap();
            loop {
                let focus = match receive.try_recv() {
                    Ok(focus) => focus,
                    Err(mpsc::TryRecvError::Empty) => break,
                    Err(mpsc::TryRecvError::Disconnected) => break 'dispatch,
                };
                let surface =
                    focus.map(|id| app.object_from_protocol_id::<WlSurface>(&dh, id).unwrap());
                data.state.seat.get_keyboard().unwrap().set_focus(
                    &mut data.state,
                    surface,
                    smithay::utils::SERIAL_COUNTER.next_serial(),
                );
                ack.send(()).unwrap();
            }
            dh.flush_clients().unwrap();
        }
        drop(data);
        drop(event_loop);
        if let Some(prior) = prior {
            std::env::set_var("XDG_RUNTIME_DIR", prior);
        } else {
            std::env::remove_var("XDG_RUNTIME_DIR");
        }
        std::fs::remove_dir_all(runtime).unwrap();
    });
    let app = Connection::from_socket(app_socket).unwrap();
    let ime = Connection::from_socket(ime_socket).unwrap();
    let mut app_queue = app.new_event_queue::<Client>();
    let app_qh = app_queue.handle();
    let app_registry = app.display().get_registry(&app_qh, ());
    let mut application = Client::default();
    app_queue.roundtrip(&mut application).unwrap();
    assert!(
        application.ime.is_none(),
        "Ordinary application can see privileged IME global"
    );
    let mut ime_queue = ime.new_event_queue::<Client>();
    let ime_qh = ime_queue.handle();
    ime.display().get_registry(&ime_qh, ());
    let mut method = Client::default();
    ime_queue.roundtrip(&mut method).unwrap();
    let input =
        method
            .ime
            .as_ref()
            .unwrap()
            .get_input_method(method.seat.as_ref().unwrap(), &ime_qh, ());
    ime_queue.roundtrip(&mut method).unwrap();
    let surface = application
        .compositor
        .as_ref()
        .unwrap()
        .create_surface(&app_qh, ());
    let text = application.text.as_ref().unwrap().get_text_input(
        application.seat.as_ref().unwrap(),
        &app_qh,
        (),
    );
    app_queue.roundtrip(&mut application).unwrap();
    use wayland_client::Proxy;
    commands.send(Some(surface.id().protocol_id())).unwrap();
    acknowledged.recv_timeout(Duration::from_secs(2)).unwrap();
    app_queue.roundtrip(&mut application).unwrap();
    assert!(application.entered);
    text.enable();
    text.commit();
    app_queue.roundtrip(&mut application).unwrap();
    ime_queue.roundtrip(&mut method).unwrap();
    input.set_preedit_string("にほん λ".into(), 9, 9);
    input.commit(method.serial);
    ime_queue.roundtrip(&mut method).unwrap();
    app_queue.roundtrip(&mut application).unwrap();
    assert_eq!(application.preedit.last().unwrap(), "にほん λ");
    input.commit_string("日本語 λ".into());
    input.commit(method.serial);
    ime_queue.roundtrip(&mut method).unwrap();
    app_queue.roundtrip(&mut application).unwrap();
    assert_eq!(application.commits, vec!["日本語 λ"]);
    commands.send(None).unwrap();
    acknowledged.recv_timeout(Duration::from_secs(2)).unwrap();
    app_queue.roundtrip(&mut application).unwrap();
    assert!(!application.entered);
    input.commit_string("stale input".into());
    input.commit(method.serial);
    ime_queue.roundtrip(&mut method).unwrap();
    app_queue.roundtrip(&mut application).unwrap();
    assert_eq!(application.commits, vec!["日本語 λ"]);
    let _: zwp_input_method_manager_v2::ZwpInputMethodManagerV2 =
        app_registry.bind(method.ime_global.unwrap(), 1, &app_qh, ());
    assert!(
        app_queue.roundtrip(&mut application).is_err(),
        "Hidden privileged global accepted a forced bind"
    );
    drop(commands);
    server.join().unwrap();
}
