//! Experimental single-GPU KMS backend. The nested backend remains the default.
//! Uses Smithay's session, allocator and scanout APIs (see LICENSE-SMITHAY).
use crate::{CalloopData, Smallvil};
use smithay::{
    backend::{
        allocator::{
            gbm::{GbmAllocator, GbmBufferFlags, GbmDevice},
            Fourcc,
        },
        drm::{DrmDevice, DrmDeviceFd, DrmEvent, GbmBufferedSurface},
        egl::{EGLContext, EGLDisplay},
        libinput::{LibinputInputBackend, LibinputSessionInterface},
        renderer::{
            damage::OutputDamageTracker,
            element::{
                memory::{MemoryRenderBuffer, MemoryRenderBufferRenderElement},
                surface::{render_elements_from_surface_tree, WaylandSurfaceRenderElement},
                Kind,
            },
            gles::GlesRenderer,
            Bind, ImportAll, ImportDma, ImportMem,
        },
        session::{libseat::LibSeatSession, Event as SessionEvent, Session},
        udev::{primary_gpu, UdevBackend, UdevEvent},
    },
    input::pointer::{CursorImageStatus, CursorImageSurfaceData},
    output::{Mode, Output, PhysicalProperties, Scale, Subpixel},
    reexports::{
        calloop::{
            timer::{TimeoutAction, Timer},
            EventLoop,
        },
        drm::control::{connector, crtc, Device as _, ModeTypeFlags},
        input::Libinput,
        rustix::fs::OFlags,
        wayland_server::backend::GlobalId,
    },
    utils::{DeviceFd, Transform},
    wayland::compositor::with_states,
};
use std::{
    cell::RefCell,
    collections::{HashMap, HashSet},
    path::PathBuf,
    rc::Rc,
    time::Duration,
};
type Scanout = GbmBufferedSurface<GbmAllocator<DrmDeviceFd>, ()>;
smithay::render_elements! {
    Cursor<R> where R: ImportAll + ImportMem;
    Surface=WaylandSurfaceRenderElement<R>,
    Memory=MemoryRenderBufferRenderElement<R>,
}
struct Head {
    output: Output,
    global: GlobalId,
    scanout: Scanout,
    damage: OutputDamageTracker,
    pending: bool,
}
struct Device {
    drm: DrmDevice,
    gbm: GbmDevice<DrmDeviceFd>,
    renderer: GlesRenderer,
    heads: HashMap<crtc::Handle, Head>,
    active: bool,
    cursor: MemoryRenderBuffer,
    retry_at: std::time::Instant,
    config: crate::output_config::Config,
}
impl Device {
    fn disconnect(&mut self, data: &mut CalloopData) {
        for (_, head) in std::mem::take(&mut self.heads) {
            data.state.space.unmap_output(&head.output);
            data.display_handle.remove_global::<Smallvil>(head.global);
        }
    }
    fn scan(&mut self, data: &mut CalloopData) -> Result<(), Box<dyn std::error::Error>> {
        self.disconnect(data);
        let resources = self.drm.resource_handles()?;
        let mut used = HashSet::new();
        let mut x = 0;
        for handle in resources.connectors() {
            let connector = self.drm.get_connector(*handle, true)?;
            if connector.state() != connector::State::Connected {
                continue;
            }
            let name = format!("{:?}-{}", connector.interface(), connector.interface_id());
            let preference = self.config.outputs.get(&name).cloned().unwrap_or_default();
            let selected = if let Some(requested) = &preference.mode {
                connector.modes().iter().find(|m| {
                    let mode = Mode::from(**m);
                    mode.size.w == i32::from(requested.width)
                        && mode.size.h == i32::from(requested.height)
                        && mode.refresh == requested.refresh_millihz as i32
                })
            } else {
                connector
                    .modes()
                    .iter()
                    .find(|m| m.mode_type().contains(ModeTypeFlags::PREFERRED))
                    .or_else(|| connector.modes().first())
            };
            let Some(mode) = selected.copied() else {
                eprintln!("No matching mode for connector {name}");
                continue;
            };
            let mut candidates = Vec::new();
            for encoder in connector.encoders() {
                if let Ok(encoder) = self.drm.get_encoder(*encoder) {
                    candidates.extend(resources.filter_crtcs(encoder.possible_crtcs()));
                }
            }
            let Some(crtc) = candidates.into_iter().find(|c| !used.contains(c)) else {
                continue;
            };
            let surface = match self.drm.create_surface(crtc, mode, &[*handle]) {
                Ok(surface) => surface,
                Err(error) => {
                    eprintln!("Cannot configure connector {handle:?}: {error}");
                    continue;
                }
            };
            let allocator = GbmAllocator::new(
                self.gbm.clone(),
                GbmBufferFlags::RENDERING | GbmBufferFlags::SCANOUT,
            );
            let scanout = match Scanout::new(
                surface,
                allocator,
                &[Fourcc::Argb8888, Fourcc::Abgr8888],
                self.renderer.dmabuf_formats(),
            ) {
                Ok(scanout) => scanout,
                Err(error) => {
                    eprintln!("Cannot allocate connector {handle:?}: {error}");
                    continue;
                }
            };
            let output = Output::new(
                name,
                PhysicalProperties {
                    size: connector
                        .size()
                        .map(|(w, h)| (w as i32, h as i32))
                        .unwrap_or((0, 0))
                        .into(),
                    subpixel: Subpixel::Unknown,
                    make: "DRM".into(),
                    model: format!("{:?}", connector.interface()),
                },
            );
            let global = output.create_global::<Smallvil>(&data.display_handle);
            let wl_mode = Mode::from(mode);
            let position = (preference.x.unwrap_or(x), preference.y.unwrap_or(0));
            output.change_current_state(
                Some(wl_mode),
                Some(Transform::Normal),
                Some(Scale::Fractional(preference.scale)),
                Some(position.into()),
            );
            output.set_preferred(wl_mode);
            data.state.space.map_output(&output, position);
            x = position.0 + (f64::from(mode.size().0) / preference.scale).ceil() as i32;
            let damage = OutputDamageTracker::from_output(&output);
            self.heads.insert(
                crtc,
                Head {
                    output,
                    global,
                    scanout,
                    damage,
                    pending: false,
                },
            );
            used.insert(crtc);
        }
        Ok(())
    }
    fn render(&mut self, data: &mut CalloopData) {
        let _timing = crate::timings::Span::new("compositor.direct_render_attempt");
        if !self.active || std::time::Instant::now() < self.retry_at {
            return;
        }
        data.state.arrange();
        let renderer = &mut self.renderer;
        for head in self.heads.values_mut() {
            if head.pending {
                continue;
            }
            let rendered = (|| -> Result<(), Box<dyn std::error::Error>> {
                let Some(geometry) = data.state.space.output_geometry(&head.output) else {
                    return Ok(());
                };
                let pointer = data.state.seat.get_pointer().unwrap().current_location()
                    - geometry.loc.to_f64();
                let scale = head.output.current_scale().fractional_scale();
                let location = pointer.to_physical(scale);
                let cursor: Vec<Cursor<GlesRenderer>> = match &data.state.cursor_image {
                    CursorImageStatus::Hidden => Vec::new(),
                    CursorImageStatus::Named(_) => {
                        vec![MemoryRenderBufferRenderElement::from_buffer(
                            renderer,
                            location,
                            &self.cursor,
                            None,
                            None,
                            None,
                            Kind::Cursor,
                        )?
                        .into()]
                    }
                    CursorImageStatus::Surface(surface) => {
                        let hotspot = with_states(surface, |states| {
                            states
                                .data_map
                                .get::<CursorImageSurfaceData>()
                                .map(|a| a.lock().unwrap().hotspot)
                                .unwrap_or_default()
                        });
                        render_elements_from_surface_tree(
                            renderer,
                            surface,
                            (pointer - hotspot.to_f64())
                                .to_physical(scale)
                                .to_i32_round(),
                            scale,
                            1.0,
                            Kind::Cursor,
                        )
                    }
                };
                let (mut buffer, age) = head.scanout.next_buffer()?;
                let mut target = renderer.bind(&mut buffer)?;
                let result = smithay::desktop::space::render_output(
                    &head.output,
                    renderer,
                    &mut target,
                    1.0,
                    age as usize,
                    [&data.state.space],
                    &cursor,
                    &mut head.damage,
                    [0.1, 0.1, 0.1, 1.0],
                )?;
                let sync = result.sync;
                drop(target);
                head.scanout.queue_buffer(Some(sync), None, ())?;
                head.pending = true;
                for window in data.state.space.elements() {
                    window.send_frame(
                        &head.output,
                        data.state.start_time.elapsed(),
                        Some(Duration::ZERO),
                        |_, _| Some(head.output.clone()),
                    );
                }
                Ok(())
            })();
            if let Err(error) = rendered {
                eprintln!("Direct output frame failed: {error}");
                head.damage = OutputDamageTracker::from_output(&head.output);
                self.retry_at = std::time::Instant::now() + Duration::from_secs(1);
            }
        }
        data.state.space.refresh();
        data.state.popups.cleanup();
        let _ = data.display_handle.flush_clients();
    }
}
fn cursor() -> MemoryRenderBuffer {
    // Original monochrome arrow, premultiplied BGRA. No external asset dependency.
    let mut rgba = vec![0; 16 * 24 * 4];
    for y in 0..20usize {
        for x in 0..12usize {
            if x <= y / 2 && (y < 14 || (x >= 4 && x <= 7)) {
                let edge = x == 0 || x == y / 2 || y == 19;
                let color = if edge { 0 } else { 255 };
                rgba[(y * 16 + x) * 4..(y * 16 + x) * 4 + 4]
                    .copy_from_slice(&[color, color, color, 255]);
            }
        }
    }
    MemoryRenderBuffer::from_slice(
        &rgba,
        Fourcc::Argb8888,
        (16, 24),
        1,
        Transform::Normal,
        None,
    )
}
pub fn init(
    event_loop: &mut EventLoop<CalloopData>,
    data: &mut CalloopData,
) -> Result<(), Box<dyn std::error::Error>> {
    let config = crate::output_config::Config::load()?;
    let (mut session, notifier) = LibSeatSession::new()?;
    let seat_name = session.seat();
    let udev = UdevBackend::new(&seat_name)?;
    let path = std::env::var_os("AGENT_OS_DRM_DEVICE")
        .map(PathBuf::from)
        .or(primary_gpu(session.seat())?)
        .or_else(|| udev.device_list().next().map(|(_, p)| p.to_owned()))
        .ok_or("No DRM device available on this seat")?;
    let device_id = udev
        .device_list()
        .find(|(_, p)| *p == path)
        .map(|(id, _)| id)
        .ok_or("DRM device does not belong to this seat")?;
    let fd = DrmDeviceFd::new(DeviceFd::from(session.open(
        &path,
        OFlags::RDWR | OFlags::CLOEXEC | OFlags::NONBLOCK | OFlags::NOCTTY,
    )?));
    let (drm, drm_events) = DrmDevice::new(fd.clone(), true)?;
    let gbm = GbmDevice::new(fd)?;
    let display = unsafe { EGLDisplay::new(gbm.clone())? };
    let context = EGLContext::new(&display)?;
    let renderer = unsafe { GlesRenderer::new(context)? };
    let device = Rc::new(RefCell::new(Device {
        drm,
        gbm,
        renderer,
        heads: HashMap::new(),
        active: session.is_active(),
        cursor: cursor(),
        retry_at: std::time::Instant::now(),
        config,
    }));
    device.borrow_mut().scan(data)?;
    data.state.direct_active = Some(device.borrow().active);
    if device.borrow().heads.is_empty() {
        return Err("No usable connected DRM output".into());
    }
    let mut input =
        Libinput::new_with_udev::<LibinputSessionInterface<LibSeatSession>>(session.clone().into());
    input
        .udev_assign_seat(&seat_name)
        .map_err(|_| "Cannot assign libinput seat")?;
    let backend = LibinputInputBackend::new(input.clone());
    let active = device.clone();
    event_loop
        .handle()
        .insert_source(backend, move |event, _, data| {
            if active.borrow().active {
                data.state.process_input_event(event);
            }
        })?;
    let session_device = device.clone();
    event_loop
        .handle()
        .insert_source(notifier, move |event, _, data| {
            let mut device = session_device.borrow_mut();
            match event {
                SessionEvent::PauseSession => {
                    device.active = false;
                    data.state.direct_active = Some(false);
                    input.suspend();
                    device.drm.pause();
                }
                SessionEvent::ActivateSession => {
                    let resumed = input
                        .resume()
                        .map_err(|error| format!("Input resume failed: {error:?}"))
                        .and_then(|_| {
                            device
                                .drm
                                .activate(false)
                                .map_err(|error| format!("DRM resume failed: {error}"))
                        });
                    if let Err(error) = resumed {
                        data.state.direct_resume_error = Some(error);
                        data.state.direct_active = Some(false);
                    } else {
                        for head in device.heads.values_mut() {
                            head.scanout.reset_buffers();
                            head.pending = false;
                            head.damage = OutputDamageTracker::from_output(&head.output);
                        }
                        device.active = true;
                        data.state.direct_active = Some(true);
                        data.state.direct_resume_error = None;
                    }
                }
            }
        })?;
    let frames = device.clone();
    event_loop
        .handle()
        .insert_source(drm_events, move |event, _, data| {
            let mut device = frames.borrow_mut();
            match event {
                DrmEvent::VBlank(crtc) => {
                    if let Some(head) = device.heads.get_mut(&crtc) {
                        if !head.pending {
                            return;
                        }
                        match head.scanout.frame_submitted() {
                            Ok(_) => {
                                data.state.direct_frames_presented =
                                    data.state.direct_frames_presented.saturating_add(1)
                            }
                            Err(error) => eprintln!("Scanout completion failed: {error}"),
                        }
                        head.pending = false;
                    }
                }
                DrmEvent::Error(error) => eprintln!("DRM event failed: {error}"),
            }
        })?;
    let hotplug = device.clone();
    event_loop
        .handle()
        .insert_source(udev, move |event, _, data| match event {
            UdevEvent::Changed { device_id: id } if id == device_id => {
                if let Err(error) = hotplug.borrow_mut().scan(data) {
                    eprintln!("Output discovery failed: {error}");
                }
            }
            UdevEvent::Removed { device_id: id } if id == device_id => {
                hotplug.borrow_mut().disconnect(data);
                data.state.loop_signal.stop();
            }
            _ => {}
        })?;
    event_loop
        .handle()
        .insert_source(Timer::immediate(), move |_, _, data| {
            device.borrow_mut().render(data);
            TimeoutAction::ToDuration(Duration::from_millis(16))
        })?;
    data.state.direct_session = Some(session);
    std::env::set_var("WAYLAND_DISPLAY", &data.state.socket_name);
    Ok(())
}
