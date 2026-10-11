//! Session-local display zoom layered over user-owned output preferences.
use smithay::output::{Output, Scale};

const FACTORS: [f64; 5] = [1.0, 1.25, 1.5, 1.75, 2.0];

#[derive(Default)]
pub struct Zoom {
    level: usize,
    bases: Vec<(Output, f64)>,
}
impl Zoom {
    pub fn factor(&self) -> f64 {
        FACTORS[self.level]
    }
    pub fn change(&mut self, direction: i8) {
        self.level = match direction {
            -1 => self.level.saturating_sub(1),
            0 => 0,
            1 => (self.level + 1).min(FACTORS.len() - 1),
            _ => return,
        };
    }
    pub fn apply(&mut self, outputs: &[Output]) {
        // Output handles, rather than connector names, distinguish reconnection
        // with new user preferences from an already magnified live output.
        self.bases.retain(|(output, _)| outputs.contains(output));
        for output in outputs {
            if !self.bases.iter().any(|(known, _)| known == output) {
                self.bases
                    .push((output.clone(), output.current_scale().fractional_scale()));
            }
        }
        let factor = self.factor();
        for (output, base) in &self.bases {
            let scale = base * factor;
            if output.current_scale().fractional_scale() != scale {
                output.change_current_state(None, None, Some(Scale::Fractional(scale)), None);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn output(scale: f64) -> Output {
        use smithay::output::{Mode, PhysicalProperties, Subpixel};
        let output = Output::new(
            "display".into(),
            PhysicalProperties {
                size: (0, 0).into(),
                subpixel: Subpixel::Unknown,
                make: "fixture".into(),
                model: "fixture".into(),
            },
        );
        output.change_current_state(
            Some(Mode {
                size: (1280, 800).into(),
                refresh: 60000,
            }),
            Some(smithay::utils::Transform::_90),
            Some(Scale::Fractional(scale)),
            Some((-100, 20).into()),
        );
        output
    }
    #[test]
    fn zoom_preserves_base_rotation_position_and_exact_reset() {
        let output = output(1.5);
        let mut zoom = Zoom::default();
        zoom.apply(&[output.clone()]);
        zoom.change(1);
        zoom.apply(&[output.clone()]);
        assert_eq!(output.current_scale().fractional_scale(), 1.875);
        for _ in 0..10 {
            zoom.change(1);
            zoom.apply(&[output.clone()]);
        }
        assert_eq!(output.current_scale().fractional_scale(), 3.0);
        assert_eq!(output.current_transform(), smithay::utils::Transform::_90);
        assert_eq!(output.current_location(), (-100, 20).into());
        let mut space = smithay::desktop::Space::<smithay::desktop::Window>::default();
        space.map_output(&output, (-100, 20));
        assert_eq!(
            space.output_geometry(&output).unwrap().size,
            (267, 427).into()
        );
        zoom.change(0);
        zoom.apply(&[output.clone()]);
        assert_eq!(output.current_scale().fractional_scale(), 1.5);
        for _ in 0..10 {
            zoom.change(-1);
        }
        assert_eq!(zoom.factor(), 1.0);
    }
    #[test]
    fn reconnect_uses_new_preferences_and_never_compounds_zoom() {
        let first = output(1.0);
        let mut zoom = Zoom::default();
        zoom.change(1);
        for _ in 0..10 {
            zoom.apply(&[first.clone()]);
        }
        assert_eq!(first.current_scale().fractional_scale(), 1.25);
        let second = output(2.0);
        zoom.apply(&[second.clone()]);
        assert_eq!(second.current_scale().fractional_scale(), 2.5);
        assert_eq!(zoom.bases.len(), 1);
        zoom.change(0);
        zoom.apply(&[second.clone()]);
        assert_eq!(second.current_scale().fractional_scale(), 2.0);
    }
}
