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
    #[serde(rename = "workspace.put")]
    Workspace { document: WorkspaceDocument },
}
impl Operation {
    fn id(&self) -> &str {
        match self {
            Self::Create { document } | Self::Replace { document } => &document.surface_id,
            Self::Workspace { document } => &document.workspace_id,
            Self::WorkspaceEdit { workspace_id, .. } => workspace_id,
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
                "/status" | "/error" => "string",
                _ => "integer",
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
                    _ => false,
                }
            };
            if !valid {
                return Err(invalid(format!("Invalid value for {key}")));
            }
        }
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
    for binding in s.bindings.values() {
        if binding.access != "read"
            || ![
                "/status",
                "/exit_code",
                "/error",
                "/created_at",
                "/finished_at",
            ]
            .contains(&binding.path.as_str())
        {
            return Err(invalid("Only registered read-only job fields are bindable"));
        }
        if binding.source.starts_with("broker:") {
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
    for d in docs.values() {
        if serde_json::to_vec(d).map_err(invalid)?.len() > DOCUMENT_LIMIT {
            return Err(error("resource_limit", "Document exceeds 1 MiB"));
        }
        let active:bool=db.query_row("SELECT EXISTS(SELECT 1 FROM activities WHERE CAST(id AS TEXT)=? AND id NOT IN (SELECT activity_id FROM removed_activities))",[d.activity()],|r|r.get(0)).map_err(db_error)?;
        if !active {
            continue;
        }
        match d {
            Document::Surface(s) => surface_valid(db, s, principal)?,
            Document::Workspace(w) => {
                if w.protocol != PROTOCOL || !ident(&w.workspace_id) {
                    return Err(invalid("Workspace protocol/identity mismatch"));
                }
                let mut local = BTreeSet::new();
                let mut locations = BTreeMap::new();
                for (output, layout) in &w.outputs {
                    let size:Option<(f64,f64)>=db.query_row("SELECT width,height FROM presentation_outputs WHERE id=? AND connected=1",[output],|r|Ok((r.get(0)?,r.get(1)?))).optional().map_err(db_error)?;
                    let (width, height) = size.ok_or_else(|| {
                        error("missing_reference", format!("Output {output} unavailable"))
                    })?;
                    let before = local.clone();
                    if let Some(t) = &layout.tiles {
                        tile_valid(t, &mut local, 1, width, height)?
                    }
                    for f in &layout.floating {
                        if ![f.x, f.y, f.width, f.height].iter().all(|v| v.is_finite())
                            || f.width < 80.0
                            || f.height < 32.0
                            || f.x < 0.0
                            || f.y < 0.0
                            || f.x + f.width > width
                            || f.y + f.height > height
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
    crate::presentation_sources::init(db)?;
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
    Ok(
        json!({"protocol":PROTOCOL,"catalog_revision":CATALOG,"documents":docs,"host_surfaces":crate::presentation_hosts::snapshot(db,&referenced)?,"renderers":crate::presentation_hosts::renderers(db)?,"event_cursor":cursor}),
    )
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
                        if element.kind != "TextField@1" {
                            return Err(invalid("Only editable text fields can commit a draft"));
                        }
                        element.props.insert("value".into(), json!(draft));
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
pub fn handle(db: &mut Connection, v: &Value, who: &Principal) -> Result<Value> {
    match v["op"].as_str().unwrap_or("") {
        "catalog.get" => Ok(catalog()),
        "source.publish" | "source.heartbeat" | "source.list" => {
            crate::presentation_sources::handle(db, v, who)
        }
        "host.renderer" => crate::presentation_hosts::renderer(db, v, who),
        "host.surface" => crate::presentation_hosts::register(db, v, who),
        "action.issue" | "action.revoke" | "action.metadata" | "action.status" => {
            crate::presentation_actions::handle(db, v, who)
        }
        "presentation.snapshot" => snapshot(db),
        "presentation.apply" => apply(db, v, who),
        "presentation.subscribe" => {
            let cursor = v["after_cursor"].as_i64().unwrap_or(0);
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
            let mut q=db.prepare("SELECT cursor,after_state,receipt FROM presentation_events WHERE cursor>? ORDER BY cursor LIMIT 32").map_err(db_error)?;
            let events=q.query_map([cursor],|r|Ok((r.get::<_,i64>(0)?,r.get::<_,String>(1)?,r.get::<_,String>(2)?))).map_err(db_error)?
                .map(|r|{let(c,d,receipt)=r.map_err(db_error)?;Ok(json!({"event_cursor":c,"documents":serde_json::from_str::<Value>(&d).map_err(db_error)?,"receipt":serde_json::from_str::<Value>(&receipt).map_err(db_error)?}))}).collect::<Result<Vec<_>>>()?;
            Ok(json!({"protocol":PROTOCOL,"events":events,"latest_cursor":latest}))
        }
        "outputs.register" => {
            if !crate::presentation_hosts::trusted(who) {
                return Err(error(
                    "unauthorized",
                    "Only the trusted compositor can advertise outputs",
                ));
            }
            let id = v["output_id"]
                .as_str()
                .filter(|x| ident(x))
                .ok_or_else(|| invalid("Invalid output ID"))?;
            let width = v["width"]
                .as_f64()
                .filter(|x| x.is_finite() && (80.0..=32768.0).contains(x))
                .ok_or_else(|| invalid("Invalid output width"))?;
            let height = v["height"]
                .as_f64()
                .filter(|x| x.is_finite() && (32.0..=32768.0).contains(x))
                .ok_or_else(|| invalid("Invalid output height"))?;
            // Refuse a size change that would silently invalidate the committed placement.
            let tx = db.transaction().map_err(db_error)?;
            tx.execute("INSERT INTO presentation_outputs VALUES(?,?,?,1) ON CONFLICT(id) DO UPDATE SET width=excluded.width,height=excluded.height,connected=1",params![id,width,height]).map_err(db_error)?;
            validate(&tx, &documents(&tx)?, who)?;
            tx.commit().map_err(db_error)?;
            Ok(json!({"output_id":id,"width":width,"height":height}))
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
    let docs = documents(db)?;
    let document = docs.get(id).ok_or_else(|| error("missing_reference", id))?;
    if !element.is_empty() {
        match document {
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
    let docs = documents(db)?;
    let id = v["surface_id"]
        .as_str()
        .ok_or_else(|| invalid("Missing surface ID"))?;
    let s = match docs.get(id) {
        Some(Document::Surface(s)) => s,
        _ => return Err(error("missing_reference", id)),
    };
    let mut values = BTreeMap::new();
    let rev: i64 = db
        .query_row("SELECT value FROM meta WHERE key='revision'", [], |r| {
            r.get(0)
        })
        .map_err(db_error)?;
    for (key, b) in &s.bindings {
        if b.source.starts_with("broker:") {
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
        assert!(handle(&mut db, &publication, &root)
            .unwrap_err()
            .contains("stale_revision"));
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
