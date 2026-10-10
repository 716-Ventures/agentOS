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
    pub x: Option<i32>,
    pub y: Option<i32>,
    pub mode: Option<Mode>,
}
impl Default for Preference {
    fn default() -> Self {
        Self {
            scale: 1.0,
            x: None,
            y: None,
            mode: None,
        }
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
    fn malformed_preferences_fail_before_device_configuration() {
        for value in [
            r#"{"outputs":{"DP-1":{"scale":0}}}"#,
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
