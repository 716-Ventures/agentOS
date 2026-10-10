//! Original agentOS layout policy, Apache-2.0. Independent of client rendering.
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Rect {
    pub x: i32,
    pub y: i32,
    pub width: i32,
    pub height: i32,
}
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "mode", rename_all = "snake_case", deny_unknown_fields)]
pub enum Placement {
    Tiled,
    Floating { rect: Rect },
    Maximized,
}
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Layout {
    pub revision: u64,
    pub order: Vec<String>,
    pub placements: BTreeMap<String, Placement>,
    pub focus: Option<String>,
}
#[derive(Default)]
pub struct Policy {
    pub current: Layout,
    history: Vec<Layout>,
}
impl Policy {
    pub fn synchronize(&mut self, windows: &[String]) {
        let live = windows.iter().cloned().collect::<BTreeSet<_>>();
        let before = self.current.clone();
        self.current.order.retain(|id| live.contains(id));
        self.current.placements.retain(|id, _| live.contains(id));
        for id in windows {
            if !self.current.placements.contains_key(id) {
                self.current.placements.insert(id.clone(), Placement::Tiled);
                self.current.order.push(id.clone());
            }
        }
        if self
            .current
            .focus
            .as_ref()
            .map(|id| !live.contains(id))
            .unwrap_or(false)
        {
            self.current.focus = None;
        }
        // New windows are placed but never activated automatically.
        if self.current != before {
            self.current.revision += 1;
        }
    }
    pub fn change(&mut self, id: &str, placement: Placement, expected: u64) -> Result<(), String> {
        if expected != self.current.revision {
            return Err("Layout changed; refresh before applying".into());
        }
        if !self.current.placements.contains_key(id) {
            return Err("Window unavailable".into());
        }
        if let Placement::Floating { rect } = placement {
            if rect.width < 80 || rect.height < 32 {
                return Err("Window below its minimum size".into());
            }
        }
        self.history.push(self.current.clone());
        if self.history.len() > 32 {
            self.history.remove(0);
        }
        self.current.placements.insert(id.into(), placement);
        self.current.revision += 1;
        Ok(())
    }
    pub fn undo(&mut self) -> Result<(), String> {
        let before = self.history.pop().ok_or("No layout change to undo")?;
        if before.order.iter().collect::<BTreeSet<_>>()
            != self.current.order.iter().collect::<BTreeSet<_>>()
        {
            return Err("Window set changed; layout undo would diverge".into());
        }
        let revision = self.current.revision + 1;
        self.current = before;
        self.current.revision = revision;
        Ok(())
    }
    pub fn arrange(&self, area: Rect) -> BTreeMap<String, Rect> {
        let tiled = self
            .current
            .order
            .iter()
            .filter(|id| matches!(self.current.placements.get(*id), Some(Placement::Tiled)))
            .collect::<Vec<_>>();
        let mut result = BTreeMap::new();
        let count = tiled.len() as i32;
        if count > 0 {
            // Prefer columns when they fit; small displays use a balanced grid.
            let columns = count.min((area.width / 320).max(1));
            let rows = (count + columns - 1) / columns;
            for (i, id) in tiled.into_iter().enumerate() {
                let i = i as i32;
                let col = i % columns;
                let row = i / columns;
                let x = area.width * col / columns;
                let y = area.height * row / rows;
                result.insert(
                    id.clone(),
                    Rect {
                        x: area.x + x,
                        y: area.y + y,
                        width: area.width * (col + 1) / columns - x,
                        height: area.height * (row + 1) / rows - y,
                    },
                );
            }
        }
        for (id, placement) in &self.current.placements {
            match placement {
                Placement::Floating { rect } => {
                    let width = rect.width.min(area.width).max(1);
                    let height = rect.height.min(area.height).max(1);
                    result.insert(
                        id.clone(),
                        Rect {
                            x: rect.x.clamp(area.x, area.x + area.width - width),
                            y: rect.y.clamp(area.y, area.y + area.height - height),
                            width,
                            height,
                        },
                    );
                }
                Placement::Maximized => {
                    result.insert(id.clone(), area);
                }
                _ => {}
            }
        }
        result
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn new_window_does_not_steal_focus() {
        let mut p = Policy::default();
        p.synchronize(&["a".into()]);
        p.current.focus = Some("a".into());
        p.synchronize(&["a".into(), "b".into()]);
        assert_eq!(p.current.focus.as_deref(), Some("a"));
    }
    #[test]
    fn exact_revisions_and_divergent_undo() {
        let mut p = Policy::default();
        p.synchronize(&["a".into()]);
        assert!(p.change("a", Placement::Maximized, 0).is_err());
        p.change("a", Placement::Maximized, 1).unwrap();
        p.synchronize(&["a".into(), "b".into()]);
        assert!(p.undo().is_err());
        assert_eq!(p.current.order.len(), 2);
    }
    #[test]
    fn floating_windows_survive_smaller_output() {
        let mut p = Policy::default();
        p.synchronize(&["a".into()]);
        p.change(
            "a",
            Placement::Floating {
                rect: Rect {
                    x: 900,
                    y: 700,
                    width: 500,
                    height: 400,
                },
            },
            1,
        )
        .unwrap();
        let area = Rect {
            x: 0,
            y: 0,
            width: 320,
            height: 240,
        };
        assert_eq!(p.arrange(area)["a"], area);
    }
    #[test]
    fn grid_is_in_bounds_and_has_no_overlap() {
        for count in 1..50 {
            let mut p = Policy::default();
            p.synchronize(&(0..count).map(|i| i.to_string()).collect::<Vec<_>>());
            let area = Rect {
                x: 10,
                y: 20,
                width: 1280,
                height: 800,
            };
            let rects = p.arrange(area);
            for (id, a) in &rects {
                assert!(
                    a.x >= area.x
                        && a.y >= area.y
                        && a.x + a.width <= 1290
                        && a.y + a.height <= 820
                );
                for (other, b) in &rects {
                    if id != other {
                        assert!(
                            a.x + a.width <= b.x
                                || b.x + b.width <= a.x
                                || a.y + a.height <= b.y
                                || b.y + b.height <= a.y
                        );
                    }
                }
            }
        }
    }
}
