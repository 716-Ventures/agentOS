//! Direct workspace controls compile into the same validated, journaled transaction.
use super::*;
#[derive(Clone, Debug, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Edit {
    Tile {
        surface_id: String,
        output_id: String,
        target: Option<String>,
        axis: String,
        ratio: f64,
    },
    Float {
        surface_id: String,
        output_id: String,
        x: f64,
        y: f64,
        width: f64,
        height: f64,
    },
    Maximize {
        surface_id: String,
    },
    Restore {
        surface_id: String,
    },
    Focus {
        surface_id: String,
        element_id: Option<String>,
    },
    ResizeSplit {
        surface_id: String,
        ratio: f64,
    },
    Swap {
        surface_id: String,
        other: String,
    },
    Remove {
        surface_id: String,
    },
    Pin {
        surface_id: String,
        required: bool,
    },
}
fn has(tile: &Tile, id: &str) -> bool {
    match tile {
        Tile::Leaf { surface_id } => surface_id == id,
        Tile::Split { children, .. } => children.iter().any(|c| has(c, id)),
    }
}
fn remove(tile: Option<Tile>, id: &str) -> Option<Tile> {
    match tile? {
        Tile::Leaf { surface_id } => {
            if surface_id == id {
                None
            } else {
                Some(Tile::Leaf { surface_id })
            }
        }
        Tile::Split {
            axis,
            children,
            ratios,
        } => {
            let kept = children
                .into_iter()
                .zip(ratios)
                .filter_map(|(c, r)| remove(Some(c), id).map(|c| (c, r)))
                .collect::<Vec<_>>();
            if kept.is_empty() {
                None
            } else if kept.len() == 1 {
                Some(kept.into_iter().next().unwrap().0)
            } else {
                let total = kept.iter().map(|(_, r)| r).sum::<f64>();
                let (children, ratios) = kept.into_iter().map(|(c, r)| (c, r / total)).unzip();
                Some(Tile::Split {
                    axis,
                    children,
                    ratios,
                })
            }
        }
    }
}
fn detach(w: &mut WorkspaceDocument, id: &str) {
    for o in w.outputs.values_mut() {
        o.tiles = remove(o.tiles.take(), id);
        o.floating.retain(|f| f.surface_id != id);
        if o.maximized.as_deref() == Some(id) {
            o.maximized = None;
        }
    }
    w.constraints.retain(|c| c.surface_id != id);
    if w.focus.as_ref().map(|f| f.surface_id.as_str()) == Some(id) {
        w.focus = None;
    }
}
fn location(w: &WorkspaceDocument, id: &str) -> Option<String> {
    w.outputs
        .iter()
        .find(|(_, o)| {
            o.tiles.as_ref().map(|t| has(t, id)).unwrap_or(false)
                || o.floating.iter().any(|f| f.surface_id == id)
        })
        .map(|(id, _)| id.clone())
}
fn pin(w: &mut WorkspaceDocument, id: &str, required: bool) -> Result<()> {
    let output =
        location(w, id).ok_or_else(|| error("missing_reference", "Surface is not placed"))?;
    w.constraints.retain(|c| c.surface_id != id);
    if required {
        w.constraints.push(Constraint {
            surface_id: id.into(),
            output_id: output,
            provenance: "direct_manipulation".into(),
            strength: "required".into(),
        });
    }
    Ok(())
}
fn split(tile: &mut Tile, target: &str, id: &str, axis: &str, ratio: f64) -> bool {
    match tile {
        Tile::Leaf { surface_id } if surface_id == target => {
            *tile = Tile::Split {
                axis: axis.into(),
                ratios: vec![1.0 - ratio, ratio],
                children: vec![
                    tile.clone(),
                    Tile::Leaf {
                        surface_id: id.into(),
                    },
                ],
            };
            true
        }
        Tile::Split { children, .. } => children
            .iter_mut()
            .any(|c| split(c, target, id, axis, ratio)),
        _ => false,
    }
}
fn resize(tile: &mut Tile, id: &str, ratio: f64) -> bool {
    match tile {
        Tile::Split {
            children, ratios, ..
        } => {
            if let Some(index) = children
                .iter()
                .position(|c| matches!(c,Tile::Leaf{surface_id} if surface_id==id))
            {
                let rest = 1.0 - ratios[index];
                if rest <= 0.0 {
                    return false;
                }
                for (i, r) in ratios.iter_mut().enumerate() {
                    *r = if i == index {
                        ratio
                    } else {
                        *r * (1.0 - ratio) / rest
                    };
                }
                true
            } else {
                children.iter_mut().any(|c| resize(c, id, ratio))
            }
        }
        _ => false,
    }
}
fn rename(tile: &mut Tile, a: &str, b: &str) {
    match tile {
        Tile::Leaf { surface_id } => {
            if surface_id == a {
                *surface_id = b.into();
            } else if surface_id == b {
                *surface_id = a.into();
            }
        }
        Tile::Split { children, .. } => {
            for c in children {
                rename(c, a, b)
            }
        }
    }
}
pub fn apply(w: &mut WorkspaceDocument, edit: Edit) -> Result<()> {
    match edit {
        Edit::Tile {
            surface_id,
            output_id,
            target,
            axis,
            ratio,
        } => {
            if !["horizontal", "vertical"].contains(&axis.as_str())
                || !ratio.is_finite()
                || !(0.0 < ratio && ratio < 1.0)
            {
                return Err(invalid("Invalid split axis or ratio"));
            }
            let focus = w.focus.clone();
            detach(w, &surface_id);
            let output = w.outputs.entry(output_id).or_insert(OutputLayout {
                tiles: None,
                floating: vec![],
                maximized: None,
            });
            if let Some(target) = target {
                if !output
                    .tiles
                    .as_mut()
                    .map(|t| split(t, &target, &surface_id, &axis, ratio))
                    .unwrap_or(false)
                {
                    return Err(error(
                        "missing_reference",
                        "Split target is not tiled on this output",
                    ));
                }
            } else if let Some(old) = output.tiles.take() {
                output.tiles = Some(Tile::Split {
                    axis,
                    ratios: vec![1.0 - ratio, ratio],
                    children: vec![
                        old,
                        Tile::Leaf {
                            surface_id: surface_id.clone(),
                        },
                    ],
                });
            } else {
                output.tiles = Some(Tile::Leaf {
                    surface_id: surface_id.clone(),
                });
            }
            w.focus = focus;
            pin(w, &surface_id, true)?;
        }
        Edit::Float {
            surface_id,
            output_id,
            x,
            y,
            width,
            height,
        } => {
            let focus = w.focus.clone();
            detach(w, &surface_id);
            w.outputs
                .entry(output_id)
                .or_insert(OutputLayout {
                    tiles: None,
                    floating: vec![],
                    maximized: None,
                })
                .floating
                .push(Floating {
                    surface_id: surface_id.clone(),
                    x,
                    y,
                    width,
                    height,
                });
            w.focus = focus;
            pin(w, &surface_id, true)?;
        }
        Edit::Maximize { surface_id } => {
            let output = location(w, &surface_id)
                .ok_or_else(|| error("missing_reference", "Surface is not placed"))?;
            w.outputs.get_mut(&output).unwrap().maximized = Some(surface_id);
        }
        Edit::Restore { surface_id } => {
            if location(w, &surface_id).is_none() {
                return Err(error("missing_reference", "Surface is not placed"));
            }
            for o in w.outputs.values_mut() {
                if o.maximized.as_deref() == Some(&surface_id) {
                    o.maximized = None;
                }
            }
        }
        Edit::Focus {
            surface_id,
            element_id,
        } => {
            w.focus = Some(Focus {
                surface_id,
                element_id,
            });
        }
        Edit::ResizeSplit { surface_id, ratio } => {
            if !ratio.is_finite() || !(0.0 < ratio && ratio < 1.0) {
                return Err(invalid("Invalid split ratio"));
            }
            if !w.outputs.values_mut().any(|o| {
                o.tiles
                    .as_mut()
                    .map(|t| resize(t, &surface_id, ratio))
                    .unwrap_or(false)
            }) {
                return Err(error("missing_reference", "Surface has no split to resize"));
            }
            pin(w, &surface_id, true)?;
        }
        Edit::Swap { surface_id, other } => {
            if surface_id == other
                || location(w, &surface_id).is_none()
                || location(w, &other).is_none()
            {
                return Err(error(
                    "missing_reference",
                    "Swap requires two distinct placed surfaces",
                ));
            }
            for o in w.outputs.values_mut() {
                if let Some(t) = &mut o.tiles {
                    rename(t, &surface_id, &other);
                }
                for f in &mut o.floating {
                    if f.surface_id == surface_id {
                        f.surface_id = other.clone();
                    } else if f.surface_id == other {
                        f.surface_id = surface_id.clone();
                    }
                }
                if let Some(max) = &mut o.maximized {
                    if max == &surface_id {
                        *max = other.clone();
                    } else if max == &other {
                        *max = surface_id.clone();
                    }
                }
            }
            pin(w, &surface_id, true)?;
            pin(w, &other, true)?;
        }
        Edit::Remove { surface_id } => {
            if location(w, &surface_id).is_none() {
                return Err(error("missing_reference", "Surface is not placed"));
            }
            detach(w, &surface_id);
        }
        Edit::Pin {
            surface_id,
            required,
        } => pin(w, &surface_id, required)?,
    }
    Ok(())
}

