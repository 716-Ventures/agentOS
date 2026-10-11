//! User-owned direct-output preferences, independent of device access.
use serde::Deserialize;
use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Config {
    pub outputs: BTreeMap<String, Preference>,
}
#[derive(Clone, Debug, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct Preference {
    pub scale: f64,
    pub transform: Transform,
    pub x: Option<i32>,
    pub y: Option<i32>,
    pub mode: Option<Mode>,
}
impl Default for Preference {
    fn default() -> Self {
        Self {
            scale: 1.0,
            transform: Transform::Normal,
            x: None,
            y: None,
            mode: None,
        }
    }
}
/// The eight Wayland output transforms, owned by the local user configuration.
#[derive(Clone, Copy, Debug, Default, Deserialize, PartialEq, Eq)]
pub enum Transform {
    #[default]
    #[serde(rename = "normal")]
    Normal,
    #[serde(rename = "90")]
    Rotate90,
    #[serde(rename = "180")]
    Rotate180,
    #[serde(rename = "270")]
    Rotate270,
    #[serde(rename = "flipped")]
    Flipped,
    #[serde(rename = "flipped-90")]
    Flipped90,
    #[serde(rename = "flipped-180")]
    Flipped180,
    #[serde(rename = "flipped-270")]
    Flipped270,
}
impl Transform {
    pub fn native(self) -> smithay::utils::Transform {
        use smithay::utils::Transform as Native;
        match self {
            Self::Normal => Native::Normal,
            Self::Rotate90 => Native::_90,
            Self::Rotate180 => Native::_180,
            Self::Rotate270 => Native::_270,
            Self::Flipped => Native::Flipped,
            Self::Flipped90 => Native::Flipped90,
            Self::Flipped180 => Native::Flipped180,
            Self::Flipped270 => Native::Flipped270,
        }
    }
}
impl Preference {
    pub fn logical_size(
        &self,
        size: smithay::utils::Size<i32, smithay::utils::Physical>,
    ) -> smithay::utils::Size<i32, smithay::utils::Logical> {
        self.transform
            .native()
            .transform_size(size)
            .to_f64()
            .to_logical(self.scale)
            .to_i32_ceil()
    }
}
#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Mode {
    pub width: u16,
    pub height: u16,
    pub refresh_millihz: u32,
}
impl Config {
    pub fn parse(bytes: &[u8]) -> Result<Self, String> {
        if bytes.len() > 65536 {
            return Err("Output preferences exceed 64 KiB".into());
        }
        let config: Self =
            serde_json::from_slice(bytes).map_err(|_| "Invalid output preference document")?;
        if config.outputs.len() > 64 {
            return Err("At most 64 output preferences are supported".into());
        }
        for (id, p) in &config.outputs {
            if id.is_empty()
                || id.len() > 128
                || !id
                    .bytes()
                    .all(|c| c.is_ascii_alphanumeric() || b"._-".contains(&c))
            {
                return Err("Invalid output preference identity".into());
            }
            if !p.scale.is_finite()
                || !(0.5..=4.0).contains(&p.scale)
                || p.x.is_some() != p.y.is_some()
                || [p.x, p.y]
                    .into_iter()
                    .flatten()
                    .any(|n| !(-65536..=65536).contains(&n))
            {
                return Err("Invalid output scale or logical position".into());
            }
            if p.mode.as_ref().is_some_and(|m| {
                m.width == 0
                    || m.height == 0
                    || m.width > 16384
                    || m.height > 16384
                    || !(1000..=1000000).contains(&m.refresh_millihz)
            }) {
                return Err("Invalid output mode preference".into());
            }
        }
        Ok(config)
    }
    pub fn load() -> Result<Self, String> {
        use std::{io::Read, path::PathBuf};
        let root = std::env::var_os("XDG_CONFIG_HOME")
            .map(PathBuf::from)
            .or_else(|| std::env::var_os("HOME").map(|p| PathBuf::from(p).join(".config")))
            .ok_or("No user configuration directory")?;
        let path = root.join("agentos/outputs.json");
        match std::fs::File::open(&path) {
            Ok(file) => {
                let mut bytes = Vec::new();
                file.take(65537)
                    .read_to_end(&mut bytes)
                    .map_err(|e| e.to_string())?;
                Self::parse(&bytes)
            }
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(Self::default()),
            Err(e) => Err(e.to_string()),
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn fractional_scales_negative_origins_and_exact_modes_are_retained() {
        let config=Config::parse(br#"{"outputs":{"DP-1":{"scale":1.5,"x":-1920,"y":120,"mode":{"width":2560,"height":1440,"refresh_millihz":60000}},"HDMI-A-1":{}}}"#).unwrap();
        assert_eq!(config.outputs["DP-1"].scale, 1.5);
        assert_eq!(config.outputs["DP-1"].x, Some(-1920));
        assert_eq!(config.outputs["DP-1"].mode.as_ref().unwrap().width, 2560);
        assert_eq!(config.outputs["HDMI-A-1"].scale, 1.0);
    }
    #[test]
    fn every_transform_matches_advertised_geometry_and_adjacent_output_spacing() {
        use smithay::utils::Transform as Native;
        for (name, native, expected) in [
            ("normal", Native::Normal, (1707, 960)),
            ("90", Native::_90, (960, 1707)),
            ("180", Native::_180, (1707, 960)),
            ("270", Native::_270, (960, 1707)),
            ("flipped", Native::Flipped, (1707, 960)),
            ("flipped-90", Native::Flipped90, (960, 1707)),
            ("flipped-180", Native::Flipped180, (1707, 960)),
            ("flipped-270", Native::Flipped270, (960, 1707)),
        ] {
            let bytes=serde_json::to_vec(&serde_json::json!({"outputs":{"DP-1":{"scale":1.5,"x":-100,"y":20,"transform":name}}})).unwrap();
            let config = Config::parse(&bytes).unwrap();
            let preference = &config.outputs["DP-1"];
            assert_eq!(preference.transform.native(), native);
            let size = preference.logical_size((2560, 1440).into());
            assert_eq!((size.w, size.h), expected);
            let output = smithay::output::Output::new(
                "test".into(),
                smithay::output::PhysicalProperties {
                    size: (0, 0).into(),
                    subpixel: smithay::output::Subpixel::Unknown,
                    make: "test".into(),
                    model: "test".into(),
                },
            );
            output.change_current_state(
                Some(smithay::output::Mode {
                    size: (2560, 1440).into(),
                    refresh: 60000,
                }),
                Some(native),
                Some(smithay::output::Scale::Fractional(1.5)),
                Some((-100, 20).into()),
            );
            let mut space = smithay::desktop::Space::<smithay::desktop::Window>::default();
            space.map_output(&output, (-100, 20));
            let geometry = space.output_geometry(&output).unwrap();
            assert_eq!(geometry.size, size);
            assert_eq!(
                geometry.loc.x + geometry.size.w,
                preference.x.unwrap() + size.w
            );
        }
        assert_eq!(
            Config::parse(br#"{"outputs":{"DP-1":{}}}"#)
                .unwrap()
                .outputs["DP-1"]
                .transform,
            Transform::Normal
        );
    }
    #[test]
    fn malformed_preferences_fail_before_device_configuration() {
        for value in [
            r#"{"outputs":{"DP-1":{"scale":0}}}"#,
            r#"{"outputs":{"DP-1":{"transform":"45"}}}"#,
            r#"{"outputs":{"DP-1":{"transform":90}}}"#,
            r#"{"outputs":{"DP-1":{"x":1}}}"#,
            r#"{"outputs":{"DP-1":{"x":2147483647,"y":0}}}"#,
            r#"{"outputs":{"DP-1":{"command":"bad"}}}"#,
            r#"{"outputs":{"DP-1":{"mode":{"width":0,"height":1,"refresh_millihz":1}}}}"#,
            r#"{"outputs":{"../path":{}}}"#,
            r#"{"outputs":{},"extra":true}"#,
        ] {
            assert!(Config::parse(value.as_bytes()).is_err(), "{value}");
        }
        assert!(Config::parse(&vec![b' '; 65537]).is_err());
    }
}
