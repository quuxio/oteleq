//! Versioned typed worker evidence and independently declared fixture contracts.
//! A successful baseline return is the default validity check. Expected errors
//! require an explicit category/type contract; equal invalid fixtures never pass.
use crate::{
    graph::{self, Difference, Gap, Snapshot, Value},
    Verdict,
};
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ErrorCategory {
    Exception,
    Panic,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum ExpectedOutcome {
    Return,
    Error {
        category: ErrorCategory,
        r#type: String,
    },
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Contract {
    pub observation_schema_version: u32,
    pub case_id: String,
    pub function_id: String,
    pub fixture_sha256: String,
    pub required_roots: Vec<String>,
    pub expected_baseline: ExpectedOutcome,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum Fixture {
    Ready,
    Invalid { reason: String },
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Outcome {
    Return {
        graph: Snapshot,
    },
    Error {
        category: ErrorCategory,
        graph: Snapshot,
    },
    NotRun {
        reason: String,
    },
}
impl Outcome {
    fn graph(&self) -> Option<&Snapshot> {
        match self {
            Self::Return { graph } | Self::Error { graph, .. } => Some(graph),
            Self::NotRun { .. } => None,
        }
    }
    fn root(&self) -> Option<&'static str> {
        match self {
            Self::Return { .. } => Some("result"),
            Self::Error { .. } => Some("error"),
            Self::NotRun { .. } => None,
        }
    }
    fn label(&self) -> String {
        match self {
            Self::Return { .. } => "return".into(),
            Self::Error { category, .. } => format!("error:{category:?}"),
            Self::NotRun { .. } => "not_run".into(),
        }
    }
}
#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Phase {
    Before,
    Outcome,
    After,
}
impl Phase {
    fn label(self) -> &'static str {
        match self {
            Self::Before => "before",
            Self::Outcome => "outcome",
            Self::After => "after",
        }
    }
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CaptureGap {
    pub phase: Phase,
    pub path: String,
    pub reason: String,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Observation {
    pub observation_schema_version: u32,
    pub case_id: String,
    pub function_id: String,
    pub fixture_sha256: String,
    pub fixture: Fixture,
    /// Missing requested dimensions only. Unrequested scope exclusions belong
    /// in the outer report; they must not silently replace required roots.
    pub gaps: Vec<CaptureGap>,
    pub before: Snapshot,
    pub outcome: Outcome,
    pub after: Snapshot,
}
#[derive(Debug, Serialize)]
pub struct Comparison {
    pub verdict: Verdict,
    pub reasons: Vec<String>,
    pub initial_differences: Vec<Difference>,
    pub differences: Vec<Difference>,
}
fn identifier(value: &str) -> bool {
    !value.is_empty() && value.len() <= 1024
}
fn sha(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit())
}
impl Contract {
    pub fn validate(&self) -> Result<(), String> {
        let roots: BTreeSet<_> = self.required_roots.iter().collect();
        if self.observation_schema_version != 1
            || !identifier(&self.case_id)
            || !identifier(&self.function_id)
            || !sha(&self.fixture_sha256)
            || roots.len() != self.required_roots.len()
            || roots.len() > 8192
            || roots
                .iter()
                .any(|root| !identifier(root) || ["result", "error"].contains(&root.as_str()))
        {
            return Err("invalid observation contract version, identity or root set".into());
        }
        if let ExpectedOutcome::Error { r#type, .. } = &self.expected_baseline {
            if !identifier(r#type) {
                return Err("expected error requires a qualified payload type".into());
            }
        }
        Ok(())
    }
}
fn roots(
    snapshot: &Snapshot,
    required: &[String],
    result: Option<&str>,
    lane: &str,
    phase: &str,
) -> Option<String> {
    let mut expected: BTreeSet<_> = required.iter().map(String::as_str).collect();
    expected.extend(result);
    let actual: BTreeSet<_> = snapshot.roots.keys().map(String::as_str).collect();
    (expected != actual)
        .then(|| format!("{lane} {phase}: requested roots {expected:?}, captured {actual:?}"))
}
fn inspect(
    observation: &Observation,
    contract: &Contract,
    lane: &str,
) -> Result<Vec<String>, String> {
    if observation.observation_schema_version != 1
        || !identifier(&observation.case_id)
        || !identifier(&observation.function_id)
        || !sha(&observation.fixture_sha256)
        || observation.gaps.len() > 128
        || observation.gaps.iter().any(|gap| {
            !identifier(&gap.path) || !gap.path.starts_with('/') || !identifier(&gap.reason)
        })
    {
        return Err("invalid observation metadata, version or gaps".into());
    }
    match (&observation.fixture, &observation.outcome) {
        (Fixture::Invalid { reason }, Outcome::NotRun { reason: skipped })
            if identifier(reason) && identifier(skipped) => {}
        (Fixture::Ready, Outcome::Return { .. } | Outcome::Error { .. }) => {}
        _ => return Err("fixture status and captured outcome are inconsistent".into()),
    }
    let mut gaps: Vec<String> = observation
        .gaps
        .iter()
        .map(|gap| format!("{lane} {} {}: {}", gap.phase.label(), gap.path, gap.reason))
        .collect();
    let mut stages = vec![
        ("before", &observation.before, None),
        ("after", &observation.after, None),
    ];
    if let Some(graph) = observation.outcome.graph() {
        stages.push(("outcome", graph, observation.outcome.root()));
    }
    for (phase, graph, result) in stages {
        gaps.extend(
            graph::inspect(graph, lane)?
                .into_iter()
                .map(|gap| format!("{phase}: {}", gap.description())),
        );
        gaps.extend(roots(graph, &contract.required_roots, result, lane, phase));
    }
    Ok(gaps)
}
fn value_type<'a>(value: &'a Value, graph: &'a Snapshot) -> Option<&'a str> {
    match value {
        Value::Reference { node_id } => graph
            .nodes
            .iter()
            .find(|node| node.id == *node_id)
            .map(|node| node.r#type.as_str()),
        Value::Unit { r#type }
        | Value::Integer { r#type, .. }
        | Value::Float { r#type, .. }
        | Value::String { r#type, .. }
        | Value::Bytes { r#type, .. }
        | Value::Opaque { r#type, .. } => Some(r#type),
        Value::Null => Some("null"),
        Value::Undefined => Some("undefined"),
        Value::Unbound => Some("unbound"),
        Value::Boolean { .. } => Some("boolean"),
    }
}
fn baseline_valid(observation: &Observation, contract: &Contract) -> Option<bool> {
    match (&observation.outcome, &contract.expected_baseline) {
        (Outcome::Return { .. }, ExpectedOutcome::Return) => Some(true),
        (
            Outcome::Error { category, graph },
            ExpectedOutcome::Error {
                category: expected,
                r#type,
            },
        ) => {
            if category != expected {
                return Some(false);
            }
            graph
                .roots
                .get("error")
                .and_then(|value| value_type(value, graph))
                .map(|actual| actual == r#type)
        }
        (Outcome::NotRun { .. }, _) => None,
        _ => Some(false),
    }
}
fn prefix(differences: &mut [Difference], phase: &str) {
    for difference in differences {
        difference.path = format!("/{phase}{}", difference.path);
    }
}
fn changed(
    left: &Snapshot,
    right: &Snapshot,
    phase: &str,
    result: &mut Comparison,
    initial: bool,
) -> Result<(), String> {
    let mut graph = graph::compare(left, right)?;
    prefix(&mut graph.differences, phase);
    // Opaque gaps were retained during independent inspection, even when
    // outcome kinds or node types differ. Only new comparison limits remain.
    result.reasons.extend(
        graph
            .gaps
            .into_iter()
            .filter(|gap| matches!(gap, Gap::Limit { .. }))
            .map(|gap| gap.description()),
    );
    if initial {
        result.initial_differences.extend(graph.differences);
    } else {
        result.differences.extend(graph.differences);
    }
    Ok(())
}
/// Compare typed evidence after checking identity and fixture validity. An
/// instrumented exception with a valid returning baseline is a difference;
/// matching unexpected baseline errors are invalid fixture evidence.
pub fn compare(
    left: &Observation,
    right: &Observation,
    contract: &Contract,
) -> Result<Comparison, String> {
    contract.validate()?;
    let mut reasons = inspect(left, contract, "baseline")?;
    reasons.extend(inspect(right, contract, "instrumented_on")?);
    let mut result = Comparison {
        verdict: Verdict::EquivalentObserved,
        reasons,
        initial_differences: Vec::new(),
        differences: Vec::new(),
    };
    for (lane, observation) in [("baseline", left), ("instrumented_on", right)] {
        if observation.case_id != contract.case_id
            || observation.function_id != contract.function_id
            || observation.fixture_sha256 != contract.fixture_sha256
        {
            result.reasons.push(format!(
                "{lane}: case/function/fixture identity differs from the contract"
            ));
            result.verdict = Verdict::Blocked;
        }
        if let Fixture::Invalid { reason } = &observation.fixture {
            result
                .reasons
                .push(format!("{lane}: invalid fixture: {reason}"));
            result.verdict = Verdict::Blocked;
        }
    }
    if baseline_valid(left, contract) == Some(false) {
        result.reasons.push("baseline outcome violates its declared contract; provide valid inputs or an explicit expected-error fixture".into());
        result.verdict = Verdict::Blocked;
    }
    changed(&left.before, &right.before, "before", &mut result, true)?;
    let known_initial = [&left.before, &right.before].iter().all(|snapshot| {
        roots(
            snapshot,
            &contract.required_roots,
            None,
            "fixture",
            "before",
        )
        .is_none()
    }) && left
        .gaps
        .iter()
        .chain(&right.gaps)
        .all(|gap| gap.phase != Phase::Before)
        && graph::inspect(&left.before, "baseline")?.is_empty()
        && graph::inspect(&right.before, "instrumented_on")?.is_empty();
    if known_initial && !result.initial_differences.is_empty() {
        result.reasons.push(
            "initial fixtures differ; function equivalence cannot be assessed from this pair"
                .into(),
        );
        result.verdict = Verdict::Blocked;
    }
    if result.verdict == Verdict::Blocked {
        return Ok(result);
    }
    changed(&left.after, &right.after, "after", &mut result, false)?;
    if let (Some(a), Some(b)) = (left.outcome.graph(), right.outcome.graph()) {
        changed(a, b, "outcome", &mut result, false)?;
    }
    if left.outcome.label() != right.outcome.label() {
        result.differences.push(Difference {
            path: "/outcome".into(),
            reason: format!(
                "outcome differs: {} vs {}",
                left.outcome.label(),
                right.outcome.label()
            ),
            baseline: None,
            instrumented_on: None,
        });
    }
    result.verdict = if !result.reasons.is_empty() {
        Verdict::Inconclusive
    } else if !result.differences.is_empty() {
        Verdict::DifferentObserved
    } else {
        Verdict::EquivalentObserved
    };
    Ok(result)
}

/// Compare independent repeats without interpreting either repeat as a valid
/// baseline. A stable instrumentation-induced exception remains a difference
/// between lanes, not an invalid fixture in the instrumented lane.
pub(crate) fn stable(left: &Observation, right: &Observation) -> Result<bool, String> {
    let before = graph::compare(&left.before, &right.before)?.equivalent();
    let after = graph::compare(&left.after, &right.after)?.equivalent();
    let outcome = match (left.outcome.graph(), right.outcome.graph()) {
        (Some(a), Some(b)) => graph::compare(a, b)?.equivalent(),
        (None, None) => true,
        _ => false,
    };
    Ok(before && after && outcome && left.outcome.label() == right.outcome.label())
}