/// Compare effective placement without coupling protection to a particular tree shape.
pub fn placement(w: &WorkspaceDocument, id: &str) -> Option<Value> {
    fn find(tile: &Tile, id: &str, rect: [f64; 4]) -> Option<[f64; 4]> {
        match tile {
            Tile::Leaf { surface_id } => (surface_id == id).then_some(rect),
            Tile::Split {
                axis,
                children,
                ratios,
            } => {
                let mut offset = 0.0;
                for (child, ratio) in children.iter().zip(ratios) {
                    let mut next = rect;
                    let (position, extent) = if axis == "horizontal" { (0, 2) } else { (1, 3) };
                    next[position] += offset * rect[extent];
                    next[extent] *= ratio;
                    if let Some(found) = find(child, id, next) {
                        return Some(found);
                    }
                    offset += ratio;
                }
                None
            }
        }
    }
    for (output, layout) in &w.outputs {
        let maximized = layout.maximized.as_deref() == Some(id);
        if let Some(f) = layout.floating.iter().find(|f| f.surface_id == id) {
            return Some(
                json!({"output":output,"mode":"floating","rect":[f.x,f.y,f.width,f.height],"maximized":maximized}),
            );
        }
        if let Some(rect) = layout
            .tiles
            .as_ref()
            .and_then(|t| find(t, id, [0.0, 0.0, 1.0, 1.0]))
        {
            return Some(json!({"output":output,"mode":"tiled","rect":rect,"maximized":maximized}));
        }
    }
    None
}

pub fn surfaces(w: &WorkspaceDocument) -> BTreeSet<String> {
    fn walk(tile: &Tile, ids: &mut BTreeSet<String>) {
        match tile {
            Tile::Leaf { surface_id } => {
                ids.insert(surface_id.clone());
            }
            Tile::Split { children, .. } => {
                for child in children {
                    walk(child, ids)
                }
            }
        }
    }
    let mut ids = BTreeSet::new();
    for layout in w.outputs.values() {
        if let Some(tile) = &layout.tiles {
            walk(tile, &mut ids)
        }
        ids.extend(layout.floating.iter().map(|f| f.surface_id.clone()));
    }
    ids
}
