//! Bounded, typed boundary snapshots. Node IDs are local capture labels, never
//! compared as addresses. Identity across different boundaries needs a separate
//! producer contract; this module does not infer it from matching local IDs.
use crate::protocol::unique_map;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

const MAX_NODES: usize = 512;
const MAX_DEPTH: usize = 32;
const MAX_FIELDS: usize = 8192;
const MAX_TEXT: usize = 262144;
const MAX_DIFFERENCES: usize = 128;
const MAX_GAPS: usize = 128;

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Value {
    Null,
    Undefined,
    Unbound,
    Unit {
        r#type: String,
    },
    Boolean {
        #[serde(default, skip_serializing_if = "Option::is_none")]
        r#type: Option<String>,
        value: bool,
    },
    Integer {
        r#type: String,
        value: String,
        bits: Option<u16>,
        signed: bool,
    },
    Float {
        r#type: String,
        bits: String,
    },
    String {
        r#type: String,
        encoding: Encoding,
        value: String,
    },
    Bytes {
        r#type: String,
        hex: String,
    },
    Reference {
        node_id: String,
    },
    Opaque {
        r#type: String,
        reason: String,
    },
}
#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Encoding {
    Utf8,
    Utf16Be,
    Codepoints32Be,
    RawBytes,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Node {
    pub id: String,
    pub r#type: String,
    // Qualified codecs give ordered containers explicit indexed fields. Keys
    // and values remain typed values; no stringification of map keys is valid.
    #[serde(deserialize_with = "unique_map")]
    pub fields: BTreeMap<String, Value>,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Snapshot {
    #[serde(deserialize_with = "unique_map")]
    pub roots: BTreeMap<String, Value>,
    pub nodes: Vec<Node>,
}
#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Difference {
    pub path: String,
    pub reason: String,
    pub baseline: Option<Value>,
    pub instrumented_on: Option<Value>,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Gap {
    Opaque {
        lane: String,
        path: String,
        r#type: String,
        reason: String,
    },
    Limit {
        path: String,
        limit: ComparisonLimit,
    },
}
#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ComparisonLimit {
    Differences,
    Depth,
    Diagnostics,
}
impl Gap {
    pub fn description(&self) -> String {
        match self {
            Self::Opaque {
                lane,
                path,
                r#type,
                reason,
            } => format!("{lane} {path}: opaque {type}: {reason}"),
            Self::Limit { path, limit } => format!("{path}: graph comparison limit {limit:?}"),
        }
    }
}
#[derive(Debug, Serialize)]
pub struct Comparison {
    pub differences: Vec<Difference>,
    pub gaps: Vec<Gap>,
}
impl Comparison {
    pub fn equivalent(&self) -> bool {
        self.differences.is_empty() && self.gaps.is_empty()
    }
}
fn name(value: &str) -> bool {
    !value.is_empty() && value.len() <= 1024
}
fn hex(value: &str) -> bool {
    value.len() <= MAX_TEXT * 2
        && value.len().is_multiple_of(2)
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}
fn decimal(value: &str) -> bool {
    let digits = value.strip_prefix('-').unwrap_or(value);
    !digits.is_empty()
        && digits.len() <= MAX_TEXT
        && digits.bytes().all(|byte| byte.is_ascii_digit())
        && (digits == "0" && value == "0" || !digits.starts_with('0'))
}
fn integer(value: &str, bits: Option<u16>, signed: bool) -> bool {
    if !decimal(value) || !signed && value.starts_with('-') {
        return false;
    }
    let Some(bits) = bits else {
        return true;
    };
    if ![8, 16, 32, 64, 128].contains(&bits) {
        return false;
    }
    if signed {
        value.parse::<i128>().is_ok_and(|number| {
            bits == 128 || (-(1_i128 << (bits - 1))..(1_i128 << (bits - 1))).contains(&number)
        })
    } else {
        value
            .parse::<u128>()
            .is_ok_and(|number| bits == 128 || number < (1_u128 << bits))
    }
}
fn string(encoding: &Encoding, value: &str) -> bool {
    if !hex(value) {
        return false;
    }
    match encoding {
        Encoding::RawBytes => true,
        Encoding::Utf16Be => value.len().is_multiple_of(4),
        Encoding::Codepoints32Be => {
            value.len().is_multiple_of(8)
                && value.as_bytes().as_chunks::<8>().0.iter().all(|unit| {
                    std::str::from_utf8(unit)
                        .ok()
                        .and_then(|text| u32::from_str_radix(text, 16).ok())
                        .is_some_and(|point| point <= 0x10ffff)
                })
        }
        Encoding::Utf8 => {
            let bytes: Vec<u8> = value
                .as_bytes()
                .as_chunks::<2>()
                .0
                .iter()
                .map(|pair| {
                    // The preceding ASCII-hex check guarantees both digits.
                    let digit = |byte: u8| {
                        if byte <= b'9' {
                            byte - b'0'
                        } else {
                            byte - b'a' + 10
                        }
                    };
                    digit(pair[0]) * 16 + digit(pair[1])
                })
                .collect();
            std::str::from_utf8(&bytes).is_ok()
        }
    }
}
fn valid_value(value: &Value, nodes: &BTreeMap<&str, &Node>) -> bool {
    match value {
        Value::Unit { r#type } => name(r#type),
        Value::Boolean { r#type, .. } => r#type.as_deref().is_none_or(name),
        Value::Integer {
            r#type,
            value,
            bits,
            signed,
        } => name(r#type) && integer(value, *bits, *signed),
        Value::Float { r#type, bits } => {
            name(r#type) && [4, 8, 16, 32].contains(&bits.len()) && hex(bits)
        }
        Value::String {
            r#type,
            encoding,
            value,
        } => name(r#type) && string(encoding, value),
        Value::Bytes { r#type, hex: value } => name(r#type) && hex(value),
        Value::Reference { node_id } => name(node_id) && nodes.contains_key(node_id.as_str()),
        Value::Opaque { r#type, reason } => {
            name(r#type) && !reason.is_empty() && reason.len() <= MAX_TEXT
        }
        _ => true,
    }
}
fn value_size(value: &Value) -> usize {
    match value {
        Value::Unit { r#type } => r#type.len(),
        Value::Boolean { r#type, .. } => 1 + r#type.as_ref().map_or(0, String::len),
        Value::Integer { r#type, value, .. } | Value::String { r#type, value, .. } => {
            r#type.len() + value.len()
        }
        Value::Float { r#type, bits } => r#type.len() + bits.len(),
        Value::Bytes { r#type, hex } => r#type.len() + hex.len(),
        Value::Reference { node_id } => node_id.len(),
        Value::Opaque { r#type, reason } => r#type.len() + reason.len(),
        _ => 1,
    }
}
fn opaque_gaps(snapshot: &Snapshot, lane: &str) -> Vec<Gap> {
    let nodes: BTreeMap<_, _> = snapshot
        .nodes
        .iter()
        .map(|node| (node.id.as_str(), node))
        .collect();
    let mut gaps = Vec::new();
    let mut payload = 0;
    let mut visited = BTreeSet::new();
    // Retain iterators rather than a copied long path for every pending child.
    let mut stack = vec![(String::new(), snapshot.roots.iter())];
    while let Some((parent, fields)) = stack.last_mut() {
        let Some((name, value)) = fields.next() else {
            stack.pop();
            continue;
        };
        let location = path(parent, name);
        match value {
            Value::Opaque { r#type, reason } => {
                payload += lane.len() + location.len() + r#type.len() + reason.len() + 32;
                if gaps.len() == MAX_GAPS || payload > MAX_TEXT {
                    gaps.push(Gap::Limit {
                        path: "/".into(),
                        limit: ComparisonLimit::Diagnostics,
                    });
                    break;
                }
                gaps.push(Gap::Opaque {
                    lane: lane.into(),
                    path: location,
                    r#type: r#type.clone(),
                    reason: reason.clone(),
                });
            }
            Value::Reference { node_id } if visited.insert(node_id.as_str()) => {
                stack.push((location, nodes[node_id.as_str()].fields.iter()));
            }
            _ => {}
        }
    }
    gaps
}
pub(crate) fn inspect(snapshot: &Snapshot, lane: &str) -> Result<Vec<Gap>, String> {
    validate(snapshot)?;
    Ok(opaque_gaps(snapshot, lane))
}
fn validate(snapshot: &Snapshot) -> Result<BTreeMap<&str, &Node>, String> {
    if snapshot.nodes.len() > MAX_NODES || snapshot.roots.len() > MAX_FIELDS {
        return Err("graph node/root limit exceeded".into());
    }
    let mut nodes = BTreeMap::new();
    let mut fields = snapshot.roots.len();
    for node in &snapshot.nodes {
        fields += node.fields.len();
        if !name(&node.id)
            || !name(&node.r#type)
            || fields > MAX_FIELDS
            || nodes.insert(node.id.as_str(), node).is_some()
        {
            return Err("invalid/duplicate graph node or field limit exceeded".into());
        }
    }
    let mut payload = nodes
        .values()
        .map(|node| node.id.len() + node.r#type.len())
        .sum::<usize>();
    for (index, values) in std::iter::once(&snapshot.roots)
        .chain(snapshot.nodes.iter().map(|node| &node.fields))
        .enumerate()
    {
        for (key, value) in values {
            if key.len() > 1024 || index == 0 && key.is_empty() || !valid_value(value, &nodes) {
                return Err("invalid typed graph field, scalar or reference".into());
            }
            payload += key.len() + value_size(value);
            if payload > MAX_TEXT {
                return Err("graph payload limit exceeded".into());
            }
        }
    }
    let mut visited = BTreeSet::new();
    let mut stack: Vec<(&Value, usize)> = snapshot
        .roots
        .values()
        .rev()
        .map(|value| (value, 0))
        .collect();
    while let Some((value, depth)) = stack.pop() {
        if let Value::Reference { node_id } = value {
            if visited.insert(node_id.as_str()) {
                if depth > MAX_DEPTH {
                    return Err("graph depth limit exceeded".into());
                }
                stack.extend(
                    nodes[node_id.as_str()]
                        .fields
                        .values()
                        .rev()
                        .map(|value| (value, depth + 1)),
                );
            }
        }
    }
    if visited.len() != nodes.len() {
        return Err("unreachable graph nodes are not a complete snapshot".into());
    }
    Ok(nodes)
}
fn path(parent: &str, key: &str) -> String {
    format!("{parent}/{}", key.replace('~', "~0").replace('/', "~1"))
}
struct Matcher<'a> {
    left: BTreeMap<&'a str, &'a Node>,
    right: BTreeMap<&'a str, &'a Node>,
    forward: BTreeMap<&'a str, &'a str>,
    reverse: BTreeMap<&'a str, &'a str>,
    result: Comparison,
    diagnostic_bytes: usize,
}
impl<'a> Matcher<'a> {
    fn limit(&mut self, limit: ComparisonLimit) {
        if !self
            .result
            .gaps
            .iter()
            .any(|gap| matches!(gap, Gap::Limit { limit: existing, .. } if *existing == limit))
        {
            self.result.gaps.push(Gap::Limit {
                path: "/".into(),
                limit,
            });
        }
    }
    fn difference(
        &mut self,
        path: &str,
        reason: &str,
        left: Option<&Value>,
        right: Option<&Value>,
    ) {
        if self.result.differences.len() == MAX_DIFFERENCES {
            self.limit(ComparisonLimit::Differences);
            return;
        }
        let payload =
            path.len() + reason.len() + left.map_or(0, value_size) + right.map_or(0, value_size);
        if self.diagnostic_bytes + payload > MAX_TEXT {
            self.limit(ComparisonLimit::Diagnostics);
            return;
        }
        self.diagnostic_bytes += payload;
        self.result.differences.push(Difference {
            path: path.into(),
            reason: reason.into(),
            baseline: left.cloned(),
            instrumented_on: right.cloned(),
        });
    }
    fn fields(
        &mut self,
        left: &'a BTreeMap<String, Value>,
        right: &'a BTreeMap<String, Value>,
        parent: &str,
        depth: usize,
    ) {
        for key in left.keys().chain(right.keys()).collect::<BTreeSet<_>>() {
            let location = path(parent, key);
            match (left.get(key), right.get(key)) {
                (Some(left), Some(right)) => self.value(left, right, &location, depth),
                (left, right) => self.difference(&location, "field/root missing", left, right),
            }
        }
    }
    fn value(&mut self, left: &'a Value, right: &'a Value, location: &str, depth: usize) {
        if matches!(left, Value::Opaque { .. }) || matches!(right, Value::Opaque { .. }) {
            return; // All opaque fields were recorded before traversal, including missing/type-different branches.
        }
        if let (Value::Reference { node_id: a }, Value::Reference { node_id: b }) = (left, right) {
            if let Some(existing) = self.forward.get(a.as_str()) {
                if *existing != b {
                    self.difference(location, "reference alias differs", Some(left), Some(right));
                }
                return;
            }
            if self.reverse.contains_key(b.as_str()) {
                self.difference(
                    location,
                    "distinct references merged",
                    Some(left),
                    Some(right),
                );
                return;
            }
            if depth > MAX_DEPTH {
                self.limit(ComparisonLimit::Depth);
                return;
            }
            self.forward.insert(a, b);
            self.reverse.insert(b, a);
            let (a, b) = (self.left[a.as_str()], self.right[b.as_str()]);
            if a.r#type != b.r#type {
                self.difference(
                    location,
                    &format!(
                        "node type differs: baseline {:?}, instrumented_on {:?}",
                        a.r#type, b.r#type
                    ),
                    Some(left),
                    Some(right),
                );
                return;
            }
            self.fields(&a.fields, &b.fields, location, depth + 1);
        } else if left != right {
            self.difference(location, "typed value differs", Some(left), Some(right));
        }
    }
}
/// Match a complete boundary graph with a bijection between reachable node IDs.
/// Ordered container codecs must retain positions as labelled fields. Unknown
/// fields, opaque state and unsupported codecs cannot establish equivalence.
pub fn compare(left: &Snapshot, right: &Snapshot) -> Result<Comparison, String> {
    let (left_nodes, right_nodes) = (validate(left)?, validate(right)?);
    let gaps = opaque_gaps(left, "baseline")
        .into_iter()
        .chain(opaque_gaps(right, "instrumented_on"))
        .collect();
    let mut matcher = Matcher {
        left: left_nodes,
        right: right_nodes,
        forward: BTreeMap::new(),
        reverse: BTreeMap::new(),
        result: Comparison {
            differences: Vec::new(),
            gaps,
        },
        diagnostic_bytes: 0,
    };
    matcher.fields(&left.roots, &right.roots, "", 0);
    Ok(matcher.result)
}
