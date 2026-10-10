//! Pointer routing in the union of logical output rectangles.
//! Kept independent of backend types so output removal and gaps can be tested.
#[derive(Clone, Copy, Debug)]
pub struct OutputRect {
    pub x: i32,
    pub y: i32,
    pub width: i32,
    pub height: i32,
}

// Output edges are exact finite integer sums. Step one representable value
// inward without removing the last pixel's fractional coordinates.
fn inside_edge(edge: f64) -> f64 {
    if edge == 0.0 {
        -f64::from_bits(1)
    } else if edge > 0.0 {
        f64::from_bits(edge.to_bits() - 1)
    } else {
        f64::from_bits(edge.to_bits() + 1)
    }
}
pub fn clamp(
    position: (f64, f64),
    outputs: impl IntoIterator<Item = OutputRect>,
) -> Option<(f64, f64)> {
    if !position.0.is_finite() || !position.1.is_finite() {
        return None;
    }
    outputs
        .into_iter()
        .filter(|r| r.width > 0 && r.height > 0)
        .map(|r| {
            // Keep coordinates inside the half-open output, including at negative origins.
            let x = position.0.clamp(
                f64::from(r.x),
                inside_edge(f64::from(r.x) + f64::from(r.width)),
            );
            let y = position.1.clamp(
                f64::from(r.y),
                inside_edge(f64::from(r.y) + f64::from(r.height)),
            );
            let distance = (position.0 - x).hypot(position.1 - y);
            ((x, y), distance)
        })
        .min_by(|a, b| a.1.total_cmp(&b.1))
        .map(|(p, _)| p)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn output(x: i32, y: i32, width: i32, height: i32) -> OutputRect {
        OutputRect {
            x,
            y,
            width,
            height,
        }
    }
    #[test]
    fn relative_motion_crosses_adjacent_outputs_and_retains_subpixels() {
        let outputs = [output(-100, 0, 100, 100), output(0, 0, 200, 100)];
        assert_eq!(clamp((-0.5 + 2.0, 12.25), outputs), Some((1.5, 12.25)));
        assert_eq!(
            clamp((-999.0, 999.0), outputs),
            Some((-100.0, inside_edge(100.0)))
        );
    }
    #[test]
    fn final_pixel_subpixels_and_negative_zero_edges_stay_inside() {
        let single = [output(-1, -1, 1, 1)];
        assert_eq!(clamp((-0.25, -0.75), single), Some((-0.25, -0.75)));
        let at_edge = clamp((0.0, 0.0), single).unwrap();
        assert!(at_edge.0 < 0.0 && at_edge.0 >= -1.0);
        assert!(at_edge.1 < 0.0 && at_edge.1 >= -1.0);
        assert_eq!(
            clamp((99.75, 99.5), [output(0, 0, 100, 100)]),
            Some((99.75, 99.5))
        );
    }
    #[test]
    fn gaps_and_removed_outputs_choose_nearest_remaining_display() {
        let outputs = [output(0, 0, 100, 100), output(200, 100, 100, 100)];
        assert_eq!(clamp((180.0, 120.0), outputs), Some((200.0, 120.0)));
        assert_eq!(
            clamp((250.0, 150.0), [outputs[0]]),
            Some((inside_edge(100.0), inside_edge(100.0)))
        );
        assert_eq!(clamp((1.0, 1.0), []), None);
        assert_eq!(clamp((1.0, 1.0), [output(0, 0, 0, 100)]), None);
    }
    #[test]
    fn invalid_coordinates_and_extreme_integer_origins_are_safe() {
        let outputs = [output(i32::MAX, i32::MIN, i32::MAX, 1)];
        assert_eq!(clamp((f64::NAN, 0.0), outputs), None);
        assert_eq!(clamp((0.0, f64::INFINITY), outputs), None);
        assert_eq!(
            clamp((f64::MAX, f64::MIN), outputs),
            Some((inside_edge(4294967294.0), -2147483648.0))
        );
    }
}
