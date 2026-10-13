//! A transparent, crop-aware legibility tint; no backdrop-blur claim.
use super::*;

fn opacity(channel: u8) -> f64 {
    // Keep every composited sRGB channel at most 117/255. Even one rounding
    // step to 118/255 retains >4.5:1 contrast with the bar's white foreground.
    if channel <= 117 {
        0.0
    } else {
        1.0 - 117.0 / f64::from(channel)
    }
}

fn band_channel(
    pixels: &[u8],
    image: (usize, usize),
    output: (i32, i32),
    bar_height: i32,
) -> Option<u8> {
    let (iw, ih) = image;
    let (ow, oh) = output;
    if iw == 0
        || ih == 0
        || ow <= 0
        || oh <= 0
        || bar_height <= 0
        || pixels.len() != iw.checked_mul(ih)?.checked_mul(4)?
    {
        return None;
    }
    // Match GtkPicture's centered Cover projection. Include a surrounding
    // filter footprint when minifying the opaque approved image.
    let scale = (f64::from(ow) / iw as f64).max(f64::from(oh) / ih as f64);
    let left = (iw as f64 - f64::from(ow) / scale) / 2.0;
    let top = (ih as f64 - f64::from(oh) / scale) / 2.0;
    let padding = (2.0 / scale).ceil().max(1.0) as usize;
    let x0 = (left.floor() as usize).saturating_sub(padding);
    let x1 = ((left + f64::from(ow) / scale).ceil() as usize + padding).min(iw);
    let y0 = (top.floor() as usize).saturating_sub(padding);
    let y1 = ((top + f64::from(bar_height) / scale).ceil() as usize + padding).min(ih);
    let mut maximum = 0;
    for y in y0..y1 {
        for x in x0..x1 {
            let pixel = &pixels[(y * iw + x) * 4..][..3];
            maximum = maximum.max(*pixel.iter().max()?);
        }
    }
    Some(maximum)
}

pub fn background() -> gtk::DrawingArea {
    let area = gtk::DrawingArea::builder()
        .accessible_role(gtk::AccessibleRole::Presentation)
        .hexpand(true)
        .vexpand(true)
        .build();
    area.set_can_target(false);
    area.set_focusable(false);
    let texture = wallpaper::texture().ok();
    let cached = Cell::new(None::<((i32, i32, i32), f64)>);
    area.set_draw_func(move |area, context, width, height| {
        if width <= 0 || height <= 0 {
            return;
        }
        let output_height = area
            .native()
            .and_then(|native| native.surface())
            .and_then(|surface| surface.display().monitor_at_surface(&surface))
            .map(|monitor| monitor.geometry().height())
            .unwrap_or(0);
        let key = (width, output_height, height);
        let alpha = match cached.get() {
            Some((known, alpha)) if known == key => alpha,
            _ => {
                let alpha = texture
                    .as_ref()
                    .and_then(|texture| {
                        if output_height <= 0 {
                            return None;
                        }
                        let (iw, ih) = (texture.width() as usize, texture.height() as usize);
                        let mut pixels = vec![0; iw.checked_mul(ih)?.checked_mul(4)?];
                        // GDK downloads Cairo-compatible 4-byte pixels. Only the
                        // maximum color channel matters, so RGB/BGR order is inert.
                        texture.download(&mut pixels, iw * 4);
                        band_channel(&pixels, (iw, ih), (width, output_height), height).map(opacity)
                    })
                    .unwrap_or_else(|| opacity(255));
                cached.set(Some((key, alpha)));
                alpha
            }
        };
        context.set_source_rgba(0.0, 0.0, 0.0, alpha);
        context.rectangle(0.0, 0.0, f64::from(width), f64::from(height));
        let _ = context.fill();
    });
    area
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn tint_retains_transparency_and_white_contrast_for_every_channel() {
        for maximum in 0..=255 {
            let alpha = opacity(maximum);
            assert!((0.0..0.55).contains(&alpha));
            let composited = (f64::from(maximum) * (1.0 - alpha)).round() / 255.0;
            let luminance = if composited <= 0.04045 {
                composited / 12.92
            } else {
                ((composited + 0.055) / 1.055).powf(2.4)
            };
            assert!(
                1.05 / (luminance + 0.05) >= 4.5,
                "Channel {maximum} lost contrast"
            );
        }
    }
    #[test]
    fn centered_cover_samples_the_visible_band_and_interpolation_edge() {
        let mut pixels = vec![0; 100 * 100 * 4];
        pixels[0] = 255; // Cropped away on a wide output.
        assert_eq!(band_channel(&pixels, (100, 100), (200, 100), 20), Some(0));
        pixels[(24 * 100 + 50) * 4] = 200; // Just outside the band, used by interpolation.
        assert_eq!(band_channel(&pixels, (100, 100), (200, 100), 20), Some(200));
        pixels[(30 * 100 + 50) * 4 + 2] = 255;
        assert_eq!(band_channel(&pixels, (100, 100), (200, 100), 20), Some(255));
        pixels.fill(0);
        pixels[(5 * 100 + 50) * 4 + 1] = 220;
        assert_eq!(band_channel(&pixels, (100, 100), (100, 200), 20), Some(220));
        assert_eq!(band_channel(&pixels, (100, 100), (0, 200), 20), None);
        assert_eq!(band_channel(&pixels[..8], (100, 100), (100, 200), 20), None);
    }
}
