//! Native presentation contract. Documents are inert, not execution authority.
use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};

mod workspace;

type Result<T> = std::result::Result<T, String>;
pub const PROTOCOL: &str = "agentos.presentation/1";
pub const CATALOG: &str = "native-core/1";
const DOCUMENT_LIMIT: usize = 1024 * 1024;
const TRANSACTION_LIMIT: usize = 4 * DOCUMENT_LIMIT;
fn error(kind: &str, detail: impl std::fmt::Display) -> String {
    json!({"code":kind,"detail":detail.to_string()}).to_string()
}
fn invalid(detail: impl std::fmt::Display) -> String {
    error("invalid_document", detail)
}
fn db_error(e: impl std::fmt::Display) -> String {
    error("storage_error", e)
}
fn decode<T: serde::de::DeserializeOwned>(v: Value) -> Result<T> {
    serde_json::from_value(v).map_err(invalid)
}
fn now() -> i64 {
    super::now()
}
fn ident(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 128
        && s.bytes()
            .all(|c| c.is_ascii_alphanumeric() || b"_-:.".contains(&c))
}
#[derive(Clone, Debug)]
pub struct Principal {
    pub uid: u32,
    pub session: String,
}
impl Principal {
    fn human(&self) -> bool {
        self.uid == 0 || self.uid >= 1000
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Element {
    #[serde(rename = "type")]
    pub kind: String,
    #[serde(default)]
    pub props: BTreeMap<String, Value>,
    #[serde(default)]
    pub slots: BTreeMap<String, Vec<String>>,
    #[serde(default)]
    pub events: BTreeMap<String, Event>,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Event {
    pub action: String,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Binding {
    pub source: String,
    pub path: String,
    pub access: String,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Action {
    #[serde(rename = "ref")]
    pub reference: String,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub parameters: BTreeMap<String, Parameter>,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Parameter {
    Literal { value: Value },
    Field { element_id: String },
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct SurfaceDocument {
    pub protocol: String,
    pub catalog_revision: String,
    pub surface_id: String,
    pub activity_id: String,
    pub revision: u64,
    pub title: String,
    pub root: String,
    pub elements: BTreeMap<String, Element>,
    pub bindings: BTreeMap<String, Binding>,
    pub actions: BTreeMap<String, Action>,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Tile {
    Leaf {
        surface_id: String,
    },
    Split {
        axis: String,
        ratios: Vec<f64>,
        children: Vec<Tile>,
    },
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Floating {
    pub surface_id: String,
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct OutputLayout {
    pub tiles: Option<Tile>,
    pub floating: Vec<Floating>,
    pub maximized: Option<String>,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Focus {
    pub surface_id: String,
    pub element_id: Option<String>,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Constraint {
    pub surface_id: String,
    pub output_id: String,
    pub provenance: String,
    pub strength: String,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct WorkspaceDocument {
    pub protocol: String,
    pub workspace_id: String,
    pub activity_id: String,
    pub revision: u64,
    pub outputs: BTreeMap<String, OutputLayout>,
    pub constraints: Vec<Constraint>,
    pub focus: Option<Focus>,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(untagged)]
enum Document {
    Surface(SurfaceDocument),
    Workspace(WorkspaceDocument),
}
impl Document {
    fn activity(&self) -> &str {
        match self {
            Self::Surface(s) => &s.activity_id,
            Self::Workspace(w) => &w.activity_id,
        }
    }
    fn revision(&self) -> u64 {
        match self {
            Self::Surface(s) => s.revision,
            Self::Workspace(w) => w.revision,
        }
    }
    fn set_revision(&mut self, r: u64) {
        match self {
            Self::Surface(s) => s.revision = r,
            Self::Workspace(w) => w.revision = r,
        }
    }
}
#[derive(Clone, Debug, Deserialize)]
#[serde(tag = "op", deny_unknown_fields)]
enum Operation {
    #[serde(rename = "surface.create")]
    Create { document: SurfaceDocument },
    #[serde(rename = "surface.replace")]
    Replace { document: SurfaceDocument },
    #[serde(rename = "surface.close")]
    Close { surface_id: String },
    #[serde(rename = "element.put")]
    Put {
        surface_id: String,
        element_id: String,
        element: Element,
    },
    #[serde(rename = "element.remove")]
    Remove {
        surface_id: String,
        element_id: String,
    },
    #[serde(rename = "element.set_props")]
    Props {
        surface_id: String,
        element_id: String,
        props: BTreeMap<String, Value>,
    },
    #[serde(rename = "draft.commit")]
    CommitDraft {
        surface_id: String,
        element_id: String,
        expected_draft_revision: i64,
    },
    #[serde(rename = "element.set_children")]
    Children {
        surface_id: String,
        element_id: String,
        slot: String,
        children: Vec<String>,
    },
    #[serde(rename = "binding.attach")]
    Bind {
        surface_id: String,
        binding_id: String,
        binding: Binding,
    },
    #[serde(rename = "binding.detach")]
    Unbind {
        surface_id: String,
        binding_id: String,
    },
    #[serde(rename = "action.attach")]
    Action {
        surface_id: String,
        action_id: String,
        action: Action,
    },
    #[serde(rename = "action.detach")]
    Unaction {
        surface_id: String,
        action_id: String,
    },
    #[serde(rename = "workspace.edit")]
    WorkspaceEdit {
        workspace_id: String,
        edit: workspace::Edit,
    },
    #[serde(rename = "workspace.navigate")]
    Navigate {
        workspace_id: String,
        surface_id: String,
        element_id: String,
        source_revision: u64,
    },
    #[serde(rename = "workspace.put")]
    Workspace { document: WorkspaceDocument },
}
impl Operation {
    fn id(&self) -> &str {
        match self {
            Self::Create { document } | Self::Replace { document } => &document.surface_id,
            Self::Workspace { document } => &document.workspace_id,
            Self::WorkspaceEdit { workspace_id, .. } | Self::Navigate { workspace_id, .. } => {
                workspace_id
            }
            Self::Close { surface_id }
            | Self::Put { surface_id, .. }
            | Self::Remove { surface_id, .. }
            | Self::Props { surface_id, .. }
            | Self::CommitDraft { surface_id, .. }
            | Self::Children { surface_id, .. }
            | Self::Bind { surface_id, .. }
            | Self::Unbind { surface_id, .. }
            | Self::Action { surface_id, .. }
            | Self::Unaction { surface_id, .. } => surface_id,
        }
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Apply {
    op: String,
    protocol: String,
    request_id: String,
    catalog_revision: String,
    expected_revisions: BTreeMap<String, Option<u64>>,
    operations: Vec<Operation>,
}

/// Catalog schemas are also the validator's source of truth.
pub fn catalog() -> Value {
    json!({"protocol":PROTOCOL,"catalog_revision":CATALOG,
    "limits":{"document_bytes":DOCUMENT_LIMIT,"transaction_bytes":TRANSACTION_LIMIT,"elements":2048,"depth":32,"operations":128},
    "components":seven_sixteen_ui::catalog::components(),
    "sources":{"discovery":"source.list","job:":["/status","/exit_code","/error","/created_at","/finished_at"],"broker:":["/status","/exit_code","/error","/created_at","/finished_at"],"window:":["/title","/app_id","/availability"],"file:":["/path","/kind","/size_bytes","/modified_at","/mode","/measured_at","/size_text","/modified_text","/mode_text"]},
    "action_parameters":{"kinds":[{"kind":"literal","value":"Typed host-schema value"},{"kind":"field","element_id":"TextField@1 identity"}],"schema_source":"action.metadata.parameter_schema","submission":"Authenticated native input; exact surface and source revisions; no expressions"}})
}

fn walk_elements(
    id: &str,
    s: &SurfaceDocument,
    seen: &mut BTreeSet<String>,
    depth: usize,
) -> Result<()> {
    if depth > 32 {
        return Err(error("resource_limit", "Element depth exceeds 32"));
    }
    if !seen.insert(id.into()) {
        return Err(invalid("Cyclic or multiply parented element"));
    }
    let node = s
        .elements
        .get(id)
        .ok_or_else(|| error("missing_reference", id))?;
    let catalog = catalog();
    let schema = &catalog["components"][&node.kind];
    if schema.is_null() {
        return Err(error("unsupported_component", &node.kind));
    }
    for required in schema["required"].as_array().into_iter().flatten() {
        if !node.props.contains_key(required.as_str().unwrap()) {
            return Err(invalid("Required component property missing"));
        }
    }
    for (key, value) in &node.props {
        let spec = &schema["props"][key];
        if spec.is_null() {
            return Err(invalid(format!("Unknown property {key}")));
        }
        if let Some(binding) = value.as_object() {
            if binding.len() != 1
                || !schema["bindable"]
                    .as_array()
                    .map(|a| a.contains(&json!(key)))
                    .unwrap_or(false)
            {
                return Err(invalid("Property does not accept a binding"));
            }
            let name = binding
                .get("binding")
                .and_then(Value::as_str)
                .ok_or_else(|| invalid("Invalid binding"))?;
            let bound = s
                .bindings
                .get(name)
                .ok_or_else(|| error("missing_reference", name))?;
            let source_type = match bound.path.as_str() {
                "/status" | "/error" | "/title" | "/app_id" | "/availability" | "/path"
                | "/kind" | "/size_text" | "/modified_text" | "/mode_text" => "string",
                _ => "number",
            };
            if spec.as_str() != Some(source_type) {
                return Err(invalid(
                    "Binding source type is incompatible with this property",
                ));
            }
        } else {
            let valid = if let Some(options) = spec.as_array() {
                options.contains(value)
            } else {
                match spec.as_str() {
                    Some("string") => value
                        .as_str()
                        .map(|x| x.len() <= 65536 && !x.contains('\0'))
                        .unwrap_or(false),
                    Some("boolean") => value.is_boolean(),
                    Some("number") => value
                        .as_f64()
                        .map(|x| x.is_finite() && (0.0..=1.0).contains(&x))
                        .unwrap_or(false),
                    Some(kind @ ("richruns" | "chartpoints")) => {
                        seven_sixteen_ui::content::valid_literal(kind, value)
                    }
                    Some(kind @ ("stringlist" | "keyedrows")) => {
                        seven_sixteen_ui::catalog::valid_collection(kind, value)
                    }
                    _ => false,
                }
            };
            if !valid {
                return Err(invalid(format!("Invalid value for {key}")));
            }
        }
    }
    for label in ["label", "recovery_label"]
        .iter()
        .filter_map(|key| node.props.get(*key).and_then(Value::as_str))
    {
        if label.trim().is_empty() || label.len() > 256 || label.contains('\0') {
            return Err(invalid("A bounded accessible label is required"));
        }
    }
    if ["Table@1", "List@1", "KeyValue@1"].contains(&node.kind.as_str()) {
        let columns = match node.kind.as_str() {
            "Table@1" => node.props["columns"].as_array().unwrap().len(),
            "List@1" => 1,
            _ => 2,
        };
        if node.props["rows"]
            .as_array()
            .unwrap()
            .iter()
            .any(|row| row["cells"].as_array().unwrap().len() != columns)
        {
            return Err(invalid("Collection cell count must match its schema"));
        }
    }
    if node.kind == "Choice@1" {
        let options = node.props["options"].as_array().unwrap();
        let mut unique = BTreeSet::new();
        if options.iter().any(|value| {
            value.as_str().unwrap().trim().is_empty() || !unique.insert(value.as_str().unwrap())
        }) || !options.contains(&node.props["value"])
        {
            return Err(invalid(
                "Choice requires distinct meaningful options and an exact selected value",
            ));
        }
    }
    if node.kind == "Tabs@1" {
        let labels = node.props["labels"].as_array().unwrap();
        if node.slots.get("children").map(Vec::len) != Some(labels.len())
            || labels
                .iter()
                .any(|label| label.as_str().unwrap().trim().is_empty())
        {
            return Err(invalid("Tabs require one meaningful label per child"));
        }
    }
    if node.kind == "Split@1" && node.slots.get("children").map(Vec::len) != Some(2) {
        return Err(invalid("Split requires exactly two children"));
    }
    if is_reference(&node.kind) && !ident(node.props["target"].as_str().unwrap()) {
        return Err(invalid("Reference requires a local view identity"));
    }
    if node.kind == "Link@1" {
        let url = node.props["url"].as_str().unwrap();
        if !(url.starts_with("https://")
            || url.starts_with("http://")
            || url.starts_with("mailto:"))
            || url.chars().any(char::is_control)
        {
            return Err(invalid("Link scheme is not supported"));
        }
    }
    for (slot, children) in &node.slots {
        let sizes = &schema["slots"][slot];
        if sizes.is_null()
            || children.len() < sizes[0].as_u64().unwrap() as usize
            || children.len() > sizes[1].as_u64().unwrap() as usize
        {
            return Err(invalid("Unsupported slot or cardinality"));
        }
        for child in children {
            walk_elements(child, s, seen, depth + 1)?
        }
    }
    for (name, event) in &node.events {
        if !schema["events"]
            .as_array()
            .map(|a| a.contains(&json!(name)))
            .unwrap_or(false)
        {
            return Err(invalid("Unknown event"));
        }
        if !s.actions.contains_key(&event.action) {
            return Err(error("missing_reference", &event.action));
        }
    }
    Ok(())
}
fn surface_valid(db: &Connection, s: &SurfaceDocument, _principal: &Principal) -> Result<()> {
    if s.protocol != PROTOCOL || s.catalog_revision != CATALOG {
        return Err(error("unsupported_protocol", "Protocol/catalog mismatch"));
    }
    if !ident(&s.surface_id) || !ident(&s.root) || s.title.len() > 1024 {
        return Err(invalid("Invalid surface identity/title"));
    }
    if s.elements.is_empty() || s.elements.len() > 2048 {
        return Err(error("resource_limit", "Element count outside limits"));
    }
    if s.elements
        .keys()
        .chain(s.bindings.keys())
        .chain(s.actions.keys())
        .any(|k| !ident(k))
    {
        return Err(invalid("Invalid element/binding/action identity"));
    }
    let mut seen = BTreeSet::new();
    walk_elements(&s.root, s, &mut seen, 1)?;
    if seen.len() != s.elements.len() {
        return Err(invalid("Unreachable elements"));
    }
    for element in s
        .elements
        .values()
        .filter(|node| node.kind == "PtySession@1")
    {
        let source = element.props["source"].as_str().unwrap();
        if !source.strip_prefix("broker:").is_some_and(ident)
            || crate::presentation_sources::activity(db, source)
                .map_err(db_error)?
                .as_deref()
                != Some(s.activity_id.as_str())
        {
            return Err(error(
                "missing_reference",
                "PTY source must name registered work in this activity",
            ));
        }
    }
    for element in s.elements.values().filter(|node| node.kind == "Image@1") {
        if crate::presentation_resources::activity(
            db,
            element.props["reference"].as_str().unwrap(),
        )?
        .as_deref()
            != Some(s.activity_id.as_str())
        {
            return Err(error(
                "missing_reference",
                "Image resource unavailable in this activity",
            ));
        }
    }
    for binding in s.bindings.values() {
        let paths = if binding.source.starts_with("file:") {
            &[
                "/path",
                "/kind",
                "/size_bytes",
                "/modified_at",
                "/mode",
                "/measured_at",
                "/size_text",
                "/modified_text",
                "/mode_text",
            ][..]
        } else if binding.source.starts_with("window:") {
            &["/title", "/app_id", "/availability"][..]
        } else {
            &[
                "/status",
                "/exit_code",
                "/error",
                "/created_at",
                "/finished_at",
            ][..]
        };
        if binding.access != "read" || !paths.contains(&binding.path.as_str()) {
            return Err(invalid(
                "Only registered typed read-only fields are bindable",
            ));
        }
        if let Some(id) = binding.source.strip_prefix("window:") {
            if crate::presentation_hosts::activity(db, id)?.as_deref()
                != Some(s.activity_id.as_str())
            {
                return Err(error(
                    "unauthorized",
                    "Window source is absent or belongs to another activity",
                ));
            }
            continue;
        }
        if binding.source.starts_with("broker:") || binding.source.starts_with("file:") {
            if crate::presentation_sources::activity(db, &binding.source)?.as_deref()
                != Some(s.activity_id.as_str())
            {
                return Err(error(
                    "unauthorized",
                    "Broker source is absent or belongs to another activity",
                ));
            }
            continue;
        }
        let id = binding
            .source
            .strip_prefix("job:")
            .and_then(|x| x.parse::<i64>().ok())
            .ok_or_else(|| error("missing_reference", &binding.source))?;
        let activity: Option<i64> = db
            .query_row("SELECT activity_id FROM jobs WHERE id=?", [id], |r| {
                r.get(0)
            })
            .optional()
            .map_err(db_error)?;
        let known: bool = db
            .query_row(
                "SELECT EXISTS(SELECT 1 FROM presentation_sources WHERE source=? AND activity=?)",
                params![binding.source, s.activity_id],
                |r| r.get(0),
            )
            .map_err(db_error)?;
        if activity.map(|x| x.to_string()) != Some(s.activity_id.clone()) && !known {
            return Err(error(
                "unauthorized",
                "Job is absent or belongs to another activity",
            ));
        }
    }
    for action in s.actions.values() {
        let metadata = crate::presentation_actions::metadata(db, &action.reference)?;
        let schema = &metadata["parameter_schema"];
        for (key, parameter) in &action.parameters {
            if schema[key].is_null() {
                return Err(invalid("Callback parameter is not in the host schema"));
            }
            match parameter {
                Parameter::Field { element_id } => {
                    if s.elements.get(element_id).map(|e| e.kind.as_str()) != Some("TextField@1") {
                        return Err(invalid(
                            "Callback parameters must reference an editable field",
                        ));
                    }
                }
                Parameter::Literal { value } => {
                    crate::presentation_actions::validate_parameters(
                        metadata["operation"].as_str().unwrap_or(""),
                        &serde_json::Map::from_iter([(key.clone(), value.clone())]),
                    )?;
                }
            }
        }
        let allowed:bool=db.query_row("SELECT EXISTS(SELECT 1 FROM presentation_actions WHERE reference=? AND activity=?)",params![action.reference,s.activity_id],|r|r.get(0)).map_err(db_error)?;
        if !allowed {
            return Err(error(
                "unauthorized",
                "Action reference is absent, revoked or not scoped to this principal/activity",
            ));
        }
    }
    Ok(())
}
fn tile_valid(
    t: &Tile,
    seen: &mut BTreeSet<String>,
    depth: usize,
    width: f64,
    height: f64,
) -> Result<()> {
    if depth > 32 {
        return Err(error("resource_limit", "Tile depth exceeds 32"));
    }
    match t {
        Tile::Leaf { surface_id } => {
            if width < 80.0 || height < 32.0 {
                return Err(error(
                    "constraint_conflict",
                    "Tile is below minimum usable size",
                ));
            }
            if !seen.insert(surface_id.clone()) {
                return Err(invalid("Surface placed more than once"));
            }
        }
        Tile::Split {
            axis,
            ratios,
            children,
        } => {
            if !["horizontal", "vertical"].contains(&axis.as_str())
                || children.len() < 2
                || ratios.len() != children.len()
                || ratios.iter().any(|r| !r.is_finite() || *r <= 0.0)
                || (ratios.iter().sum::<f64>() - 1.0).abs() > 1e-6
            {
                return Err(invalid("Invalid tile split/ratios"));
            }
            for (child, r) in children.iter().zip(ratios) {
                tile_valid(
                    child,
                    seen,
                    depth + 1,
                    if axis == "horizontal" {
                        width * r
                    } else {
                        width
                    },
                    if axis == "vertical" {
                        height * r
                    } else {
                        height
                    },
                )?
            }
        }
    }
    Ok(())
}
fn validate(
    db: &Connection,
    docs: &BTreeMap<String, Document>,
    principal: &Principal,
) -> Result<()> {
    let mut placed = BTreeSet::new();
    let mut image_pixels = BTreeMap::<String, u64>::new();
    let mut dimensions = BTreeMap::<String, u64>::new();
    for d in docs.values() {
        if serde_json::to_vec(d).map_err(invalid)?.len() > DOCUMENT_LIMIT {
            return Err(error("resource_limit", "Document exceeds 1 MiB"));
        }
        let active:bool=db.query_row("SELECT EXISTS(SELECT 1 FROM activities WHERE CAST(id AS TEXT)=? AND id NOT IN (SELECT activity_id FROM removed_activities))",[d.activity()],|r|r.get(0)).map_err(db_error)?;
        if !active {
            continue;
        }
        match d {
            Document::Surface(s) => {
                surface_valid(db, s, principal)?;
                // Count every rendered occurrence: reusing one resource in many
                // elements still allocates a native texture for each view.
                for element in s
                    .elements
                    .values()
                    .filter(|element| element.kind == "Image@1")
                {
                    let reference = element.props["reference"].as_str().unwrap();
                    let pixels = if let Some(pixels) = dimensions.get(reference) {
                        *pixels
                    } else {
                        let (width, height): (u32, u32) = db
                            .query_row(
                                "SELECT width,height FROM presentation_resources WHERE reference=?",
                                [reference],
                                |r| Ok((r.get(0)?, r.get(1)?)),
                            )
                            .map_err(db_error)?;
                        let pixels = u64::from(width) * u64::from(height);
                        dimensions.insert(reference.into(), pixels);
                        pixels
                    };
                    let total = image_pixels.entry(s.activity_id.clone()).or_default();
                    *total = total
                        .checked_add(pixels)
                        .ok_or_else(|| error("resource_limit", "Image pixel budget overflow"))?;
                    if *total > 16 * 1024 * 1024 {
                        return Err(error(
                            "resource_limit",
                            "Rendered images exceed the activity's 16 MiPixel budget",
                        ));
                    }
                }

                for (id, element) in s.elements.iter().filter(|(_, e)| is_reference(&e.kind)) {
                    let target = element.props["target"].as_str().unwrap();
                    if reference_target(db, docs, s, element).is_err() {
                        // An existing reference can outlive its target. Preserve its
                        // disabled representation without preventing user closure.
                        let old: Option<String> = db
                            .query_row(
                                "SELECT body FROM presentation_documents WHERE id=?",
                                [&s.surface_id],
                                |r| r.get(0),
                            )
                            .optional()
                            .map_err(db_error)?;
                        let retained = old
                            .and_then(|raw| serde_json::from_str::<SurfaceDocument>(&raw).ok())
                            .and_then(|old| old.elements.get(id).cloned())
                            .is_some_and(|old| {
                                old.kind == element.kind
                                    && old.props.get("target").and_then(Value::as_str)
                                        == Some(target)
                            });
                        if !retained {
                            return Err(error(
                                "missing_reference",
                                "Reference target must exist in the same activity",
                            ));
                        }
                    }
                }
            }
            Document::Workspace(w) => {
                if w.protocol != PROTOCOL || !ident(&w.workspace_id) {
                    return Err(invalid("Workspace protocol/identity mismatch"));
                }
                let previous: Option<String> = db
                    .query_row(
                        "SELECT body FROM presentation_documents WHERE id=?",
                        [&w.workspace_id],
                        |r| r.get(0),
                    )
                    .optional()
                    .map_err(db_error)?;
                let previous = previous
                    .map(|body| serde_json::from_str::<Document>(&body).map_err(db_error))
                    .transpose()?;
                let previous = match &previous {
                    Some(Document::Workspace(w)) => Some(w),
                    _ => None,
                };
                let mut local = BTreeSet::new();
                let mut locations = BTreeMap::new();
                for (output, layout) in &w.outputs {
                    let unchanged = previous
                        .and_then(|w| w.outputs.get(output))
                        .is_some_and(|old| workspace::removes_only(old, layout));
                    let size: Option<(f64, f64, bool,Option<String>)> = db
                        .query_row(
                            "SELECT o.width,o.height,o.connected,s.session FROM presentation_outputs o LEFT JOIN presentation_output_observations s USING(id) WHERE o.id=?",
                            [output],
                            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?,r.get(3)?)),
                        )
                        .optional()
                        .map_err(db_error)?;
                    let (width, height, connected, owner) = size.ok_or_else(|| {
                        error("missing_reference", format!("Output {output} unavailable"))
                    })?;
                    let connected = connected
                        && !owner.as_deref().is_some_and(|s| {
                            s.split_once(':').is_some_and(|(pid, start)| {
                                pid.parse::<u32>().is_ok() && start.parse::<u64>().is_ok()
                            }) && !crate::presentation_hosts::alive(s)
                        });
                    if !connected && !unchanged {
                        return Err(error(
                            "missing_reference",
                            format!(
                                "Output {output} is disconnected; preferred placement was retained"
                            ),
                        ));
                    }
                    let before = local.clone();
                    if let Some(t) = &layout.tiles {
                        tile_valid(
                            t,
                            &mut local,
                            1,
                            if unchanged { f64::INFINITY } else { width },
                            if unchanged { f64::INFINITY } else { height },
                        )?
                    }
                    for f in &layout.floating {
                        if ![f.x, f.y, f.width, f.height].iter().all(|v| v.is_finite())
                            || f.width < 80.0
                            || f.height < 32.0
                            || f.x < 0.0
                            || f.y < 0.0
                            || (!unchanged && (f.x + f.width > width || f.y + f.height > height))
                        {
                            return Err(error(
                                "constraint_conflict",
                                "Floating rectangle outside work area or below minimum",
                            ));
                        }
                        if !local.insert(f.surface_id.clone()) {
                            return Err(invalid("Duplicate surface placement"));
                        }
                    }
                    let added: Vec<_> = local.difference(&before).cloned().collect();
                    for id in &added {
                        locations.insert(id.clone(), output.clone());
                    }
                    if let Some(max) = &layout.maximized {
                        if !added.contains(max) {
                            return Err(error(
                                "missing_reference",
                                "Maximized surface is not on this output",
                            ));
                        }
                    }
                }
                for id in &local {
                    if !placed.insert(id.clone()) {
                        return Err(invalid("Surface belongs to more than one workspace"));
                    }
                    match docs.get(id) {
                        Some(Document::Surface(s)) if s.activity_id == w.activity_id => {}
                        _ if crate::presentation_hosts::activity(db, id)?.as_deref()
                            == Some(w.activity_id.as_str()) => {}
                        _ => {
                            return Err(error(
                                "missing_reference",
                                format!("Surface {id} absent or in another activity"),
                            ))
                        }
                    }
                }
                for c in &w.constraints {
                    if ![
                        "explicit_request",
                        "direct_manipulation",
                        "inferred_preference",
                    ]
                    .contains(&c.provenance.as_str())
                        || !["required", "preferred"].contains(&c.strength.as_str())
                    {
                        return Err(invalid("Invalid constraint provenance/strength"));
                    }
                    if !local.contains(&c.surface_id) || !w.outputs.contains_key(&c.output_id) {
                        return Err(error("missing_reference", "Constraint target missing"));
                    }
                    if c.strength == "required"
                        && locations.get(&c.surface_id) != Some(&c.output_id)
                    {
                        return Err(error("constraint_conflict", "Pinned surface moved"));
                    }
                }
                if let Some(f) = &w.focus {
                    if !local.contains(&f.surface_id) {
                        return Err(error("missing_reference", "Focus surface not placed"));
                    }
                    if let Some(id) = &f.element_id {
                        match docs.get(&f.surface_id) {
                            Some(Document::Surface(s)) if s.elements.contains_key(id) => {}
                            _ => return Err(error("missing_reference", "Focus element absent")),
                        }
                    }
                }
            }
        }
    }
    Ok(())
}

pub fn init(db: &Connection) -> Result<()> {
    db.execute_batch("CREATE TABLE IF NOT EXISTS presentation_documents(id TEXT PRIMARY KEY,body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS presentation_identities(id TEXT PRIMARY KEY,revision INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS presentation_sources(source TEXT NOT NULL,activity TEXT NOT NULL,PRIMARY KEY(source,activity));
        CREATE TABLE IF NOT EXISTS presentation_receipts(uid INTEGER NOT NULL,request TEXT NOT NULL,payload TEXT NOT NULL,receipt TEXT NOT NULL,PRIMARY KEY(uid,request));
        CREATE TABLE IF NOT EXISTS presentation_events(cursor INTEGER PRIMARY KEY AUTOINCREMENT,uid INTEGER NOT NULL,request TEXT NOT NULL,before_state TEXT NOT NULL,after_state TEXT NOT NULL,receipt TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS presentation_leases(document TEXT NOT NULL,element TEXT NOT NULL,uid INTEGER NOT NULL,session TEXT NOT NULL,expires INTEGER NOT NULL,draft_revision INTEGER NOT NULL DEFAULT 0,draft TEXT,PRIMARY KEY(document,element));
        CREATE TABLE IF NOT EXISTS presentation_outputs(id TEXT PRIMARY KEY,width REAL NOT NULL,height REAL NOT NULL,connected INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS presentation_actions(reference TEXT PRIMARY KEY,uid INTEGER NOT NULL,activity TEXT NOT NULL,revoked INTEGER NOT NULL DEFAULT 0);").map_err(db_error)?;
    crate::presentation_hosts::init(db)?;
    crate::presentation_outputs::init(db)?;
    crate::presentation_sources::init(db)?;
    crate::presentation_resources::init(db)?;
    crate::presentation_actions::init(db)
}
fn documents(db: &Connection) -> Result<BTreeMap<String, Document>> {
    let mut q = db
        .prepare("SELECT id,body FROM presentation_documents ORDER BY id")
        .map_err(db_error)?;
    let rows = q
        .query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))
        .map_err(db_error)?;
    rows.map(|r| {
        let (id, body) = r.map_err(db_error)?;
        Ok((id, serde_json::from_str(&body).map_err(db_error)?))
    })
    .collect()
}
fn snapshot(db: &Connection) -> Result<Value> {
    let bytes: i64 = db.query_row("SELECT COALESCE(SUM(length(CAST(body AS BLOB))+length(CAST(id AS BLOB))+8),0) FROM presentation_documents", [], |r| r.get(0)).map_err(db_error)?;
    if bytes > (TRANSACTION_LIMIT - 1024) as i64 {
        return Err(error(
            "pagination_required",
            "Use presentation.page and presentation.changes for this workspace",
        ));
    }
    let docs = documents(db)?;
    let referenced = docs
        .values()
        .filter_map(|d| match d {
            Document::Workspace(w) => Some(workspace::surfaces(w)),
            _ => None,
        })
        .flatten()
        .collect::<BTreeSet<_>>();
    let cursor: i64 = db
        .query_row(
            "SELECT COALESCE(MAX(cursor),0) FROM presentation_events",
            [],
            |r| r.get(0),
        )
        .map_err(db_error)?;
    let state = json!({"protocol":PROTOCOL,"catalog_revision":CATALOG,"documents":docs,"host_surfaces":crate::presentation_hosts::snapshot(db,&referenced)?,"renderers":crate::presentation_hosts::renderers(db)?,"event_cursor":cursor});
    if state.to_string().len() > TRANSACTION_LIMIT {
        return Err(error(
            "pagination_required",
            "Use presentation.page and presentation.metadata for this workspace",
        ));
    }
    Ok(state)
}
/// Pages carry a journal cursor so callers never combine different document states.
fn page(db: &Connection, value: &Value) -> Result<Value> {
    let activity = match value.get("activity_id") {
        None | Some(Value::Null) => None,
        Some(Value::String(id)) if ident(id) => Some(id.as_str()),
        _ => return Err(invalid("Invalid activity filter")),
    };
    let after = match value.get("after_id") {
        None | Some(Value::Null) => "",
        Some(Value::String(id)) if id.is_empty() || ident(id) => id.as_str(),
        _ => return Err(invalid("Invalid document cursor")),
    };
    let limit = match value.get("limit") {
        None => 16,
        Some(v) => v
            .as_u64()
            .filter(|n| (1..=64).contains(n))
            .ok_or_else(|| invalid("Page size must be between 1 and 64"))?,
    };
    let cursor: i64 = db
        .query_row(
            "SELECT COALESCE(MAX(cursor),0) FROM presentation_events",
            [],
            |r| r.get(0),
        )
        .map_err(db_error)?;
    if let Some(expected) = value.get("expected_cursor") {
        if expected.as_i64() != Some(cursor) {
            return Err(error(
                "resync_required",
                "Presentation changed while reading pages",
            ));
        }
    }
    let mut q=db.prepare("SELECT id,body FROM presentation_documents WHERE id>?1 AND (?2 IS NULL OR json_extract(body,'$.activity_id')=?2) ORDER BY id LIMIT ?3").map_err(db_error)?;
    let rows = q
        .query_map(params![after, activity, limit + 1], |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?))
        })
        .map_err(db_error)?;
    let mut documents = BTreeMap::new();
    let mut bytes = 0;
    let mut more = false;
    for row in rows {
        let (id, body) = row.map_err(db_error)?;
        if documents.len() >= limit as usize
            || (!documents.is_empty() && bytes + body.len() > 2 * DOCUMENT_LIMIT)
        {
            more = true;
            break;
        }
        bytes += body.len();
        documents.insert(id, serde_json::from_str::<Value>(&body).map_err(db_error)?);
    }
    let next = if more {
        documents.keys().next_back().cloned()
    } else {
        None
    };
    Ok(
        json!({"protocol":PROTOCOL,"catalog_revision":CATALOG,"documents":documents,"event_cursor":cursor,"next_after_id":next}),
    )
}
fn metadata(db: &Connection, value: &Value) -> Result<Value> {
    let activity = match value.get("activity_id") {
        None | Some(Value::Null) => None,
        Some(Value::String(id)) if ident(id) => Some(id.as_str()),
        _ => return Err(invalid("Invalid activity filter")),
    };
    let cursor: i64 = db
        .query_row(
            "SELECT COALESCE(MAX(cursor),0) FROM presentation_events",
            [],
            |r| r.get(0),
        )
        .map_err(db_error)?;
    if value
        .get("expected_cursor")
        .is_some_and(|v| v.as_i64() != Some(cursor))
    {
        return Err(error(
            "resync_required",
            "Presentation changed while reading pages",
        ));
    }
    let mut referenced = BTreeSet::new();
    let mut q=db.prepare("SELECT body FROM presentation_documents WHERE json_type(body,'$.workspace_id')='text' AND (?1 IS NULL OR json_extract(body,'$.activity_id')=?1)").map_err(db_error)?;
    let rows = q
        .query_map([activity], |r| r.get::<_, String>(0))
        .map_err(db_error)?;
    for row in rows {
        if let Document::Workspace(workspace) =
            serde_json::from_str::<Document>(&row.map_err(db_error)?).map_err(db_error)?
        {
            referenced.extend(workspace::surfaces(&workspace));
        }
    }
    let state = json!({"protocol":PROTOCOL,"catalog_revision":CATALOG,"event_cursor":cursor,"host_surfaces":crate::presentation_hosts::snapshot_for(db,&referenced,activity)?,"renderers":crate::presentation_hosts::renderers_for(db,activity)?,"outputs":crate::presentation_outputs::list(db,&json!({"limit":64,"connected_only":true}))?});
    if state.to_string().len() > TRANSACTION_LIMIT {
        return Err(error(
            "resource_limit",
            "Presentation metadata exceeds its transport budget",
        ));
    }
    Ok(state)
}
/// A bounded invalidation journal. Revisions include null tombstones for removals;
/// document bodies are fetched separately against the same journal cursor.
fn changes(db: &Connection, value: &Value) -> Result<Value> {
    let after = match value.get("after_cursor") {
        None => 0,
        Some(v) => v
            .as_i64()
            .filter(|n| *n >= 0)
            .ok_or_else(|| invalid("Invalid journal cursor"))?,
    };
    let limit = match value.get("limit") {
        None => 64,
        Some(v) => v
            .as_u64()
            .filter(|n| (1..=128).contains(n))
            .ok_or_else(|| invalid("Invalid journal page size"))?,
    };
    let latest: i64 = db
        .query_row(
            "SELECT COALESCE(MAX(cursor),0) FROM presentation_events",
            [],
            |r| r.get(0),
        )
        .map_err(db_error)?;
    if after > latest
        || value
            .get("expected_cursor")
            .is_some_and(|v| v.as_i64() != Some(latest))
    {
        return Err(error("resync_required", "Presentation journal changed"));
    }
    let mut query = db
        .prepare(
            "SELECT cursor,receipt FROM presentation_events WHERE cursor>? ORDER BY cursor LIMIT ?",
        )
        .map_err(db_error)?;
    let rows = query
        .query_map(params![after, limit + 1], |r| {
            Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?))
        })
        .map_err(db_error)?;
    let mut events = Vec::new();
    let mut bytes = 256;
    let mut next = after;
    let mut more = false;
    for row in rows {
        let (cursor, raw) = row.map_err(db_error)?;
        let receipt: Value = serde_json::from_str(&raw).map_err(db_error)?;
        let event = json!({"event_cursor":cursor,"revisions":receipt["revisions"]});
        let size = event.to_string().len() + 1;
        if events.len() >= limit as usize || bytes + size > 512 * 1024 {
            if events.is_empty() {
                return Err(error(
                    "resource_limit",
                    "Journal record exceeds page budget",
                ));
            }
            more = true;
            break;
        }
        bytes += size;
        next = cursor;
        events.push(event);
    }
    Ok(
        json!({"protocol":PROTOCOL,"events":events,"latest_cursor":latest,"next_cursor":next,"has_more":more}),
    )
}
fn get_document(db: &Connection, value: &Value) -> Result<Value> {
    if let Some(expected) = value.get("expected_cursor") {
        let latest: i64 = db
            .query_row(
                "SELECT COALESCE(MAX(cursor),0) FROM presentation_events",
                [],
                |r| r.get(0),
            )
            .map_err(db_error)?;
        if expected.as_i64() != Some(latest) {
            return Err(error(
                "resync_required",
                "Presentation changed before document read",
            ));
        }
    }
    let id = value["document_id"]
        .as_str()
        .filter(|id| ident(id))
        .ok_or_else(|| invalid("Document identity required"))?;
    let body: Option<String> = db
        .query_row(
            "SELECT body FROM presentation_documents WHERE id=?",
            [id],
            |r| r.get(0),
        )
        .optional()
        .map_err(db_error)?;
    let doc: Value = serde_json::from_str(
        &body.ok_or_else(|| error("missing_reference", "Document unavailable"))?,
    )
    .map_err(db_error)?;
    if let Some(activity) = value.get("activity_id") {
        if activity != &doc["activity_id"] {
            return Err(error(
                "missing_reference",
                "Document unavailable in this activity",
            ));
        }
    }
    Ok(doc)
}
fn element_path(surface: &SurfaceDocument, target: &str) -> Vec<(String, String, usize)> {
    fn walk(
        s: &SurfaceDocument,
        id: &str,
        target: &str,
        path: &mut Vec<(String, String, usize)>,
    ) -> bool {
        if id == target {
            return true;
        }
        if path.len() >= 32 || path.iter().any(|(ancestor, _, _)| ancestor == id) {
            return false;
        }
        if let Some(node) = s.elements.get(id) {
            for (slot, children) in &node.slots {
                for (index, child) in children.iter().enumerate() {
                    path.push((id.into(), slot.clone(), index));
                    if walk(s, child, target, path) {
                        return true;
                    }
                    path.pop();
                }
            }
        }
        false
    }
    let mut path = Vec::new();
    walk(surface, &surface.root, target, &mut path);
    path
}
fn guard(
    db: &Connection,
    before: &BTreeMap<String, Document>,
    after: &BTreeMap<String, Document>,
    who: &Principal,
) -> Result<()> {
    let mut q = db
        .prepare("SELECT document,element,uid,session,expires,draft FROM presentation_leases")
        .map_err(db_error)?;
    let rows = q
        .query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, u32>(2)?,
                r.get::<_, String>(3)?,
                r.get::<_, i64>(4)?,
                r.get::<_, Option<String>>(5)?,
            ))
        })
        .map_err(db_error)?;
    for row in rows {
        let (id, element, uid, session, expires, draft) = row.map_err(db_error)?;
        if uid == who.uid && session == who.session {
            continue;
        }
        if expires < now() && draft.is_none() {
            continue;
        }
        let old = before.get(&id);
        let new = after.get(&id);
        let changed = if element.is_empty() {
            old != new
        } else {
            match (old, new) {
                (Some(Document::Surface(a)), Some(Document::Surface(b))) => {
                    a.elements.get(&element) != b.elements.get(&element)
                        || a.root != b.root
                        || element_path(a, &element) != element_path(b, &element)
                }
                _ => old != new,
            }
        };
        let moved = before.iter().any(|(key, doc)| match doc {
            Document::Workspace(w)
                if w.outputs.values().any(|o| {
                    serde_json::to_string(o)
                        .unwrap_or_default()
                        .contains(&format!("\"{id}\""))
                }) =>
            {
                match after.get(key) {
                    Some(Document::Workspace(new)) => w.outputs != new.outputs,
                    _ => true,
                }
            }
            _ => false,
        });
        if changed || moved {
            return Err(error(
                "interaction_conflict",
                format!("{id}/{element} has active input or a recoverable draft"),
            ));
        }
    }
    if !who.human() {
        for (id, old) in before {
            if let Document::Workspace(old) = old {
                if let Some(Document::Workspace(new)) = after.get(id) {
                    if new.focus != old.focus {
                        return Err(error(
                            "interaction_conflict",
                            "Agent changes cannot steal focus",
                        ));
                    }
                    for c in old
                        .constraints
                        .iter()
                        .filter(|c| c.provenance != "inferred_preference")
                    {
                        if c.strength == "required"
                            && workspace::placement(old, &c.surface_id)
                                != workspace::placement(new, &c.surface_id)
                        {
                            return Err(error(
                                "constraint_conflict",
                                "Agent cannot change manually constrained geometry",
                            ));
                        }
                        if !new.constraints.contains(c) {
                            return Err(error(
                                "constraint_conflict",
                                "Manual constraints require direct manipulation",
                            ));
                        }
                    }
                } else {
                    return Err(error(
                        "constraint_conflict",
                        "Agent cannot remove an existing workspace",
                    ));
                }
            }
        }
        for (id, new) in after {
            if !before.contains_key(id) {
                if let Document::Workspace(w) = new {
                    if w.focus.is_some()
                        || w.constraints
                            .iter()
                            .any(|c| c.provenance != "inferred_preference")
                    {
                        return Err(error(
                            "unauthorized",
                            "Agent cannot assert direct focus/constraint provenance",
                        ));
                    }
                }
            }
        }
    }
    Ok(())
}
fn surface_mut<'a>(
    docs: &'a mut BTreeMap<String, Document>,
    id: &str,
) -> Result<&'a mut SurfaceDocument> {
    match docs.get_mut(id) {
        Some(Document::Surface(s)) => Ok(s),
        _ => Err(error("missing_reference", id)),
    }
}
fn apply(db: &mut Connection, v: &Value, who: &Principal) -> Result<Value> {
    if v.to_string().len() > TRANSACTION_LIMIT {
        return Err(error("resource_limit", "Transaction exceeds 4 MiB"));
    }
    let req: Apply = decode(v.clone())?;
    if req.op != "presentation.apply" || req.protocol != PROTOCOL || req.catalog_revision != CATALOG
    {
        return Err(error("unsupported_protocol", "Protocol/catalog mismatch"));
    }
    if !ident(&req.request_id) || req.operations.is_empty() || req.operations.len() > 128 {
        return Err(error(
            "resource_limit",
            "Invalid request identity or operation count",
        ));
    }
    let payload = v.to_string();
    let tx = db.transaction().map_err(db_error)?;
    let previous: Option<(String, String)> = tx
        .query_row(
            "SELECT payload,receipt FROM presentation_receipts WHERE uid=? AND request=?",
            params![who.uid, req.request_id],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()
        .map_err(db_error)?;
    if let Some((old, receipt)) = previous {
        if old != payload {
            return Err(error(
                "idempotency_conflict",
                "Request ID reused with changed payload",
            ));
        }
        return serde_json::from_str(&receipt).map_err(db_error);
    }
    let before = documents(&tx)?;
    let mut after = before.clone();
    let affected: BTreeSet<String> = req.operations.iter().map(|o| o.id().into()).collect();
    if req
        .expected_revisions
        .keys()
        .cloned()
        .collect::<BTreeSet<_>>()
        != affected
    {
        return Err(error(
            "stale_revision",
            "Supply exact revision preconditions for every affected document",
        ));
    }
    for id in &affected {
        if before.get(id).map(Document::revision) != req.expected_revisions[id] {
            return Err(error(
                "stale_revision",
                format!(
                    "{id}: current revision {:?}",
                    before.get(id).map(Document::revision)
                ),
            ));
        }
    }
    for op in req.operations {
        let id = op.id().to_string();
        match op {
            Operation::Create { document } => {
                if after.contains_key(&id)
                    || tx
                        .query_row(
                            "SELECT EXISTS(SELECT 1 FROM presentation_identities WHERE id=?)",
                            [&id],
                            |r| r.get::<_, bool>(0),
                        )
                        .map_err(db_error)?
                    || document.revision != 0
                {
                    return Err(invalid("Created surface must be absent at revision 0"));
                }
                after.insert(id, Document::Surface(document));
            }
            Operation::Replace { document } => {
                let current = surface_mut(&mut after, &id)?;
                if current.activity_id != document.activity_id
                    || current.revision != document.revision
                {
                    return Err(invalid("Surface ownership/revision cannot be replaced"));
                }
                *current = document;
            }
            Operation::Close { .. } => {
                surface_mut(&mut after, &id)?;
                after.remove(&id);
            }
            Operation::Navigate {
                surface_id,
                element_id,
                source_revision,
                ..
            } => {
                if !who.human() {
                    return Err(error(
                        "unauthorized",
                        "Reference navigation requires user input",
                    ));
                }
                let source = match after.get(&surface_id) {
                    Some(Document::Surface(source)) if source.revision == source_revision => source,
                    Some(_) => return Err(error("stale_revision", "Reference source changed")),
                    None => return Err(error("missing_reference", "Reference source unavailable")),
                };
                let element = source
                    .elements
                    .get(&element_id)
                    .filter(|e| is_reference(&e.kind))
                    .ok_or_else(|| error("missing_reference", "Reference element unavailable"))?;
                let active:bool=tx.query_row("SELECT EXISTS(SELECT 1 FROM activities WHERE CAST(id AS TEXT)=? AND id NOT IN (SELECT activity_id FROM removed_activities))",[&source.activity_id],|r|r.get(0)).map_err(db_error)?;
                if !active {
                    return Err(error("missing_reference", "Activity unavailable"));
                }
                let target = reference_target(&tx, &after, source, element)?;
                let activity = source.activity_id.clone();
                match after.get_mut(&id) {
                    Some(Document::Workspace(w)) if w.activity_id == activity => workspace::apply(
                        w,
                        workspace::Edit::Focus {
                            surface_id: target,
                            element_id: None,
                        },
                    )?,
                    _ => {
                        return Err(error(
                            "missing_reference",
                            "Workspace unavailable in this activity",
                        ))
                    }
                }
            }
            Operation::WorkspaceEdit { edit, .. } => {
                if !who.human() {
                    return Err(error(
                        "unauthorized",
                        "Direct workspace controls require user input",
                    ));
                }
                match after.get_mut(&id) {
                    Some(Document::Workspace(w)) => workspace::apply(w, edit)?,
                    _ => return Err(error("missing_reference", "Workspace unavailable")),
                }
            }
            Operation::Workspace { document } => {
                if let Some(old) = after.get(&id) {
                    if !matches!(old, Document::Workspace(_))
                        || old.activity() != document.activity_id
                        || old.revision() != document.revision
                    {
                        return Err(invalid("Workspace ownership/revision mismatch"));
                    }
                } else if document.revision != 0
                    || tx
                        .query_row(
                            "SELECT EXISTS(SELECT 1 FROM presentation_identities WHERE id=?)",
                            [&id],
                            |r| r.get::<_, bool>(0),
                        )
                        .map_err(db_error)?
                {
                    return Err(invalid(
                        "New workspace revision must be 0 and its identity must be unused",
                    ));
                }
                after.insert(id, Document::Workspace(document));
            }
            other => {
                let s = surface_mut(&mut after, &id)?;
                match other {
                    Operation::Put {
                        element_id,
                        element,
                        ..
                    } => {
                        s.elements.insert(element_id, element);
                    }
                    Operation::Remove { element_id, .. } => {
                        if s.elements.remove(&element_id).is_none() {
                            return Err(error("missing_reference", element_id));
                        }
                    }
                    Operation::Props {
                        element_id, props, ..
                    } => {
                        s.elements
                            .get_mut(&element_id)
                            .ok_or_else(|| error("missing_reference", element_id))?
                            .props = props;
                    }
                    Operation::CommitDraft {
                        element_id,
                        expected_draft_revision,
                        ..
                    } => {
                        if !who.human() {
                            return Err(error(
                                "unauthorized",
                                "Draft commit requires direct native input",
                            ));
                        }
                        let saved:Option<(u32,String,i64,Option<String>)>=tx.query_row("SELECT uid,session,draft_revision,draft FROM presentation_leases WHERE document=? AND element=?",params![id,element_id],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?))).optional().map_err(db_error)?;
                        let (uid, session, revision, draft) = saved
                            .ok_or_else(|| error("missing_reference", "No draft to commit"))?;
                        if uid != who.uid || session != who.session {
                            return Err(error(
                                "interaction_conflict",
                                "Acquire the native editor before committing",
                            ));
                        }
                        if revision != expected_draft_revision {
                            return Err(error("stale_revision", "Draft changed before commit"));
                        }
                        let draft = draft
                            .ok_or_else(|| error("missing_reference", "No draft text to commit"))?;
                        let element = s
                            .elements
                            .get_mut(&element_id)
                            .ok_or_else(|| error("missing_reference", &element_id))?;
                        let value = match element.kind.as_str() {
                            "TextField@1" | "DocumentEditor@1" => json!(draft),
                            "Choice@1"
                                if element.props["options"]
                                    .as_array()
                                    .unwrap()
                                    .contains(&json!(draft)) =>
                            {
                                json!(draft)
                            }
                            "Toggle@1" if draft == "true" || draft == "false" => {
                                json!(draft == "true")
                            }
                            _ => {
                                return Err(invalid(
                                    "Draft is incompatible with this editable control",
                                ))
                            }
                        };
                        element.props.insert("value".into(), value);
                        tx.execute("UPDATE presentation_leases SET draft=NULL,draft_revision=draft_revision+1 WHERE document=? AND element=?",params![id,element_id]).map_err(db_error)?;
                    }
                    Operation::Children {
                        element_id,
                        slot,
                        children,
                        ..
                    } => {
                        s.elements
                            .get_mut(&element_id)
                            .ok_or_else(|| error("missing_reference", element_id))?
                            .slots
                            .insert(slot, children);
                    }
                    Operation::Bind {
                        binding_id,
                        binding,
                        ..
                    } => {
                        s.bindings.insert(binding_id, binding);
                    }
                    Operation::Unbind { binding_id, .. } => {
                        if s.bindings.remove(&binding_id).is_none() {
                            return Err(error("missing_reference", binding_id));
                        }
                    }
                    Operation::Action {
                        action_id, action, ..
                    } => {
                        s.actions.insert(action_id, action);
                    }
                    Operation::Unaction { action_id, .. } => {
                        if s.actions.remove(&action_id).is_none() {
                            return Err(error("missing_reference", action_id));
                        }
                    }
                    _ => unreachable!(),
                }
            }
        }
    }
    for id in &affected {
        if let Some(doc) = after.get_mut(id) {
            let revision = match before.get(id) {
                Some(old) => old
                    .revision()
                    .checked_add(1)
                    .ok_or_else(|| error("resource_limit", "Revision overflow"))?,
                None => 0,
            };
            doc.set_revision(revision);
        }
    }
    for id in &affected {
        if let Some(doc) = after.get(id) {
            let active:bool=tx.query_row("SELECT EXISTS(SELECT 1 FROM activities WHERE CAST(id AS TEXT)=? AND id NOT IN (SELECT activity_id FROM removed_activities))",[doc.activity()],|r|r.get(0)).map_err(db_error)?;
            if !active {
                return Err(error(
                    "missing_reference",
                    "Affected activity is absent or set aside",
                ));
            }
        }
    }
    guard(&tx, &before, &after, who)?;
    validate(&tx, &after, who)?;
    let receipt = commit(
        &tx,
        who,
        &req.request_id,
        &payload,
        &before,
        &after,
        &affected,
    )?;
    tx.commit().map_err(db_error)?;
    Ok(receipt)
}
/// Remove a returning window's transient placement inside the host association transaction.
/// Host metadata and the journaled workspace edit therefore become visible atomically.
pub(crate) fn reconnect_placement(
    db: &Connection,
    v: &Value,
    who: &Principal,
    live: &str,
    activity: &str,
) -> Result<Option<Value>> {
    let before = documents(db)?;
    let mut after = before.clone();
    let mut affected = BTreeSet::new();
    let expected = v
        .get("expected_workspaces")
        .cloned()
        .unwrap_or_else(|| json!({}));
    let expected = expected
        .as_object()
        .ok_or_else(|| invalid("Expected workspace revisions must be an object"))?;
    for (id, doc) in &before {
        if let Document::Workspace(w) = doc {
            if workspace::placement(w, live).is_some() {
                if w.activity_id != activity
                    || expected.get(id).and_then(Value::as_u64) != Some(w.revision)
                {
                    return Err(error(
                        "stale_revision",
                        "Returning placement needs current workspace revisions",
                    ));
                }
                if let Some(Document::Workspace(next)) = after.get_mut(id) {
                    workspace::apply(
                        next,
                        workspace::Edit::Remove {
                            surface_id: live.into(),
                        },
                    )?;
                    next.revision = next
                        .revision
                        .checked_add(1)
                        .ok_or_else(|| error("resource_limit", "Workspace revision overflow"))?;
                }
                affected.insert(id.clone());
            }
        }
    }
    if expected.keys().cloned().collect::<BTreeSet<_>>() != affected {
        return Err(error(
            "stale_revision",
            "Supply exact workspace revisions for the returning placement",
        ));
    }
    if affected.is_empty() {
        return Ok(None);
    }
    guard(db, &before, &after, who)?;
    validate(db, &after, who)?;
    let request = format!("{}-placement", v["request_id"].as_str().unwrap_or(""));
    commit(
        db,
        who,
        &request,
        &v.to_string(),
        &before,
        &after,
        &affected,
    )
    .map(Some)
}

fn commit(
    db: &Connection,
    who: &Principal,
    request: &str,
    payload: &str,
    before: &BTreeMap<String, Document>,
    after: &BTreeMap<String, Document>,
    affected: &BTreeSet<String>,
) -> Result<Value> {
    for id in affected {
        let rev = after
            .get(id)
            .map(Document::revision)
            .unwrap_or_else(|| before[id].revision() + 1);
        db.execute("INSERT INTO presentation_identities VALUES(?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision",params![id,rev]).map_err(db_error)?;
        if let Some(doc) = after.get(id) {
            if let Document::Surface(surface) = doc {
                for binding in surface.bindings.values() {
                    db.execute(
                        "INSERT OR IGNORE INTO presentation_sources VALUES(?,?)",
                        params![binding.source, surface.activity_id],
                    )
                    .map_err(db_error)?;
                }
            }
            db.execute("INSERT INTO presentation_documents VALUES(?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body",params![id,serde_json::to_string(doc).map_err(db_error)?]).map_err(db_error)?;
        } else {
            db.execute("DELETE FROM presentation_documents WHERE id=?", [id])
                .map_err(db_error)?;
        }
    }
    let revisions: BTreeMap<_, _> = affected
        .iter()
        .map(|id| (id, after.get(id).map(Document::revision)))
        .collect();
    let mut receipt = json!({"request_id":request,"status":"committed","revisions":revisions});
    db.execute("INSERT INTO presentation_events(uid,request,before_state,after_state,receipt) VALUES(?,?,?,?,?)",params![who.uid,request,serde_json::to_string(&before.iter().filter(|(id,_)|affected.contains(*id)).collect::<BTreeMap<_,_>>()).map_err(db_error)?,serde_json::to_string(&after.iter().filter(|(id,_)|affected.contains(*id)).collect::<BTreeMap<_,_>>()).map_err(db_error)?,receipt.to_string()]).map_err(db_error)?;
    let cursor = db.last_insert_rowid();
    receipt["event_cursor"] = json!(cursor);
    db.execute(
        "UPDATE presentation_events SET receipt=? WHERE cursor=?",
        params![receipt.to_string(), cursor],
    )
    .map_err(db_error)?;
    db.execute(
        "INSERT INTO presentation_receipts VALUES(?,?,?,?)",
        params![who.uid, request, payload, receipt.to_string()],
    )
    .map_err(db_error)?;
    Ok(receipt)
}
fn is_reference(kind: &str) -> bool {
    matches!(kind, "DocumentReference@1" | "ApplicationReference@1")
}
fn reference_target(
    db: &Connection,
    docs: &BTreeMap<String, Document>,
    source: &SurfaceDocument,
    element: &Element,
) -> Result<String> {
    let target = element.props["target"]
        .as_str()
        .filter(|id| ident(id))
        .ok_or_else(|| invalid("Invalid reference identity"))?;
    if element.kind == "DocumentReference@1" {
        match docs.get(target) {
            Some(Document::Surface(s)) if s.activity_id == source.activity_id => {}
            _ => {
                return Err(error(
                    "missing_reference",
                    "Document unavailable in this activity",
                ))
            }
        }
    } else if element.kind == "ApplicationReference@1" {
        let observed = crate::presentation_hosts::source(db, target)
            .map_err(db_error)?
            .ok_or_else(|| error("missing_reference", "Application unavailable"))?;
        if observed["activity_id"].as_str() != Some(source.activity_id.as_str())
            || observed["availability"] != "available"
        {
            return Err(error(
                "missing_reference",
                "Application unavailable in this activity",
            ));
        }
    } else {
        return Err(invalid("Element is not a view reference"));
    }
    Ok(target.into())
}
fn resolve_reference(db: &Connection, v: &Value, who: &Principal) -> Result<Value> {
    if !who.human() {
        return Err(error(
            "unauthorized",
            "Reference navigation requires user input",
        ));
    }
    let id = v["surface_id"]
        .as_str()
        .ok_or_else(|| invalid("Source required"))?;
    let mut docs = BTreeMap::new();
    let raw:Option<String>=db.query_row("SELECT CASE WHEN length(CAST(body AS BLOB))<=1048576 THEN body END FROM presentation_documents WHERE id=?",[id],|r|r.get(0)).optional().map_err(db_error)?.flatten();
    let raw = raw.ok_or_else(|| error("missing_reference", "Bounded source unavailable"))?;
    let document: Document = serde_json::from_str(&raw).map_err(db_error)?;
    if let Document::Surface(source) = &document {
        if let Some(target) = v["element_id"]
            .as_str()
            .and_then(|id| source.elements.get(id))
            .and_then(|e| e.props.get("target"))
            .and_then(Value::as_str)
        {
            let target_body:Option<String>=db.query_row("SELECT CASE WHEN length(CAST(body AS BLOB))<=1048576 THEN body END FROM presentation_documents WHERE id=?",[target],|r|r.get(0)).optional().map_err(db_error)?.flatten();
            if let Some(raw) = target_body {
                docs.insert(
                    target.to_string(),
                    serde_json::from_str(&raw).map_err(db_error)?,
                );
            }
        }
    }
    docs.insert(id.to_string(), document);
    let source = match docs.get(id) {
        Some(Document::Surface(source)) => source,
        _ => return Err(error("missing_reference", "Source unavailable")),
    };
    if v["source_revision"].as_u64() != Some(source.revision) {
        return Err(error("stale_revision", "Reference source changed"));
    }
    let active:bool=db.query_row("SELECT EXISTS(SELECT 1 FROM activities WHERE CAST(id AS TEXT)=? AND id NOT IN (SELECT activity_id FROM removed_activities))",[&source.activity_id],|r|r.get(0)).map_err(db_error)?;
    if !active {
        return Err(error("missing_reference", "Activity unavailable"));
    }
    let element = v["element_id"]
        .as_str()
        .and_then(|id| source.elements.get(id))
        .ok_or_else(|| error("missing_reference", "Reference element unavailable"))?;
    let target = reference_target(db, &docs, source, element)?;
    Ok(json!({"target":target,"kind":element.kind,"activity_id":source.activity_id}))
}
pub fn handle(db: &mut Connection, v: &Value, who: &Principal) -> Result<Value> {
    match v["op"].as_str().unwrap_or("") {
        "catalog.get" => Ok(catalog()),
        "resource.publish" | "resource.get" | "resource.list" => {
            crate::presentation_resources::handle(db, v, who)
        }
        "source.publish" | "source.heartbeat" | "source.list" => {
            crate::presentation_sources::handle(db, v, who)
        }
        "host.renderer" => crate::presentation_hosts::renderer(db, v, who),
        "host.reconnect" => crate::presentation_hosts::reconnect(db, v, who),
        "host.surface" => crate::presentation_hosts::register(db, v, who),
        "action.issue"
        | "action.ensure"
        | "action.ensure_sources"
        | "action.list"
        | "action.revoke"
        | "action.metadata"
        | "action.status" => crate::presentation_actions::handle(db, v, who),
        "presentation.snapshot" => snapshot(db),
        "presentation.page" => page(db, v),
        "presentation.metadata" => metadata(db, v),
        "presentation.get" => get_document(db, v),
        "presentation.changes" => changes(db, v),
        "presentation.apply" => apply(db, v, who),
        "presentation.reference" => resolve_reference(db, v, who),
        "presentation.subscribe" => {
            let cursor = match v.get("after_cursor") {
                None => 0,
                Some(value) => value
                    .as_i64()
                    .ok_or_else(|| invalid("Cursor must be a nonnegative integer"))?,
            };
            if cursor < 0 {
                return Err(invalid("Cursor must be nonnegative"));
            }
            if cursor == 0 {
                return snapshot(db);
            }
            let latest: i64 = db
                .query_row(
                    "SELECT COALESCE(MAX(cursor),0) FROM presentation_events",
                    [],
                    |r| r.get(0),
                )
                .map_err(db_error)?;
            if cursor > latest {
                return Err(error("resync_required", "Cursor is ahead of the journal"));
            }
            let mut query = db.prepare("SELECT cursor,after_state,receipt FROM presentation_events WHERE cursor>? ORDER BY cursor LIMIT 33").map_err(db_error)?;
            let mut rows = query.query([cursor]).map_err(db_error)?;
            let mut events = Vec::new();
            let mut bytes = 1024;
            let mut next = cursor;
            let mut more = false;
            while let Some(row) = rows.next().map_err(db_error)? {
                let observed: i64 = row.get(0).map_err(db_error)?;
                let body: String = row.get(1).map_err(db_error)?;
                let receipt: String = row.get(2).map_err(db_error)?;
                if events.len() >= 32
                    || bytes + body.len() + receipt.len() + 128 > TRANSACTION_LIMIT
                {
                    if events.is_empty() {
                        return Err(error(
                            "pagination_required",
                            "Use presentation.changes and presentation.get for this journal event",
                        ));
                    }
                    more = true;
                    break;
                }
                bytes += body.len() + receipt.len() + 128;
                events.push(json!({"event_cursor":observed,"documents":serde_json::from_str::<Value>(&body).map_err(db_error)?,"receipt":serde_json::from_str::<Value>(&receipt).map_err(db_error)?}));
                next = observed;
            }
            Ok(
                json!({"protocol":PROTOCOL,"events":events,"latest_cursor":latest,"next_cursor":next,"has_more":more}),
            )
        }
        "outputs.register" | "outputs.disconnect" | "outputs.list" => {
            crate::presentation_outputs::handle(db, v, who)
        }
        "interaction.begin" | "interaction.renew" | "interaction.end" | "draft.save"
        | "draft.get" => interaction(db, v, who),
        "presentation.undo" => undo(db, v, who),
        "binding.snapshot" => bindings(db, v),
        _ => Err(error(
            "unsupported_operation",
            "Unknown presentation operation",
        )),
    }
}
fn interaction(db: &mut Connection, v: &Value, who: &Principal) -> Result<Value> {
    if !who.human() {
        return Err(error(
            "unauthorized",
            "Interaction ownership belongs to native user input",
        ));
    }
    let id = v["surface_id"]
        .as_str()
        .ok_or_else(|| invalid("Missing surface ID"))?;
    let element = v["element_id"].as_str().unwrap_or("");
    let body: Option<String> = db
        .query_row(
            "SELECT body FROM presentation_documents WHERE id=?",
            [id],
            |r| r.get(0),
        )
        .optional()
        .map_err(db_error)?;
    let document: Document =
        serde_json::from_str(&body.ok_or_else(|| error("missing_reference", id))?)
            .map_err(db_error)?;
    if !element.is_empty() {
        match &document {
            Document::Surface(s) if s.elements.contains_key(element) => {}
            _ => return Err(error("missing_reference", element)),
        }
    }
    if matches!(document, Document::Workspace(_))
        && v["op"].as_str().unwrap_or("").starts_with("draft.")
    {
        return Err(invalid("Workspace leases do not contain text drafts"));
    }
    let existing:Option<(u32,String,i64,i64,Option<String>)>=db.query_row("SELECT uid,session,expires,draft_revision,draft FROM presentation_leases WHERE document=? AND element=?",params![id,element],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?))).optional().map_err(db_error)?;
    let owned = existing
        .as_ref()
        .map(|(uid, session, ..)| *uid == who.uid && session == &who.session)
        .unwrap_or(false);
    let op = v["op"].as_str().unwrap();
    if existing.as_ref().map(|r| r.0 != who.uid).unwrap_or(false) {
        return Err(error("unauthorized", "Draft belongs to another local user"));
    }
    if op == "draft.get" {
        return Ok(
            json!({"draft_revision":existing.as_ref().map(|r|r.3).unwrap_or(0),"draft":existing.and_then(|r|r.4)}),
        );
    }
    let previous_dead = existing
        .as_ref()
        .map(|r| {
            r.1.split_once(':')
                .map(|(pid, start)| pid.parse::<u32>().is_ok() && start.parse::<u64>().is_ok())
                .unwrap_or(false)
                && !crate::presentation_hosts::alive(&r.1)
        })
        .unwrap_or(false);
    if !owned && !previous_dead && existing.as_ref().map(|r| r.2 >= now()).unwrap_or(false) {
        return Err(error(
            "interaction_conflict",
            "Another native input session owns this element",
        ));
    }
    if op == "interaction.begin" {
        let rev = existing.as_ref().map(|r| r.3).unwrap_or(0);
        db.execute("INSERT INTO presentation_leases(document,element,uid,session,expires) VALUES(?,?,?,?,?) ON CONFLICT(document,element) DO UPDATE SET uid=excluded.uid,session=excluded.session,expires=excluded.expires",params![id,element,who.uid,who.session,now()+30]).map_err(db_error)?;
        return Ok(
            json!({"expires_at":now()+30,"draft_revision":rev,"surface_revision":document.revision()}),
        );
    }
    if !owned {
        return Err(error(
            "interaction_conflict",
            "Begin interaction before changing its lease/draft",
        ));
    }
    match op {
        "interaction.end" => {
            db.execute(
                "UPDATE presentation_leases SET expires=0 WHERE document=? AND element=?",
                params![id, element],
            )
            .map_err(db_error)?;
        }
        "interaction.renew" => {
            db.execute(
                "UPDATE presentation_leases SET expires=? WHERE document=? AND element=?",
                params![now() + 30, id, element],
            )
            .map_err(db_error)?;
        }
        "draft.save" => {
            let expected = v["expected_draft_revision"]
                .as_i64()
                .ok_or_else(|| invalid("Draft revision precondition required"))?;
            if existing.as_ref().unwrap().3 != expected {
                return Err(error(
                    "stale_revision",
                    "Draft changed; recover it before editing",
                ));
            }
            let draft = if v["draft"].is_null() {
                None
            } else {
                Some(
                    v["draft"]
                        .as_str()
                        .filter(|s| s.len() <= 65536)
                        .ok_or_else(|| {
                            error("resource_limit", "Draft must be text up to 64 KiB")
                        })?,
                )
            };
            db.execute("UPDATE presentation_leases SET draft=?,draft_revision=draft_revision+1 WHERE document=? AND element=?",params![draft,id,element]).map_err(db_error)?;
            return Ok(json!({"draft_revision":expected+1}));
        }
        _ => unreachable!(),
    }
    Ok(json!({"status":"accepted"}))
}
fn bindings(db: &Connection, v: &Value) -> Result<Value> {
    let id = v["surface_id"]
        .as_str()
        .ok_or_else(|| invalid("Missing surface ID"))?;
    let body: Option<String> = db
        .query_row(
            "SELECT body FROM presentation_documents WHERE id=?",
            [id],
            |r| r.get(0),
        )
        .optional()
        .map_err(db_error)?;
    let document: Document =
        serde_json::from_str(&body.ok_or_else(|| error("missing_reference", id))?)
            .map_err(db_error)?;
    let s = match document {
        Document::Surface(s) => s,
        _ => return Err(error("missing_reference", id)),
    };
    let mut values = BTreeMap::new();
    let rev: i64 = db
        .query_row("SELECT value FROM meta WHERE key='revision'", [], |r| {
            r.get(0)
        })
        .map_err(db_error)?;
    for (key, b) in &s.bindings {
        if b.source.starts_with("broker:")
            || b.source.starts_with("window:")
            || b.source.starts_with("file:")
        {
            values.insert(
                key,
                crate::presentation_sources::binding(db, &b.source, &s.activity_id, &b.path)?,
            );
            continue;
        }
        let job = b
            .source
            .strip_prefix("job:")
            .and_then(|x| x.parse::<i64>().ok())
            .unwrap_or(0);
        let value:Option<Value>=db.query_row("SELECT status,exit_code,error,created_at,finished_at FROM jobs WHERE id=? AND CAST(activity_id AS TEXT)=?",params![job,s.activity_id],|r|Ok(json!({"status":r.get::<_,String>(0)?,"exit_code":r.get::<_,Option<i64>>(1)?,"error":r.get::<_,Option<String>>(2)?,"created_at":r.get::<_,i64>(3)?,"finished_at":r.get::<_,Option<i64>>(4)?}))).optional().map_err(db_error)?;
        values.insert(key,json!({"source":b.source,"source_revision":rev,"observed_at":now(),"availability":if value.is_some(){"available"}else{"unavailable"},"value":value.and_then(|x|x.pointer(&b.path).cloned())}));
    }
    Ok(json!({"surface_id":id,"surface_revision":s.revision,"bindings":values}))
}
fn undo(db: &mut Connection, v: &Value, who: &Principal) -> Result<Value> {
    if !who.human() {
        return Err(error("unauthorized", "Undo requires direct native input"));
    }
    let target = v["event_cursor"]
        .as_i64()
        .ok_or_else(|| invalid("Missing undo event"))?;
    let request = v["request_id"]
        .as_str()
        .filter(|s| ident(s))
        .ok_or_else(|| invalid("Missing undo request ID"))?;
    let payload = v.to_string();
    let tx = db.transaction().map_err(db_error)?;
    let previous: Option<(String, String)> = tx
        .query_row(
            "SELECT payload,receipt FROM presentation_receipts WHERE uid=? AND request=?",
            params![who.uid, request],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()
        .map_err(db_error)?;
    if let Some((old, receipt)) = previous {
        if old != payload {
            return Err(error("idempotency_conflict", "Undo request changed"));
        }
        return serde_json::from_str(&receipt).map_err(db_error);
    }
    let record: Option<(String, String)> = tx
        .query_row(
            "SELECT before_state,after_state FROM presentation_events WHERE cursor=?",
            [target],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()
        .map_err(db_error)?;
    let (old, new) = record.ok_or_else(|| error("missing_reference", "Undo event absent"))?;
    let old: BTreeMap<String, Document> = serde_json::from_str(&old).map_err(db_error)?;
    let new: BTreeMap<String, Document> = serde_json::from_str(&new).map_err(db_error)?;
    let before = documents(&tx)?;
    let mut after = before.clone();
    let affected: BTreeSet<String> = old
        .keys()
        .chain(new.keys())
        .filter(|id| old.get(*id) != new.get(*id))
        .cloned()
        .collect();
    for id in &affected {
        if before.get(id) != new.get(id) {
            return Err(error(
                "stale_revision",
                "Undo target diverged; current views were preserved",
            ));
        }
        if let Some(doc) = old.get(id) {
            let mut doc = doc.clone();
            let latest: u64 = tx
                .query_row(
                    "SELECT revision FROM presentation_identities WHERE id=?",
                    [id],
                    |r| r.get(0),
                )
                .map_err(db_error)?;
            doc.set_revision(
                latest
                    .checked_add(1)
                    .ok_or_else(|| error("resource_limit", "Revision overflow"))?,
            );
            after.insert(id.clone(), doc);
        } else {
            after.remove(id);
        }
    }
    guard(&tx, &before, &after, who)?;
    validate(&tx, &after, who)?;
    let receipt = commit(&tx, who, request, &payload, &before, &after, &affected)?;
    tx.commit().map_err(db_error)?;
    Ok(receipt)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn fixture() -> Connection {
        let db = Connection::open_in_memory().unwrap();
        db.execute_batch("CREATE TABLE activities(id INTEGER PRIMARY KEY); INSERT INTO activities VALUES(1); INSERT INTO activities VALUES(2);
            CREATE TABLE removed_activities(activity_id INTEGER PRIMARY KEY);
            CREATE TABLE jobs(id INTEGER PRIMARY KEY,activity_id INTEGER,status TEXT,exit_code INTEGER,error TEXT,created_at INTEGER,finished_at INTEGER);
            INSERT INTO jobs VALUES(1,1,'running',NULL,NULL,1,NULL); INSERT INTO jobs VALUES(2,2,'running',NULL,NULL,1,NULL);
            CREATE TABLE meta(key TEXT PRIMARY KEY,value INTEGER); INSERT INTO meta VALUES('revision',1);").unwrap();
        init(&db).unwrap();
        db
    }
    fn human() -> Principal {
        Principal {
            uid: 1000,
            session: "user-a".into(),
        }
    }
    fn agent() -> Principal {
        Principal {
            uid: 999,
            session: "agent".into(),
        }
    }
    fn surface() -> Value {
        json!({"protocol":PROTOCOL,"catalog_revision":CATALOG,"surface_id":"surface-a","activity_id":"1","revision":0,"title":"Work","root":"root","elements":{
        "root":{"type":"Stack@1","slots":{"children":["text","input"]}},
        "text":{"type":"Text@1","props":{"text":"Hello"}},
        "input":{"type":"TextField@1","props":{"label":"Request"}}
    },"bindings":{},"actions":{}})
    }
    fn create(db: &mut Connection) -> Value {
        handle(db,&json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"create","expected_revisions":{"surface-a":null},"operations":[{"op":"surface.create","document":surface()}]}),&human()).unwrap()
    }
    fn props(request: &str, revision: u64, element: &str, text: &str) -> Value {
        json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":request,"expected_revisions":{"surface-a":revision},"operations":[{"op":"element.set_props","surface_id":"surface-a","element_id":element,"props":{"text":text}}]})
    }
    #[test]
    fn repeated_image_references_share_an_aggregate_decoded_pixel_budget() {
        let mut db = fixture();
        let reference = format!("resource-{}", "f".repeat(32));
        db.execute("INSERT INTO presentation_resources VALUES(?, '1', 1000, 'Large image', '', 2048, 2048, 0)",[&reference]).unwrap();
        let mut doc = surface();
        doc["elements"] =
            json!({"root":{"type":"Stack@1","slots":{"children":["a","b","c","d","e"]}}});
        for id in ["a", "b", "c", "d", "e"] {
            doc["elements"][id] = json!({"type":"Image@1","props":{"label":"Large referenced image","reference":reference}});
        }
        let mut request = json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"image-budget","expected_revisions":{"surface-a":null},"operations":[{"op":"surface.create","document":doc}]});
        assert!(handle(&mut db, &request, &agent())
            .unwrap_err()
            .contains("16 MiPixel"));
        assert!(snapshot(&db).unwrap()["documents"]
            .as_object()
            .unwrap()
            .is_empty());
        request["operations"][0]["document"]["elements"]
            .as_object_mut()
            .unwrap()
            .remove("e");
        request["operations"][0]["document"]["elements"]["root"]["slots"]["children"] =
            json!(["a", "b", "c", "d"]);
        handle(&mut db, &request, &agent()).unwrap();
    }
    #[test]
    fn embedded_terminals_only_reference_registered_same_activity_broker_work() {
        let mut db = fixture();
        let source = format!("broker:{}", "d".repeat(32));
        db.execute(
            "INSERT INTO presentation_external_sources VALUES(?, '1', 1, '{}', 'fixture', 0)",
            [&source],
        )
        .unwrap();
        let mut doc = surface();
        doc["elements"]["text"] =
            json!({"type":"PtySession@1","props":{"label":"Interactive work","source":source}});
        let request = json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"terminal-reference","expected_revisions":{"surface-a":null},"operations":[{"op":"surface.create","document":doc}]});
        for value in [
            "/bin/sh".to_string(),
            format!("broker:{}", "e".repeat(32)),
            format!("file:{}", "d".repeat(32)),
        ] {
            let mut invalid = request.clone();
            invalid["operations"][0]["document"]["elements"]["text"]["props"]["source"] =
                json!(value);
            assert!(handle(&mut db, &invalid, &agent())
                .unwrap_err()
                .contains("missing_reference"));
        }
        let mut foreign = request.clone();
        foreign["operations"][0]["document"]["activity_id"] = json!("2");
        assert!(handle(&mut db, &foreign, &agent())
            .unwrap_err()
            .contains("missing_reference"));
        handle(&mut db, &request, &agent()).unwrap();
    }
    #[test]
    fn shared_document_edits_persist_only_through_guarded_human_draft_commit() {
        let mut db = fixture();
        let mut doc = surface();
        doc["elements"]["input"] =
            json!({"type":"DocumentEditor@1","props":{"label":"Document","value":"Original λ"}});
        handle(&mut db,&json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"editor-create","expected_revisions":{"surface-a":null},"operations":[{"op":"surface.create","document":doc}]}),&agent()).unwrap();
        handle(
            &mut db,
            &json!({"op":"interaction.begin","surface_id":"surface-a","element_id":"input"}),
            &human(),
        )
        .unwrap();
        handle(&mut db,&json!({"op":"draft.save","surface_id":"surface-a","element_id":"input","expected_draft_revision":0,"draft":"Human document 日本語\nSecond line"}),&human()).unwrap();
        let mut commit = json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"editor-save","expected_revisions":{"surface-a":1},"operations":[{"op":"draft.commit","surface_id":"surface-a","element_id":"input","expected_draft_revision":1}]});
        assert!(handle(&mut db, &commit, &human())
            .unwrap_err()
            .contains("stale_revision"));
        assert_eq!(
            snapshot(&db).unwrap()["documents"]["surface-a"]["elements"]["input"]["props"]["value"],
            "Original λ"
        );
        commit["expected_revisions"]["surface-a"] = json!(0);
        assert!(handle(&mut db, &commit, &agent()).is_err());
        handle(&mut db, &commit, &human()).unwrap();
        assert_eq!(
            snapshot(&db).unwrap()["documents"]["surface-a"]["elements"]["input"]["props"]["value"],
            "Human document 日本語\nSecond line"
        );
    }
    #[test]
    fn result_and_error_content_is_bounded_typed_and_source_bindable() {
        for (kind, key) in [("Result@1", "value"), ("Error@1", "message")] {
            let mut db = fixture();
            let mut doc = surface();
            doc["elements"]["text"] =
                json!({"type":kind,"props":{"label":"Observed outcome",key:{"binding":"outcome"}}});
            doc["bindings"]["outcome"] = json!({"source":"job:1","path":"/error","access":"read"});
            let request = json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"outcome","expected_revisions":{"surface-a":null},"operations":[{"op":"surface.create","document":doc}]});
            handle(&mut db, &request, &agent()).unwrap();
            let mut invalid = request.clone();
            invalid["request_id"] = json!("bad-outcome");
            invalid["expected_revisions"]["surface-a"] = json!(0);
            invalid["operations"] = json!([{"op":"element.set_props","surface_id":"surface-a","element_id":"text","props":{"label":"Outcome",key:42}}]);
            assert!(handle(&mut db, &invalid, &agent()).is_err());
            assert_eq!(
                snapshot(&db).unwrap()["documents"]["surface-a"]["revision"],
                0
            );
        }
    }
    #[test]
    fn references_are_scoped_guarded_and_survive_target_closure() {
        let mut db = fixture();
        create(&mut db);
        let mut doc = surface();
        doc["surface_id"] = json!("links");
        doc["elements"]["text"] = json!({"type":"DocumentReference@1","props":{"label":"Open work","target":"surface-a"}});
        let create_link = json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"links","expected_revisions":{"links":null},"operations":[{"op":"surface.create","document":doc}]});
        let mut foreign = create_link.clone();
        foreign["operations"][0]["document"]["activity_id"] = json!("2");
        assert!(handle(&mut db, &foreign, &agent())
            .unwrap_err()
            .contains("missing_reference"));
        let mut path = create_link.clone();
        path["operations"][0]["document"]["elements"]["text"]["props"]["target"] =
            json!("/etc/passwd");
        assert!(handle(&mut db, &path, &agent()).is_err());
        handle(&mut db, &create_link, &agent()).unwrap();
        let query = json!({"op":"presentation.reference","surface_id":"links","element_id":"text","source_revision":0});
        assert!(handle(&mut db, &query, &agent())
            .unwrap_err()
            .contains("unauthorized"));
        assert_eq!(
            handle(&mut db, &query, &human()).unwrap()["target"],
            "surface-a"
        );
        let mut stale = query.clone();
        stale["source_revision"] = json!(1);
        assert!(handle(&mut db, &stale, &human())
            .unwrap_err()
            .contains("stale_revision"));
        let root = Principal {
            uid: 0,
            session: "compositor".into(),
        };
        handle(
            &mut db,
            &json!({"op":"outputs.register","output_id":"output-a","width":1920,"height":1080}),
            &root,
        )
        .unwrap();
        handle(&mut db,&json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"reference-workspace","expected_revisions":{"workspace-a":null},"operations":[{"op":"workspace.put","document":workspace()}]}),&human()).unwrap();
        let navigate = json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"reference-focus","expected_revisions":{"workspace-a":0},"operations":[{"op":"workspace.navigate","workspace_id":"workspace-a","surface_id":"links","element_id":"text","source_revision":0}]});
        assert!(handle(&mut db, &navigate, &agent())
            .unwrap_err()
            .contains("unauthorized"));
        let mut stale = navigate.clone();
        stale["operations"][0]["source_revision"] = json!(1);
        assert!(handle(&mut db, &stale, &human())
            .unwrap_err()
            .contains("stale_revision"));
        handle(&mut db, &navigate, &human()).unwrap();
        assert_eq!(
            snapshot(&db).unwrap()["documents"]["workspace-a"]["focus"]["surface_id"],
            "surface-a"
        );
        handle(&mut db,&json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"close-referenced","expected_revisions":{"workspace-a":1,"surface-a":0},"operations":[{"op":"workspace.edit","workspace_id":"workspace-a","edit":{"kind":"remove","surface_id":"surface-a"}},{"op":"surface.close","surface_id":"surface-a"}]}),&human()).unwrap();
        assert!(handle(&mut db, &query, &human())
            .unwrap_err()
            .contains("missing_reference"));
        assert!(snapshot(&db).unwrap()["documents"].get("links").is_some());
    }
    #[test]
    fn document_pages_are_bounded_scoped_and_refuse_mixed_revisions() {
        let mut db = fixture();
        for i in 0..5 {
            let mut doc = surface();
            doc["surface_id"] = json!(format!("surface-{i}"));
            doc["activity_id"] = json!(if i == 4 { "2" } else { "1" });
            db.execute(
                "INSERT INTO presentation_documents VALUES(?,?)",
                params![format!("surface-{i}"), doc.to_string()],
            )
            .unwrap();
        }
        let first = handle(
            &mut db,
            &json!({"op":"presentation.page","activity_id":"1","limit":2}),
            &human(),
        )
        .unwrap();
        assert_eq!(first["documents"].as_object().unwrap().len(), 2);
        assert_eq!(first["next_after_id"], "surface-1");
        let second=handle(&mut db,&json!({"op":"presentation.page","activity_id":"1","limit":2,"after_id":first["next_after_id"],"expected_cursor":first["event_cursor"]}),&human()).unwrap();
        assert_eq!(second["documents"].as_object().unwrap().len(), 2);
        assert!(second["next_after_id"].is_null());
        assert!(handle(
            &mut db,
            &json!({"op":"presentation.get","document_id":"surface-4","activity_id":"1"}),
            &human()
        )
        .is_err());
        assert_eq!(
            handle(
                &mut db,
                &json!({"op":"presentation.get","document_id":"surface-4","activity_id":"2"}),
                &human()
            )
            .unwrap()["activity_id"],
            "2"
        );
        for limit in [0, 65] {
            assert!(handle(
                &mut db,
                &json!({"op":"presentation.page","limit":limit}),
                &human()
            )
            .is_err());
        }
        create(&mut db);
        assert!(handle(
            &mut db,
            &json!({"op":"presentation.page","expected_cursor":first["event_cursor"]}),
            &human()
        )
        .unwrap_err()
        .contains("resync_required"));
    }
    #[test]
    fn document_page_byte_budget_keeps_large_collections_bounded() {
        let db = fixture();
        for i in 0..8 {
            let mut doc = surface();
            doc["surface_id"] = json!(format!("large-{i}"));
            doc["elements"]["text"]["props"]["text"] = json!("a".repeat(700_000));
            db.execute(
                "INSERT INTO presentation_documents VALUES(?,?)",
                params![format!("large-{i}"), doc.to_string()],
            )
            .unwrap();
        }
        let first = page(&db, &json!({"limit":64})).unwrap();
        assert_eq!(first["documents"].as_object().unwrap().len(), 2);
        assert!(first.to_string().len() < 2 * DOCUMENT_LIMIT);
        assert_eq!(first["next_after_id"], "large-1");
    }
    #[test]
    fn atomic_rejection_stale_and_deduplicated_receipts() {
        let mut db = fixture();
        let receipt = create(&mut db);
        let before = snapshot(&db).unwrap();
        let mut bad = props("bad", 0, "text", "Changed");
        bad["operations"]
            .as_array_mut()
            .unwrap()
            .push(json!({"op":"element.remove","surface_id":"surface-a","element_id":"input"}));
        assert!(handle(&mut db, &bad, &human())
            .unwrap_err()
            .contains("missing_reference"));
        assert_eq!(snapshot(&db).unwrap(), before);
        let request = props("change", 0, "text", "Changed");
        let r = handle(&mut db, &request, &human()).unwrap();
        assert_eq!(handle(&mut db, &request, &human()).unwrap(), r);
        assert!(
            handle(&mut db, &props("change", 0, "text", "Other"), &human())
                .unwrap_err()
                .contains("idempotency_conflict")
        );
        assert!(
            handle(&mut db, &props("stale", 0, "text", "Other"), &human())
                .unwrap_err()
                .contains("stale_revision")
        );
        assert_eq!(receipt["event_cursor"], 1);
        assert_eq!(r["event_cursor"], 2);
    }
    #[test]
    fn malformed_trees_unknown_fields_and_executable_links_are_rejected() {
        for case in 0..8 {
            let mut db = fixture();
            let mut s = surface();
            match case {
                0 => s["elements"]["root"]["slots"]["children"] = json!(["root"]),
                1 => s["elements"]["root"]["slots"]["children"] = json!(["text", "text", "input"]),
                2 => s["elements"]["text"]["type"] = json!("HTML@1"),
                3 => s["elements"]["text"]["props"]["shader"] = json!("execute"),
                4 => s["actor"] = json!("human"),
                5 => s["elements"]["text"]["type"] = json!("Link@1"),
                6 => {
                    s["elements"]["text"] =
                        json!({"type":"Link@1","props":{"label":"Run","url":"javascript:evil()"}})
                }
                7 => s["elements"]["extra"] = json!({"type":"Text@1","props":{"text":"orphan"}}),
                _ => unreachable!(),
            }
            let request = json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"bad","expected_revisions":{"surface-a":null},"operations":[{"op":"surface.create","document":s}]});
            assert!(handle(&mut db, &request, &human()).is_err(), "case {case}");
            assert_eq!(snapshot(&db).unwrap()["documents"], json!({}));
        }
    }
    #[test]
    fn numeric_bindings_use_the_released_catalog_number_type() {
        let mut db = fixture();
        let mut doc = surface();
        doc["elements"]["text"] = json!({"type":"Progress@1","props":{"label":"Observed fraction","value":{"binding":"number"}}});
        doc["bindings"]["number"] = json!({"source":"job:1","path":"/exit_code","access":"read"});
        let create = json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"numeric-binding","expected_revisions":{"surface-a":null},"operations":[{"op":"surface.create","document":doc}]});
        let mut bad = create.clone();
        bad["operations"][0]["document"]["bindings"]["number"]["path"] = json!("/status");
        assert!(handle(&mut db, &bad, &human()).is_err());
        assert!(handle(&mut db, &create, &human()).is_ok());
    }
    #[test]
    fn typed_source_bindings_are_live_and_cross_activity_access_is_rejected() {
        let mut db = fixture();
        let mut s = surface();
        s["elements"]["text"] =
            json!({"type":"Status@1","props":{"value":{"binding":"job-state"}}});
        s["bindings"] = json!({"job-state":{"source":"job:1","path":"/status","access":"read"}});
        let mut request = json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"source","expected_revisions":{"surface-a":null},"operations":[{"op":"surface.create","document":s}]});
        request["operations"][0]["document"]["bindings"]["job-state"]["source"] = json!("job:2");
        assert!(handle(&mut db, &request, &human())
            .unwrap_err()
            .contains("unauthorized"));
        request["operations"][0]["document"]["bindings"]["job-state"]["source"] = json!("job:1");
        handle(&mut db, &request, &human()).unwrap();
        let query = json!({"op":"binding.snapshot","surface_id":"surface-a"});
        assert_eq!(
            handle(&mut db, &query, &human()).unwrap()["bindings"]["job-state"]["value"],
            "running"
        );
        db.execute("UPDATE jobs SET status='failed',exit_code=7 WHERE id=1", [])
            .unwrap();
        assert_eq!(
            handle(&mut db, &query, &human()).unwrap()["bindings"]["job-state"]["value"],
            "failed"
        );
        db.execute("DELETE FROM jobs WHERE id=1", []).unwrap();
        let unavailable = handle(&mut db, &query, &human()).unwrap();
        assert_eq!(
            unavailable["bindings"]["job-state"]["availability"],
            "unavailable"
        );
        assert!(unavailable["bindings"]["job-state"]["value"].is_null());
    }
    #[test]
    fn native_input_and_recovered_drafts_survive_agent_updates() {
        let mut db = fixture();
        create(&mut db);
        handle(
            &mut db,
            &json!({"op":"interaction.begin","surface_id":"surface-a","element_id":"text"}),
            &human(),
        )
        .unwrap();
        assert!(
            handle(&mut db, &props("agent", 0, "text", "Gone"), &agent())
                .unwrap_err()
                .contains("interaction_conflict")
        );
        handle(&mut db,&json!({"op":"draft.save","surface_id":"surface-a","element_id":"text","expected_draft_revision":0,"draft":"Unsaved"}),&human()).unwrap();
        db.execute("UPDATE presentation_leases SET expires=0", [])
            .unwrap();
        assert!(
            handle(&mut db, &props("agent", 0, "text", "Gone"), &agent())
                .unwrap_err()
                .contains("interaction_conflict")
        );
        let recovered = handle(
            &mut db,
            &json!({"op":"draft.get","surface_id":"surface-a","element_id":"text"}),
            &human(),
        )
        .unwrap();
        assert_eq!(recovered["draft"], "Unsaved");
        assert!(handle(&mut db,&json!({"op":"draft.save","surface_id":"surface-a","element_id":"text","expected_draft_revision":0,"draft":"Stale"}),&human()).unwrap_err().contains("stale_revision"));
        handle(
            &mut db,
            &props("human", 0, "text", "Human change"),
            &human(),
        )
        .unwrap();
    }
    fn workspace() -> Value {
        json!({"protocol":PROTOCOL,"workspace_id":"workspace-a","activity_id":"1","revision":0,"outputs":{"output-a":{"tiles":{"kind":"leaf","surface_id":"surface-a"},"floating":[],"maximized":null}},"constraints":[],"focus":null})
    }
    #[test]
    fn output_resize_disconnect_and_restore_preserve_preferred_work() {
        let mut db = fixture();
        create(&mut db);
        let root = Principal {
            uid: 0,
            session: "compositor".into(),
        };
        let original =
            json!({"op":"outputs.register","output_id":"output-a","width":1920,"height":1080});
        handle(&mut db, &original, &root).unwrap();
        let mut w = workspace();
        w["outputs"]["output-a"]["tiles"] = Value::Null;
        w["outputs"]["output-a"]["floating"] =
            json!([{"surface_id":"surface-a","x":100,"y":80,"width":1000,"height":600}]);
        handle(&mut db,&json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"initial-float","expected_revisions":{"workspace-a":null},"operations":[{"op":"workspace.put","document":w}]}),&human()).unwrap();
        let before = get_document(&db, &json!({"document_id":"workspace-a"})).unwrap();
        handle(&mut db,&json!({"op":"outputs.register","output_id":"output-a","width":320,"height":240,"x":100,"y":200,"scale":2,"transform":"_90"}),&root).unwrap();
        assert_eq!(
            get_document(&db, &json!({"document_id":"workspace-a"})).unwrap(),
            before
        );
        handle(
            &mut db,
            &props("edit-during-pressure", 0, "text", "Still editable"),
            &human(),
        )
        .unwrap();
        let outputs = handle(&mut db, &json!({"op":"outputs.list"}), &human()).unwrap();
        assert_eq!(outputs["outputs"][0]["scale"], 2.);
        assert_eq!(outputs["outputs"][0]["transform"], "_90");
        assert_eq!(outputs["outputs"][0]["width"], 320.);
        let mut changed = before.clone();
        changed["outputs"]["output-a"]["floating"][0]["x"] = json!(120);
        let bad = json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"new-out-of-bounds","expected_revisions":{"workspace-a":0},"operations":[{"op":"workspace.put","document":changed}]});
        assert!(handle(&mut db, &bad, &human())
            .unwrap_err()
            .contains("constraint_conflict"));
        assert!(handle(
            &mut db,
            &json!({"op":"outputs.disconnect","output_id":"output-a"}),
            &agent()
        )
        .is_err());
        handle(
            &mut db,
            &json!({"op":"outputs.disconnect","output_id":"output-a"}),
            &root,
        )
        .unwrap();
        handle(
            &mut db,
            &props("edit-without-output", 1, "text", "Work retained"),
            &human(),
        )
        .unwrap();
        let state = handle(&mut db, &json!({"op":"outputs.list"}), &human()).unwrap();
        assert_eq!(state["outputs"][0]["connected"], false);
        assert!(handle(&mut db, &bad, &human())
            .unwrap_err()
            .contains("missing_reference"));
        handle(&mut db, &original, &root).unwrap();
        assert_eq!(
            get_document(&db, &json!({"document_id":"workspace-a"})).unwrap(),
            before
        );
        handle(
            &mut db,
            &json!({"op":"outputs.disconnect","output_id":"output-a"}),
            &root,
        )
        .unwrap();
        let close = json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"close-on-removed-output","expected_revisions":{"workspace-a":0,"surface-a":2},"operations":[{"op":"workspace.edit","workspace_id":"workspace-a","edit":{"kind":"remove","surface_id":"surface-a"}},{"op":"surface.close","surface_id":"surface-a"}]});
        assert!(handle(&mut db, &close, &human()).is_ok());
    }
    #[test]
    fn workspace_enforces_outputs_placements_sizes_focus_and_provenance() {
        let mut db = fixture();
        create(&mut db);
        let root = Principal {
            uid: 0,
            session: "compositor".into(),
        };
        assert!(handle(
            &mut db,
            &json!({"op":"outputs.register","output_id":"output-a","width":1280,"height":720}),
            &agent()
        )
        .is_err());
        handle(
            &mut db,
            &json!({"op":"outputs.register","output_id":"output-a","width":1280,"height":720}),
            &root,
        )
        .unwrap();
        let request = json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"workspace","expected_revisions":{"workspace-a":null},"operations":[{"op":"workspace.put","document":workspace()}]});
        let mut duplicate = request.clone();
        duplicate["operations"][0]["document"]["outputs"]["output-a"]["floating"] =
            json!([{"surface_id":"surface-a","x":0,"y":0,"width":100,"height":100}]);
        assert!(handle(&mut db, &duplicate, &human()).is_err());
        handle(&mut db, &request, &human()).unwrap();
        let mut focus = request.clone();
        focus["request_id"] = json!("focus");
        focus["expected_revisions"]["workspace-a"] = json!(0);
        focus["operations"][0]["document"]["focus"] =
            json!({"surface_id":"surface-a","element_id":"input"});
        assert!(handle(&mut db, &focus, &agent())
            .unwrap_err()
            .contains("steal focus"));
        handle(&mut db, &focus, &human()).unwrap();
        assert!(handle(
            &mut db,
            &json!({"op":"outputs.register","output_id":"output-a","width":50,"height":720}),
            &root
        )
        .is_err());
    }
    #[test]
    fn undo_is_compensating_idempotent_and_rejects_divergence() {
        let mut db = fixture();
        create(&mut db);
        let r = handle(&mut db, &props("first", 0, "text", "First"), &human()).unwrap();
        let undo = json!({"op":"presentation.undo","event_cursor":r["event_cursor"],"request_id":"undo-first"});
        let receipt = handle(&mut db, &undo, &human()).unwrap();
        assert_eq!(receipt["revisions"]["surface-a"], 2);
        assert_eq!(handle(&mut db, &undo, &human()).unwrap(), receipt);
        assert_eq!(
            snapshot(&db).unwrap()["documents"]["surface-a"]["elements"]["text"]["props"]["text"],
            "Hello"
        );
        assert!(handle(&mut db,&json!({"op":"presentation.undo","event_cursor":r["event_cursor"],"request_id":"different-undo"}),&human()).unwrap_err().contains("stale_revision"));
    }
    #[test]
    fn closed_identities_cannot_be_recycled_and_undo_keeps_revisions_monotonic() {
        let mut db = fixture();
        create(&mut db);
        let close = json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"close","expected_revisions":{"surface-a":0},"operations":[{"op":"surface.close","surface_id":"surface-a"}]});
        let receipt = handle(&mut db, &close, &human()).unwrap();
        let recycle = json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"recycle","expected_revisions":{"surface-a":null},"operations":[{"op":"surface.create","document":surface()}]});
        assert!(handle(&mut db, &recycle, &human()).is_err());
        let restored=handle(&mut db,&json!({"op":"presentation.undo","request_id":"restore","event_cursor":receipt["event_cursor"]}),&human()).unwrap();
        assert_eq!(restored["revisions"]["surface-a"], 2);
        assert!(handle(&mut db, &props("stale", 0, "text", "Old"), &human())
            .unwrap_err()
            .contains("stale_revision"));
    }
    #[test]
    fn inactive_activities_do_not_block_other_views() {
        let mut db = fixture();
        create(&mut db);
        db.execute("INSERT INTO removed_activities VALUES(1)", [])
            .unwrap();
        assert!(handle(&mut db, &props("inactive", 0, "text", "Hidden"), &human()).is_err());
        let mut doc = surface();
        doc["activity_id"] = json!("2");
        doc["surface_id"] = json!("surface-b");
        let other = json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"other","expected_revisions":{"surface-b":null},"operations":[{"op":"surface.create","document":doc}]});
        handle(&mut db, &other, &human()).unwrap();
        assert!(snapshot(&db).unwrap()["documents"]["surface-a"].is_object());
    }
    #[test]
    fn adversarial_update_cannot_recurse_through_an_editing_lease() {
        let mut db = fixture();
        create(&mut db);
        handle(
            &mut db,
            &json!({"op":"interaction.begin","surface_id":"surface-a","element_id":"input"}),
            &human(),
        )
        .unwrap();
        let cycle = json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"cycle","expected_revisions":{"surface-a":0},"operations":[{"op":"element.set_children","surface_id":"surface-a","element_id":"root","slot":"children","children":["root"]}]});
        assert!(handle(&mut db, &cycle, &agent()).is_err());
        assert_eq!(
            snapshot(&db).unwrap()["documents"]["surface-a"]["revision"],
            0
        );
    }
    #[test]
    fn compact_change_pages_preserve_tombstones_and_guard_document_reads() {
        let mut db = fixture();
        create(&mut db);
        handle(
            &mut db,
            &props("compact-edit", 0, "text", "Private body"),
            &human(),
        )
        .unwrap();
        let first = changes(&db, &json!({"after_cursor":0,"limit":1})).unwrap();
        assert_eq!(first["latest_cursor"], 2);
        assert_eq!(first["next_cursor"], 1);
        assert_eq!(first["has_more"], true);
        assert_eq!(first["events"][0]["revisions"]["surface-a"], 0);
        assert!(!first.to_string().contains("Private body"));
        let second = changes(&db, &json!({"after_cursor":1,"expected_cursor":2})).unwrap();
        assert_eq!(second["events"][0]["revisions"]["surface-a"], 1);
        assert_eq!(second["next_cursor"], 2);
        assert_eq!(second["has_more"], false);
        assert!(
            get_document(&db, &json!({"document_id":"surface-a","expected_cursor":1}))
                .unwrap_err()
                .contains("resync_required")
        );
        assert_eq!(
            get_document(&db, &json!({"document_id":"surface-a","expected_cursor":2})).unwrap()
                ["revision"],
            1
        );
        db.execute("INSERT INTO presentation_events(uid,request,before_state,after_state,receipt) VALUES(0,'deleted','{}','{}',?)",[json!({"revisions":{"surface-a":null}}).to_string()]).unwrap();
        let removed = changes(&db, &json!({"after_cursor":2})).unwrap();
        assert!(removed["events"][0]["revisions"]
            .get("surface-a")
            .unwrap()
            .is_null());
        assert!(changes(&db, &json!({"after_cursor":1,"expected_cursor":2}))
            .unwrap_err()
            .contains("resync_required"));
        assert!(changes(&db, &json!({"after_cursor":99}))
            .unwrap_err()
            .contains("resync_required"));
        for value in [
            json!({"after_cursor":-1}),
            json!({"after_cursor":true}),
            json!({"limit":129}),
        ] {
            assert!(changes(&db, &value).is_err());
        }
        // Large receipts must split even when the requested item count would fit.
        let revisions: BTreeMap<_, _> = (0..128)
            .map(|i| (format!("{}-{i}", "x".repeat(250)), json!(i)))
            .collect();
        for i in 0..32 {
            db.execute("INSERT INTO presentation_events(uid,request,before_state,after_state,receipt) VALUES(0,?,'{}','{}',?)",params![format!("large-{i}"),json!({"revisions":revisions}).to_string()]).unwrap();
        }
        let large = changes(&db, &json!({"after_cursor":3,"limit":128})).unwrap();
        assert!(large.to_string().len() <= 512 * 1024);
        assert_eq!(large["has_more"], true);
        assert!(large["events"].as_array().unwrap().len() < 32);
    }
    #[test]
    fn legacy_snapshot_and_subscription_require_bounded_reads_without_skipping_events() {
        let mut db = fixture();
        create(&mut db);
        let body = json!({"payload":"日".repeat(250000)}).to_string();
        for i in 0..12 {
            db.execute("INSERT INTO presentation_events(uid,request,before_state,after_state,receipt) VALUES(0,?,'{}',?,'{}')", params![format!("bounded-{i}"), body]).unwrap();
        }
        let mut cursor = 1;
        let mut seen = Vec::new();
        loop {
            let page = handle(
                &mut db,
                &json!({"op":"presentation.subscribe","after_cursor":cursor}),
                &human(),
            )
            .unwrap();
            assert!(page.to_string().len() < TRANSACTION_LIMIT);
            seen.extend(
                page["events"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|e| e["event_cursor"].as_i64().unwrap()),
            );
            cursor = page["next_cursor"].as_i64().unwrap();
            if page["has_more"] == false {
                break;
            }
        }
        assert_eq!(seen, (2..=13).collect::<Vec<_>>());
        for invalid in [json!(true), json!("1"), json!(1.5)] {
            assert!(handle(
                &mut db,
                &json!({"op":"presentation.subscribe","after_cursor":invalid}),
                &human()
            )
            .is_err());
        }
        db.execute(
            "UPDATE presentation_events SET after_state=? WHERE cursor=2",
            [json!({"payload":"x".repeat(TRANSACTION_LIMIT)}).to_string()],
        )
        .unwrap();
        assert!(handle(
            &mut db,
            &json!({"op":"presentation.subscribe","after_cursor":1}),
            &human()
        )
        .unwrap_err()
        .contains("pagination_required"));
        // Guard before decoding bodies: legacy snapshots cannot allocate an entire large workspace.
        db.execute(
            "UPDATE presentation_documents SET body=?",
            ["x".repeat(TRANSACTION_LIMIT)],
        )
        .unwrap();
        assert!(snapshot(&db).unwrap_err().contains("pagination_required"));
    }
    #[test]
    fn ordered_subscription_and_reopen_preserve_receipts() {
        let path = std::env::temp_dir().join(format!(
            "agentos-presentation-{}-{}.sqlite",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let db = fixture();
        // Exercise persistence using SQLite's VACUUM INTO, without optional backup features.
        db.execute("VACUUM INTO ?", [path.to_str().unwrap()])
            .unwrap();
        drop(db);
        let mut db = Connection::open(&path).unwrap();
        create(&mut db);
        let request = props("change", 0, "text", "Saved");
        let receipt = handle(&mut db, &request, &human()).unwrap();
        drop(db);
        let mut db = Connection::open(&path).unwrap();
        init(&db).unwrap();
        assert_eq!(handle(&mut db, &request, &human()).unwrap(), receipt);
        let events = handle(
            &mut db,
            &json!({"op":"presentation.subscribe","after_cursor":1}),
            &human(),
        )
        .unwrap();
        assert_eq!(events["events"].as_array().unwrap().len(), 1);
        assert_eq!(events["events"][0]["event_cursor"], 2);
        assert!(handle(
            &mut db,
            &json!({"op":"presentation.subscribe","after_cursor":500}),
            &human()
        )
        .unwrap_err()
        .contains("resync_required"));
        drop(db);
        std::fs::remove_file(path).unwrap();
    }
    #[test]
    fn committing_a_native_draft_is_atomic_scoped_and_idempotent() {
        let mut db = fixture();
        create(&mut db);
        handle(
            &mut db,
            &json!({"op":"interaction.begin","surface_id":"surface-a","element_id":"input"}),
            &human(),
        )
        .unwrap();
        handle(&mut db,&json!({"op":"draft.save","surface_id":"surface-a","element_id":"input","expected_draft_revision":0,"draft":"Reviewed λ"}),&human()).unwrap();
        let commit = json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"commit-draft","expected_revisions":{"surface-a":0},"operations":[{"op":"draft.commit","surface_id":"surface-a","element_id":"input","expected_draft_revision":1}]});
        assert!(handle(&mut db, &commit, &agent()).is_err());
        let mut broken = commit.clone();
        broken["request_id"] = json!("atomic-bad");
        broken["operations"]
            .as_array_mut()
            .unwrap()
            .push(json!({"op":"element.remove","surface_id":"surface-a","element_id":"root"}));
        assert!(handle(&mut db, &broken, &human()).is_err());
        assert_eq!(
            handle(
                &mut db,
                &json!({"op":"draft.get","surface_id":"surface-a","element_id":"input"}),
                &human()
            )
            .unwrap()["draft"],
            "Reviewed λ"
        );
        let first = handle(&mut db, &commit, &human()).unwrap();
        assert_eq!(handle(&mut db, &commit, &human()).unwrap(), first);
        assert_eq!(
            snapshot(&db).unwrap()["documents"]["surface-a"]["elements"]["input"]["props"]["value"],
            "Reviewed λ"
        );
        let draft = handle(
            &mut db,
            &json!({"op":"draft.get","surface_id":"surface-a","element_id":"input"}),
            &human(),
        )
        .unwrap();
        assert!(draft["draft"].is_null());
        assert_eq!(draft["draft_revision"], 2);
    }
    #[test]
    fn broker_observations_are_scoped_monotonic_and_unwritable_by_presentation_clients() {
        let mut db = fixture();
        let root = Principal {
            uid: 0,
            session: "broker-fixture".into(),
        };
        let source = format!("broker:{}", "a".repeat(32));
        let mut publication = json!({"op":"source.publish","source":source,"activity_id":"1","source_revision":0,"values":{"status":"running","exit_code":null,"error":null,"created_at":1,"finished_at":null}});
        assert!(handle(&mut db, &publication, &agent())
            .unwrap_err()
            .contains("unauthorized"));
        assert!(handle(&mut db, &publication, &human())
            .unwrap_err()
            .contains("unauthorized"));
        handle(&mut db, &publication, &root).unwrap();
        let mut doc = surface();
        doc["bindings"] =
            json!({"broker-state":{"source":source,"path":"/status","access":"read"}});
        doc["elements"]["status"] =
            json!({"type":"Status@1","props":{"value":{"binding":"broker-state"}}});
        doc["elements"]["root"]["slots"]["children"]
            .as_array_mut()
            .unwrap()
            .push(json!("status"));
        let create = json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"broker-source-view","expected_revisions":{"surface-a":null},"operations":[{"op":"surface.create","document":doc}]});
        let mut foreign = create.clone();
        foreign["operations"][0]["document"]["activity_id"] = json!("2");
        assert!(handle(&mut db, &foreign, &human())
            .unwrap_err()
            .contains("unauthorized"));
        handle(&mut db, &create, &human()).unwrap();
        let read = json!({"op":"binding.snapshot","surface_id":"surface-a"});
        assert_eq!(
            handle(&mut db, &read, &human()).unwrap()["bindings"]["broker-state"]["value"],
            "running"
        );
        publication["source_revision"] = json!(1);
        publication["values"]["status"] = json!("failed");
        handle(&mut db, &publication, &root).unwrap();
        assert_eq!(
            handle(&mut db, &read, &human()).unwrap()["bindings"]["broker-state"]["value"],
            "failed"
        );
        publication["values"]["status"] = json!("succeeded");
        let conflict: Value =
            serde_json::from_str(&handle(&mut db, &publication, &root).unwrap_err()).unwrap();
        assert_eq!(conflict["code"], "stale_revision");
        assert_eq!(conflict["source"], source);
        assert_eq!(conflict["current_revision"], 1);
        publication["source_revision"] = json!(0);
        let older: Value =
            serde_json::from_str(&handle(&mut db, &publication, &root).unwrap_err()).unwrap();
        assert_eq!(older["current_revision"], 1);
        let binding = handle(&mut db, &read, &human()).unwrap();
        assert_eq!(
            binding["bindings"]["broker-state"]["availability"], "unavailable",
            "A dead fixture publisher must not claim a live source"
        );
        // The source's metadata exposes only registered paths; stdin is never published.
        assert_eq!(
            handle(
                &mut db,
                &json!({"op":"source.list","activity_id":"1"}),
                &agent()
            )
            .unwrap()["sources"][0]["paths"]
                .as_array()
                .unwrap()
                .len(),
            5
        );
    }
    #[test]
    fn table_documents_validate_keyed_rows_before_native_allocation() {
        let mut db = fixture();
        let mut doc = surface();
        doc["elements"]["text"] = json!({"type":"Table@1","props":{"label":"Observed resources","columns":["Name","Status"],"rows":[{"id":"item-a","cells":["日本語","Ready"]},{"id":"item-b","cells":["Other","Pending"]}]}});
        let create = json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"table-view","expected_revisions":{"surface-a":null},"operations":[{"op":"surface.create","document":doc}]});
        for rows in [
            json!([{"id":"a","cells":["Missing column"]}]),
            json!([{"id":"a","cells":["Name","Ready"]},{"id":"a","cells":["Other","Ready"]}]),
            json!([{"id":"a","cells":["Name",42]}]),
        ] {
            let mut bad = create.clone();
            bad["operations"][0]["document"]["elements"]["text"]["props"]["rows"] = rows;
            assert!(handle(&mut db, &bad, &human()).is_err());
        }
        handle(&mut db, &create, &human()).unwrap();
    }
    #[test]
    fn lists_and_key_value_groups_enforce_exact_cells_and_accessible_labels() {
        for (kind, cells) in [
            ("List@1", json!(["Observed item"])),
            ("KeyValue@1", json!(["Kind", "File"])),
        ] {
            let mut db = fixture();
            let mut doc = surface();
            doc["elements"]["text"] = json!({"type":kind,"props":{"label":"Observed data","rows":[{"id":"item-a","cells":cells}]}});
            let create = json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"collection","expected_revisions":{"surface-a":null},"operations":[{"op":"surface.create","document":doc}]});
            let mut bad = create.clone();
            bad["operations"][0]["document"]["elements"]["text"]["props"]["rows"][0]["cells"] =
                json!(["a", "b", "c"]);
            assert!(handle(&mut db, &bad, &human())
                .unwrap_err()
                .contains("cell count"));
            for label in ["".to_string(), " ".into(), "x".repeat(257)] {
                let mut bad = create.clone();
                bad["operations"][0]["document"]["elements"]["text"]["props"]["label"] =
                    json!(label);
                assert!(handle(&mut db, &bad, &human())
                    .unwrap_err()
                    .contains("accessible label"));
            }
            handle(&mut db, &create, &human()).unwrap();
        }
    }
    #[test]
    fn labeled_sections_and_scroll_regions_validate_complete_nested_trees() {
        let mut db = fixture();
        let mut doc = surface();
        doc["elements"]["root"] =
            json!({"type":"Section@1","props":{"label":"Details"},"slots":{"children":["region"]}});
        doc["elements"]["region"] = json!({"type":"Scroll@1","props":{"label":"Observed content","spacing":"compact"},"slots":{"children":["text","input"]}});
        let create = json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"section-view","expected_revisions":{"surface-a":null},"operations":[{"op":"surface.create","document":doc}]});
        for element in ["root", "region"] {
            let mut bad = create.clone();
            bad["operations"][0]["document"]["elements"][element]["props"]["label"] = json!(" ");
            assert!(handle(&mut db, &bad, &human())
                .unwrap_err()
                .contains("accessible label"));
            bad["operations"][0]["document"]["elements"][element]["props"]
                .as_object_mut()
                .unwrap()
                .remove("label");
            assert!(handle(&mut db, &bad, &human()).is_err());
        }
        let mut bad = create.clone();
        bad["operations"][0]["document"]["elements"]["region"]["slots"]["children"] =
            json!(["root"]);
        assert!(handle(&mut db, &bad, &human()).is_err());
        handle(&mut db, &create, &human()).unwrap();
    }
    #[test]
    fn tabs_and_splits_require_complete_bounded_labeled_children() {
        for kind in ["Split@1", "Tabs@1"] {
            let mut db = fixture();
            let mut doc = surface();
            doc["elements"]["root"] = json!({"type":kind,"props":{"label":"Details"},"slots":{"children":["text","input"]}});
            if kind == "Tabs@1" {
                doc["elements"]["root"]["props"]["labels"] = json!(["Text", "Input"]);
            }
            let create = json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"panes-view","expected_revisions":{"surface-a":null},"operations":[{"op":"surface.create","document":doc}]});
            let mut bad = create.clone();
            bad["operations"][0]["document"]["elements"]["root"]["slots"]
                .as_object_mut()
                .unwrap()
                .remove("children");
            assert!(handle(&mut db, &bad, &human()).is_err());
            if kind == "Tabs@1" {
                for labels in [json!(["Text"]), json!(["Text", " "]), json!([])] {
                    bad = create.clone();
                    bad["operations"][0]["document"]["elements"]["root"]["props"]["labels"] =
                        labels;
                    assert!(handle(&mut db, &bad, &human()).is_err());
                }
            }
            handle(&mut db, &create, &human()).unwrap();
        }
    }
    #[test]
    fn choice_and_toggle_drafts_are_typed_atomic_and_user_owned() {
        for (kind, props, valid, invalid, result) in [
            (
                "Choice@1",
                json!({"label":"Density","options":["Compact","Comfortable"],"value":"Comfortable"}),
                "Compact",
                "Unknown",
                json!("Compact"),
            ),
            (
                "Toggle@1",
                json!({"label":"Wrap","value":true}),
                "false",
                "yes",
                json!(false),
            ),
        ] {
            let mut db = fixture();
            let mut doc = surface();
            doc["elements"]["input"] = json!({"type":kind,"props":props});
            let create = json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"selection-view","expected_revisions":{"surface-a":null},"operations":[{"op":"surface.create","document":doc}]});
            if kind == "Choice@1" {
                for options in [
                    json!(["Compact", "Compact"]),
                    json!([" ", "Comfortable"]),
                    json!(["Compact"]),
                ] {
                    let mut bad = create.clone();
                    bad["operations"][0]["document"]["elements"]["input"]["props"]["options"] =
                        options;
                    assert!(handle(&mut db, &bad, &human()).is_err());
                }
            }
            handle(&mut db, &create, &human()).unwrap();
            handle(
                &mut db,
                &json!({"op":"interaction.begin","surface_id":"surface-a","element_id":"input"}),
                &human(),
            )
            .unwrap();
            handle(&mut db, &json!({"op":"draft.save","surface_id":"surface-a","element_id":"input","expected_draft_revision":0,"draft":invalid}), &human()).unwrap();
            let mut commit = json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"selection-commit","expected_revisions":{"surface-a":0},"operations":[{"op":"draft.commit","surface_id":"surface-a","element_id":"input","expected_draft_revision":1}]});
            assert!(handle(&mut db, &commit, &human()).is_err());
            assert_eq!(
                snapshot(&db).unwrap()["documents"]["surface-a"]["elements"]["input"]["props"],
                props
            );
            handle(&mut db, &json!({"op":"draft.save","surface_id":"surface-a","element_id":"input","expected_draft_revision":1,"draft":valid}), &human()).unwrap();
            commit["operations"][0]["expected_draft_revision"] = json!(2);
            assert!(handle(&mut db, &commit, &agent()).is_err());
            handle(&mut db, &commit, &human()).unwrap();
            assert_eq!(
                snapshot(&db).unwrap()["documents"]["surface-a"]["elements"]["input"]["props"]
                    ["value"],
                result
            );
        }
    }
    #[test]
    fn rich_text_and_chart_literals_reject_unbounded_or_executable_shapes() {
        for (kind, props, invalid) in [
            (
                "RichText@1",
                json!({"runs":[{"text":"Literal <script>日本語","style":"strong"}]}),
                json!({"runs":[{"text":"Content","style":"markup"}]}),
            ),
            (
                "Chart@1",
                json!({"label":"Comparison","points":[{"id":"a","label":"A","value":-2.5}]}),
                json!({"label":"Comparison","points":[{"id":"a","label":"A","value":1e13}]}),
            ),
        ] {
            let mut db = fixture();
            let mut doc = surface();
            doc["elements"]["text"] = json!({"type":kind,"props":props});
            let create = json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"reading-view","expected_revisions":{"surface-a":null},"operations":[{"op":"surface.create","document":doc}]});
            let mut bad = create.clone();
            bad["operations"][0]["document"]["elements"]["text"]["props"] = invalid;
            assert!(handle(&mut db, &bad, &human()).is_err());
            handle(&mut db, &create, &human()).unwrap();
            assert_eq!(
                snapshot(&db).unwrap()["documents"]["surface-a"]["elements"]["text"]["props"],
                props
            );
        }
    }
    #[test]
    fn image_resources_are_immutable_scoped_human_owned_and_metadata_only_for_models() {
        let mut db = fixture();
        let bytes = include_bytes!("../tests/fixtures/pixel.png");
        let hex = bytes
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        let reference = format!("resource-{}", "a".repeat(32));
        let publish = json!({"op":"resource.publish","activity_id":"1","reference":reference,"label":"Blue pixel","png_hex":hex});
        assert!(handle(&mut db, &publish, &agent())
            .unwrap_err()
            .contains("unauthorized"));
        let receipt = handle(&mut db, &publish, &human()).unwrap();
        assert_eq!(handle(&mut db, &publish, &human()).unwrap(), receipt);
        let mut changed = publish.clone();
        changed["label"] = json!("Different image");
        assert!(handle(&mut db, &changed, &human())
            .unwrap_err()
            .contains("immutable_resource"));
        let get = json!({"op":"resource.get","activity_id":"1","reference":reference});
        assert_eq!(handle(&mut db, &get, &human()).unwrap()["png_hex"], hex);
        assert!(handle(&mut db, &get, &agent()).is_err());
        assert!(handle(
            &mut db,
            &get,
            &Principal {
                uid: 1001,
                session: "another-user".into()
            }
        )
        .is_err());
        assert!(handle(
            &mut db,
            &json!({"op":"resource.get","activity_id":"2","reference":reference}),
            &human()
        )
        .is_err());
        let list = handle(
            &mut db,
            &json!({"op":"resource.list","activity_id":"1"}),
            &agent(),
        )
        .unwrap();
        assert_eq!(list["resources"][0]["reference"], reference);
        assert!(list["resources"][0].get("png_hex").is_none());
        let mut doc = surface();
        doc["elements"]["text"] =
            json!({"type":"Image@1","props":{"label":"Blue pixel","reference":reference}});
        let create = json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"image-view","expected_revisions":{"surface-a":null},"operations":[{"op":"surface.create","document":doc}]});
        let mut bad = create.clone();
        bad["operations"][0]["document"]["elements"]["text"]["props"]["reference"] =
            json!("/etc/shadow");
        assert!(handle(&mut db, &bad, &human()).is_err());
        bad = create.clone();
        bad["operations"][0]["document"]["activity_id"] = json!("2");
        assert!(handle(&mut db, &bad, &human()).is_err());
        handle(&mut db, &create, &human()).unwrap();
    }
    #[test]
    fn file_metadata_is_typed_private_scoped_and_monotonic() {
        let mut db = fixture();
        let root = Principal {
            uid: 0,
            session: "file-fixture".into(),
        };
        let source = format!("file:{}", "b".repeat(32));
        let mut publication = json!({"op":"source.publish","source":source,"activity_id":"1","source_revision":1,"values":{"path":"/tmp/note","kind":"file","size_bytes":123,"mode":420,"modified_at":2.5,"measured_at":3.5}});
        assert!(handle(&mut db, &publication, &human())
            .unwrap_err()
            .contains("unauthorized"));
        assert!(handle(&mut db, &publication, &agent())
            .unwrap_err()
            .contains("unauthorized"));
        handle(&mut db, &publication, &root).unwrap();
        let mut doc = surface();
        doc["bindings"] =
            json!({"file-size":{"source":source,"path":"/size_text","access":"read"}});
        doc["elements"]["status"] =
            json!({"type":"Status@1","props":{"value":{"binding":"file-size"}}});
        doc["elements"]["root"]["slots"]["children"]
            .as_array_mut()
            .unwrap()
            .push(json!("status"));
        let create = json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"file-view","expected_revisions":{"surface-a":null},"operations":[{"op":"surface.create","document":doc}]});
        let mut bad = create.clone();
        bad["operations"][0]["document"]["activity_id"] = json!("2");
        assert!(handle(&mut db, &bad, &human())
            .unwrap_err()
            .contains("unauthorized"));
        bad = create.clone();
        bad["operations"][0]["document"]["bindings"]["file-size"]["path"] = json!("/content");
        assert!(handle(&mut db, &bad, &human()).is_err());
        handle(&mut db, &create, &human()).unwrap();
        let query = json!({"op":"binding.snapshot","surface_id":"surface-a"});
        let observed = handle(&mut db, &query, &human()).unwrap();
        assert_eq!(observed["bindings"]["file-size"]["value"], "123 bytes");
        assert_eq!(observed["bindings"]["file-size"]["observed_at"], 3.5);
        let mode = crate::presentation_sources::binding(&db, &source, "1", "/mode_text").unwrap();
        assert_eq!(mode["value"], "0644");
        for change in [
            json!({"path":"/tmp/other"}),
            json!({"content":"private"}),
            json!({"size_bytes":-1}),
            json!({"mode":8192}),
        ] {
            let mut bad = publication.clone();
            bad["source_revision"] = json!(2);
            for (key, value) in change.as_object().unwrap() {
                bad["values"][key] = value.clone();
            }
            assert!(handle(&mut db, &bad, &root).is_err());
        }
        let mut bad = publication.clone();
        bad["activity_id"] = json!("2");
        bad["source_revision"] = json!(2);
        assert!(handle(&mut db, &bad, &root)
            .unwrap_err()
            .contains("unauthorized"));
        publication["values"]["size_bytes"] = json!(42);
        assert!(handle(&mut db, &publication, &root)
            .unwrap_err()
            .contains("stale_revision"));
        publication["source_revision"] = json!(2);
        handle(&mut db, &publication, &root).unwrap();
        assert_eq!(
            handle(&mut db, &query, &human()).unwrap()["bindings"]["file-size"]["value"],
            "42 bytes"
        );
        publication["source_revision"] = json!(3);
        publication["values"]["kind"] = json!("missing");
        publication["values"]["size_bytes"] = Value::Null;
        handle(&mut db, &publication, &root).unwrap();
        assert_eq!(
            handle(&mut db, &query, &human()).unwrap()["bindings"]["file-size"]["value"],
            "Unavailable"
        );
        let listing = handle(
            &mut db,
            &json!({"op":"source.list","activity_id":"1"}),
            &agent(),
        )
        .unwrap();
        let row = listing["sources"]
            .as_array()
            .unwrap()
            .iter()
            .find(|r| r["source"] == source)
            .unwrap();
        assert_eq!(row["paths"].as_array().unwrap().len(), 9);
        assert!(!row.to_string().contains("/content"));
    }
    #[test]
    fn conventional_window_metadata_is_typed_scoped_and_host_observed() {
        let mut db = fixture();
        let root = Principal {
            uid: 0,
            session: "compositor".into(),
        };
        let mut observed = json!({"op":"host.surface","surface_id":"window-fixture","activity_id":"1","title":"Original title","app_id":"org.example.Editor","connected":true});
        assert!(handle(&mut db, &observed, &agent()).is_err());
        handle(&mut db, &observed, &root).unwrap();
        let mut doc = surface();
        doc["elements"]["text"] =
            json!({"type":"Status@1","props":{"value":{"binding":"window-title"}}});
        doc["bindings"]["window-title"] =
            json!({"source":"window:window-fixture","path":"/title","access":"read"});
        let create = json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"window-binding","expected_revisions":{"surface-a":null},"operations":[{"op":"surface.create","document":doc}]});
        let mut foreign = create.clone();
        foreign["operations"][0]["document"]["activity_id"] = json!("2");
        assert!(handle(&mut db, &foreign, &agent()).is_err());
        let mut bad = create.clone();
        bad["operations"][0]["document"]["bindings"]["window-title"]["path"] = json!("/private");
        assert!(handle(&mut db, &bad, &agent()).is_err());
        handle(&mut db, &create, &agent()).unwrap();
        let query = json!({"op":"binding.snapshot","surface_id":"surface-a"});
        let first = handle(&mut db, &query, &human()).unwrap();
        assert_eq!(first["bindings"]["window-title"]["value"], "Original title");
        observed["title"] = json!("Updated λ");
        handle(&mut db, &observed, &root).unwrap();
        let changed = handle(&mut db, &query, &human()).unwrap();
        assert_eq!(changed["bindings"]["window-title"]["value"], "Updated λ");
        assert!(
            changed["bindings"]["window-title"]["source_revision"].as_i64()
                > first["bindings"]["window-title"]["source_revision"].as_i64()
        );
        handle(&mut db, &observed, &root).unwrap();
        assert_eq!(
            handle(&mut db, &query, &human()).unwrap()["bindings"]["window-title"]
                ["source_revision"],
            changed["bindings"]["window-title"]["source_revision"]
        );
        let source = crate::presentation_hosts::source(&db, "window-fixture")
            .unwrap()
            .unwrap();
        assert_eq!(source["values"]["app_id"], "org.example.Editor");
        assert_eq!(source["availability"], "unavailable");
        let mut cursor = String::new();
        let mut sources = Vec::new();
        loop {
            let page = handle(
                &mut db,
                &json!({"op":"source.list","activity_id":"1","limit":1,"after":cursor}),
                &agent(),
            )
            .unwrap();
            sources.extend(page["sources"].as_array().unwrap().iter().cloned());
            if page["has_more"] == false {
                break;
            }
            cursor = page["next"].as_str().unwrap().into();
        }
        assert!(sources
            .iter()
            .any(|row| row["source"] == "window:window-fixture" && row["paths"][0] == "/title"));
        assert!(sources.iter().any(|row| row["source"] == "job:1"));
    }
    #[test]
    fn dead_host_connections_do_not_exhaust_capacity_or_inflate_live_snapshots() {
        let mut db = fixture();
        for i in 0..1024 {
            db.execute("INSERT INTO presentation_host_surfaces VALUES(?, '1', 0, '999999999:1', 'Old app', 'old.app', 1, 0)",[format!("retired-{i}")]).unwrap();
        }
        let root = Principal {
            uid: 0,
            session: "new-host".into(),
        };
        handle(&mut db,&json!({"op":"host.surface","surface_id":"new-app","activity_id":"1","title":"New app","app_id":"new.app","connected":true}),&root).unwrap();
        let connected: i64 = db
            .query_row(
                "SELECT COUNT(*) FROM presentation_host_surfaces WHERE connected=1",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(connected, 1);
        assert!(snapshot(&db).unwrap()["host_surfaces"]
            .as_object()
            .unwrap()
            .is_empty());
        let stored: i64 = db
            .query_row("SELECT COUNT(*) FROM presentation_host_surfaces", [], |r| {
                r.get(0)
            })
            .unwrap();
        assert_eq!(
            stored, 1025,
            "Restore metadata must survive process retirement"
        );
    }
    #[test]
    fn conventional_reconnect_requires_an_unambiguous_authenticated_process_and_dead_host() {
        let mut db = fixture();
        let old = Principal {
            uid: 0,
            session: "4294967295:0".into(),
        };
        let new = Principal {
            uid: 0,
            session: "new-host".into(),
        };
        let observation = json!({"op":"host.surface","surface_id":"persisted-window","activity_id":"1","title":"Editor","app_id":"example.Editor","connected":true,"client_uid":1000,"client_session":"12345:67890"});
        handle(&mut db, &observation, &old).unwrap();
        let previous = crate::presentation_hosts::source(&db, "persisted-window")
            .unwrap()
            .unwrap()["source_revision"]
            .as_i64()
            .unwrap();
        let mut reconnect = observation.clone();
        reconnect["surface_id"] = json!("new-ephemeral-window");
        reconnect["title"] = json!("Updated title");
        assert!(handle(&mut db, &reconnect, &agent()).is_err());
        let receipt = handle(&mut db, &reconnect, &new).unwrap();
        assert_eq!(receipt["surface_id"], "persisted-window");
        assert_eq!(receipt["reconciled"], true);
        assert!(
            crate::presentation_hosts::source(&db, "persisted-window")
                .unwrap()
                .unwrap()["source_revision"]
                .as_i64()
                .unwrap()
                > previous
        );
        assert_eq!(
            db.query_row("SELECT COUNT(*) FROM presentation_host_surfaces", [], |r| r
                .get::<_, i64>(0))
                .unwrap(),
            1
        );
        let mut changed_peer = observation.clone();
        changed_peer["client_session"] = json!("12345:67891");
        assert!(handle(&mut db, &changed_peer, &new).is_err());
        changed_peer["surface_id"] = json!("different-process-window");
        assert_eq!(
            handle(&mut db, &changed_peer, &new).unwrap()["surface_id"],
            "different-process-window"
        );
        let mut second = observation.clone();
        second["surface_id"] = json!("second-window");
        handle(&mut db, &second, &new).unwrap();
        // Multiple same-process windows are ambiguous after a compositor failure.
        db.execute(
            "UPDATE presentation_host_surfaces SET session='4294967295:0'",
            [],
        )
        .unwrap();
        reconnect["surface_id"] = json!("ambiguous-reconnect");
        assert_eq!(
            handle(&mut db, &reconnect, &new).unwrap()["surface_id"],
            "ambiguous-reconnect"
        );
    }
    #[test]
    fn conventional_reconnect_never_adopts_another_live_compositors_window() {
        let mut db = fixture();
        let old = Principal {
            uid: 0,
            session: {
                let Ok(stat) =
                    std::fs::read_to_string(format!("/proc/{}/stat", std::process::id()))
                else {
                    return;
                };
                let start = stat
                    .rsplit_once(')')
                    .unwrap()
                    .1
                    .split_whitespace()
                    .nth(19)
                    .unwrap();
                format!("{}:{start}", std::process::id())
            },
        };
        let new = Principal {
            uid: 0,
            session: "new-host".into(),
        };
        let observation = json!({"op":"host.surface","surface_id":"live-window","activity_id":"1","title":"Editor","app_id":"example.Editor","connected":true,"client_uid":1000,"client_session":"12345:67890"});
        handle(&mut db, &observation, &old).unwrap();
        let mut reconnect = observation;
        reconnect["surface_id"] = json!("second-host-window");
        assert_eq!(
            handle(&mut db, &reconnect, &new).unwrap()["surface_id"],
            "second-host-window"
        );
    }
    #[test]
    fn human_reconnect_preserves_logical_identity_and_durable_receipt() {
        let Ok(stat) = std::fs::read_to_string(format!("/proc/{}/stat", std::process::id())) else {
            return;
        };
        let start = stat
            .rsplit_once(')')
            .unwrap()
            .1
            .split_whitespace()
            .nth(19)
            .unwrap();
        let host = Principal {
            uid: 0,
            session: format!("{}:{start}", std::process::id()),
        };
        let old = Principal {
            uid: 0,
            session: "4294967295:0".into(),
        };
        let mut db = fixture();
        let missing = json!({"op":"host.surface","surface_id":"missing-editor","activity_id":"1","title":"Old editor","app_id":"example.Editor","connected":true,"client_uid":1000,"client_session":"100:1"});
        let returning = json!({"op":"host.surface","surface_id":"returning-editor","activity_id":"1","title":"Returning editor","app_id":"example.Editor","connected":true,"client_uid":1000,"client_session":"101:2"});
        handle(&mut db, &missing, &old).unwrap();
        handle(&mut db, &returning, &host).unwrap();
        let request = json!({"op":"host.reconnect","request_id":"explicit-reconnect","missing_surface":"missing-editor","live_surface":"returning-editor","missing_revision":1,"live_revision":1});
        assert!(handle(&mut db, &request, &agent()).is_err());
        let mut stale = request.clone();
        stale["live_revision"] = json!(2);
        assert!(handle(&mut db, &stale, &human())
            .unwrap_err()
            .contains("unauthorized"));
        assert!(handle(&mut db, &stale, &host)
            .unwrap_err()
            .contains("stale_revision"));
        handle(
            &mut db,
            &json!({"op":"outputs.register","output_id":"output-a","width":1280,"height":720}),
            &host,
        )
        .unwrap();
        let mut doc = workspace();
        doc["outputs"]["output-a"]["tiles"] = json!({"kind":"split","axis":"horizontal","ratios":[0.5,0.5],"children":[{"kind":"leaf","surface_id":"missing-editor"},{"kind":"leaf","surface_id":"returning-editor"}]});
        handle(&mut db,&json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"place-returning","expected_revisions":{"workspace-a":null},"operations":[{"op":"workspace.put","document":doc}]}),&host).unwrap();
        assert!(handle(&mut db, &request, &host)
            .unwrap_err()
            .contains("placement"));
        let mut request = request;
        request["expected_workspaces"] = json!({"workspace-a":1});
        assert!(handle(&mut db, &request, &host).is_err());
        assert_eq!(
            crate::presentation_hosts::source(&db, "returning-editor")
                .unwrap()
                .unwrap()["availability"],
            "available"
        );
        request["expected_workspaces"] = json!({"workspace-a":0});
        let receipt = handle(&mut db, &request, &host).unwrap();
        assert_eq!(receipt["surface_id"], "missing-editor");
        assert_eq!(handle(&mut db, &request, &host).unwrap(), receipt);
        assert_eq!(
            handle(&mut db, &returning, &host).unwrap()["surface_id"],
            "missing-editor"
        );
        let placed = snapshot(&db).unwrap()["documents"]["workspace-a"].clone();
        assert_eq!(placed["revision"], 1);
        assert_eq!(
            placed["outputs"]["output-a"]["tiles"],
            json!({"kind":"leaf","surface_id":"missing-editor"})
        );
        assert_eq!(
            crate::presentation_hosts::source(&db, "missing-editor")
                .unwrap()
                .unwrap()["availability"],
            "available"
        );
        assert_eq!(
            crate::presentation_hosts::source(&db, "returning-editor")
                .unwrap()
                .unwrap()["availability"],
            "unavailable"
        );
        let mut collision = request;
        collision["missing_revision"] = json!(99);
        assert!(handle(&mut db, &collision, &host).is_err());
    }
    #[test]
    fn conventional_surface_registration_is_host_scoped_and_placeholders_are_durable() {
        let mut db = fixture();
        let root = Principal {
            uid: 0,
            session: "compositor-old-session".into(),
        };
        let registration = json!({"op":"host.surface","surface_id":"app-fixture","activity_id":"1","title":"Conventional editor","app_id":"org.example.Editor","connected":true});
        assert!(handle(&mut db, &registration, &agent())
            .unwrap_err()
            .contains("unauthorized"));
        handle(&mut db, &registration, &root).unwrap();
        let other = Principal {
            uid: 0,
            session: "different-compositor".into(),
        };
        assert!(handle(&mut db, &registration, &other).is_err());
        handle(
            &mut db,
            &json!({"op":"outputs.register","output_id":"output-a","width":1280,"height":720}),
            &root,
        )
        .unwrap();
        let mut document = workspace();
        document["outputs"]["output-a"]["tiles"]["surface_id"] = json!("app-fixture");
        document["focus"] = json!({"surface_id":"app-fixture","element_id":null});
        let mut apply = json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"conventional-workspace","expected_revisions":{"workspace-a":null},"operations":[{"op":"workspace.put","document":document}]});
        let mut foreign = apply.clone();
        foreign["operations"][0]["document"]["activity_id"] = json!("2");
        assert!(handle(&mut db, &foreign, &human()).is_err());
        let mut element = apply.clone();
        element["operations"][0]["document"]["focus"]["element_id"] = json!("invented-element");
        assert!(handle(&mut db, &element, &human()).is_err());
        handle(&mut db, &apply, &human()).unwrap();
        let snapshot = snapshot(&db).unwrap();
        assert_eq!(
            snapshot["host_surfaces"]["app-fixture"]["availability"],
            "unavailable"
        );
        assert_eq!(
            snapshot["documents"]["workspace-a"]["outputs"]["output-a"]["tiles"]["surface_id"],
            "app-fixture"
        );
        let mut disconnect = registration.clone();
        disconnect["connected"] = json!(false);
        handle(&mut db, &disconnect, &root).unwrap();
        apply["request_id"] = json!("keep-disconnected-placeholder");
        apply["expected_revisions"]["workspace-a"] = json!(0);
        handle(&mut db, &apply, &human()).unwrap();
        let mut reuse = surface();
        reuse["surface_id"] = json!("app-fixture");
        let recycle = json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"recycle-app-id","expected_revisions":{"app-fixture":null},"operations":[{"op":"surface.create","document":reuse}]});
        assert!(handle(&mut db, &recycle, &human()).is_err());
    }
    #[test]
    fn direct_workspace_edits_are_atomic_revisioned_and_undoable() {
        let mut db = fixture();
        create(&mut db);
        let mut second = surface();
        second["surface_id"] = json!("surface-b");
        handle(&mut db,&json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"create-b","expected_revisions":{"surface-b":null},"operations":[{"op":"surface.create","document":second}]}),&human()).unwrap();
        let root = Principal {
            uid: 0,
            session: "host".into(),
        };
        handle(
            &mut db,
            &json!({"op":"outputs.register","output_id":"output-a","width":1280,"height":720}),
            &root,
        )
        .unwrap();
        handle(&mut db,&json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"workspace-create","expected_revisions":{"workspace-a":null},"operations":[{"op":"workspace.put","document":workspace()}]}),&human()).unwrap();
        let request = |id: &str, revision: u64, edit: Value| json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":id,"expected_revisions":{"workspace-a":revision},"operations":[{"op":"workspace.edit","workspace_id":"workspace-a","edit":edit}]});
        handle(
            &mut db,
            &json!({"op":"interaction.begin","surface_id":"workspace-a"}),
            &human(),
        )
        .unwrap();
        let competing = Principal {
            uid: 1000,
            session: "other-input".into(),
        };
        assert!(handle(
            &mut db,
            &json!({"op":"interaction.begin","surface_id":"workspace-a"}),
            &competing
        )
        .unwrap_err()
        .contains("interaction_conflict"));
        assert!(handle(&mut db,&json!({"op":"draft.save","surface_id":"workspace-a","draft":"text","expected_draft_revision":0}),&human()).unwrap_err().contains("Workspace leases"));
        handle(
            &mut db,
            &json!({"op":"interaction.end","surface_id":"workspace-a"}),
            &human(),
        )
        .unwrap();
        let tile = request(
            "split",
            0,
            json!({"kind":"tile","surface_id":"surface-b","output_id":"output-a","target":"surface-a","axis":"horizontal","ratio":0.4}),
        );
        assert!(handle(&mut db, &tile, &agent())
            .unwrap_err()
            .contains("unauthorized"));
        let receipt = handle(&mut db, &tile, &human()).unwrap();
        assert_eq!(handle(&mut db, &tile, &human()).unwrap(), receipt);
        let committed = snapshot(&db).unwrap()["documents"]["workspace-a"].clone();
        assert_eq!(
            committed["outputs"]["output-a"]["tiles"]["ratios"],
            json!([0.6, 0.4])
        );
        let mut indirect = committed.clone();
        indirect["outputs"]["output-a"]["tiles"]["ratios"] = json!([0.5, 0.5]);
        let agent_resize = json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"indirect-resize","expected_revisions":{"workspace-a":1},"operations":[{"op":"workspace.put","document":indirect}]});
        assert!(handle(&mut db, &agent_resize, &agent())
            .unwrap_err()
            .contains("manually constrained geometry"));
        assert_eq!(
            snapshot(&db).unwrap()["documents"]["workspace-a"],
            committed
        );
        let tiny = request(
            "tiny",
            1,
            json!({"kind":"resize_split","surface_id":"surface-b","ratio":0.0001}),
        );
        assert!(handle(&mut db, &tiny, &human())
            .unwrap_err()
            .contains("constraint_conflict"));
        assert_eq!(
            snapshot(&db).unwrap()["documents"]["workspace-a"],
            committed
        );
        let float = request(
            "float",
            1,
            json!({"kind":"float","surface_id":"surface-b","output_id":"output-a","x":100,"y":80,"width":320,"height":240}),
        );
        let floated = handle(&mut db, &float, &human()).unwrap();
        assert_eq!(
            snapshot(&db).unwrap()["documents"]["workspace-a"]["outputs"]["output-a"]["tiles"]
                ["surface_id"],
            "surface-a"
        );
        handle(&mut db,&json!({"op":"presentation.undo","event_cursor":floated["event_cursor"],"request_id":"undo-float"}),&human()).unwrap();
        let restored = snapshot(&db).unwrap()["documents"]["workspace-a"].clone();
        assert_eq!(restored["outputs"], committed["outputs"]);
        assert_eq!(restored["constraints"], committed["constraints"]);
        assert!(handle(
            &mut db,
            &request(
                "stale",
                1,
                json!({"kind":"maximize","surface_id":"surface-b"})
            ),
            &human()
        )
        .is_err());
        handle(
            &mut db,
            &request(
                "max",
                3,
                json!({"kind":"maximize","surface_id":"surface-b"}),
            ),
            &human(),
        )
        .unwrap();
        handle(
            &mut db,
            &request(
                "restore",
                4,
                json!({"kind":"restore","surface_id":"surface-b"}),
            ),
            &human(),
        )
        .unwrap();
        assert_eq!(
            snapshot(&db).unwrap()["documents"]["workspace-a"]["outputs"],
            committed["outputs"]
        );
    }
    #[test]
    fn closing_a_placed_view_keeps_its_draft_and_undo_restores_it() {
        let mut db = fixture();
        create(&mut db);
        let root = Principal {
            uid: 0,
            session: "host".into(),
        };
        handle(
            &mut db,
            &json!({"op":"outputs.register","output_id":"output-a","width":1280,"height":720}),
            &root,
        )
        .unwrap();
        handle(&mut db,&json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"workspace-create","expected_revisions":{"workspace-a":null},"operations":[{"op":"workspace.put","document":workspace()}]}),&human()).unwrap();
        handle(
            &mut db,
            &json!({"op":"interaction.begin","surface_id":"surface-a","element_id":"input"}),
            &human(),
        )
        .unwrap();
        handle(&mut db,&json!({"op":"draft.save","surface_id":"surface-a","element_id":"input","expected_draft_revision":0,"draft":"Keep my unsaved λ text"}),&human()).unwrap();
        let closed=handle(&mut db,&json!({"op":"presentation.apply","protocol":PROTOCOL,"catalog_revision":CATALOG,"request_id":"close-placed","expected_revisions":{"workspace-a":0,"surface-a":0},"operations":[{"op":"workspace.edit","workspace_id":"workspace-a","edit":{"kind":"remove","surface_id":"surface-a"}},{"op":"surface.close","surface_id":"surface-a"}]}),&human()).unwrap();
        assert!(snapshot(&db).unwrap()["documents"]
            .get("surface-a")
            .is_none());
        handle(&mut db,&json!({"op":"presentation.undo","event_cursor":closed["event_cursor"],"request_id":"reopen-closed"}),&human()).unwrap();
        let restored = snapshot(&db).unwrap();
        assert_eq!(
            restored["documents"]["workspace-a"]["outputs"],
            workspace()["outputs"]
        );
        assert_eq!(restored["documents"]["surface-a"]["revision"], 2);
        assert_eq!(
            handle(
                &mut db,
                &json!({"op":"draft.get","surface_id":"surface-a","element_id":"input"}),
                &human()
            )
            .unwrap()["draft"],
            "Keep my unsaved λ text"
        );
    }
    #[test]
    fn renderer_restart_can_recover_a_dead_process_draft_without_waiting_for_timeout() {
        let mut db = fixture();
        create(&mut db);
        let old = Principal {
            uid: human().uid,
            session: "4294967295:0".into(),
        };
        handle(
            &mut db,
            &json!({"op":"interaction.begin","surface_id":"surface-a","element_id":"input"}),
            &old,
        )
        .unwrap();
        handle(&mut db,&json!({"op":"draft.save","surface_id":"surface-a","element_id":"input","expected_draft_revision":0,"draft":"Recover after crash"}),&old).unwrap();
        handle(
            &mut db,
            &json!({"op":"interaction.begin","surface_id":"surface-a","element_id":"input"}),
            &human(),
        )
        .unwrap();
        let recovered = handle(
            &mut db,
            &json!({"op":"draft.get","surface_id":"surface-a","element_id":"input"}),
            &human(),
        )
        .unwrap();
        assert_eq!(recovered["draft"], "Recover after crash");
        assert_eq!(recovered["draft_revision"], 1);
    }
}
