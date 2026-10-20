//! Ordered observations retain intermediate state without comparing GC timing.
use crate::{
    graph::Snapshot,
    observation::{self, CaptureGap, Comparison, ExpectedOutcome, Outcome},
    Verdict,
};
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;

pub const MAX_STEPS: usize = 32;

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Action {
    Call,
    Release,
    Collect,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Contract {
    pub id: String,
    pub action: Action,
    pub required_roots: Vec<String>,
    pub expected_baseline: ExpectedOutcome,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Observation {
    pub id: String,
    pub action: Action,
    pub gaps: Vec<CaptureGap>,
    pub before: Snapshot,
    pub outcome: Outcome,
    pub after: Snapshot,
}

fn contract(parent: &observation::Contract, step: &Contract) -> observation::Contract {
    observation::Contract {
        observation_schema_version: parent.observation_schema_version,
        case_id: step.id.clone(),
        function_id: parent.function_id.clone(),
        fixture_sha256: parent.fixture_sha256.clone(),
        required_roots: step.required_roots.clone(),
        expected_baseline: step.expected_baseline.clone(),
        steps: Vec::new(),
    }
}

fn observation(parent: &observation::Observation, step: &Observation) -> observation::Observation {
    observation::Observation {
        observation_schema_version: parent.observation_schema_version,
        case_id: step.id.clone(),
        function_id: parent.function_id.clone(),
        fixture_sha256: parent.fixture_sha256.clone(),
        fixture: parent.fixture.clone(),
        gaps: step.gaps.clone(),
        before: step.before.clone(),
        outcome: step.outcome.clone(),
        after: step.after.clone(),
        steps: Vec::new(),
    }
}

pub(crate) fn validate(parent: &observation::Contract) -> Result<(), String> {
    let mut identities = BTreeSet::new();
    if parent.steps.len() > MAX_STEPS {
        return Err("sequence exceeds the step limit".into());
    }
    for step in &parent.steps {
        if !identities.insert(&step.id)
            || (step.action != Action::Call
                && !matches!(step.expected_baseline, ExpectedOutcome::Return))
        {
            return Err("duplicate sequence step or invalid non-call outcome contract".into());
        }
        contract(parent, step).validate()?;
    }
    Ok(())
}

pub(crate) fn inspect(
    captured: &observation::Observation,
    expected: &observation::Contract,
    lane: &str,
) -> Result<Vec<String>, String> {
    if captured.steps.len() > MAX_STEPS {
        return Err("captured sequence exceeds the step limit".into());
    }
    let mut reasons = Vec::new();
    if captured.steps.len() != expected.steps.len() {
        reasons.push(format!(
            "{lane}: requested sequence steps are missing or extra"
        ));
    }
    let mut identities = BTreeSet::new();
    for (index, step) in captured.steps.iter().enumerate() {
        if !identities.insert(&step.id) {
            return Err("duplicate captured sequence step".into());
        }
        let fallback = Contract {
            id: step.id.clone(),
            action: step.action,
            required_roots: Vec::new(),
            expected_baseline: ExpectedOutcome::Return,
        };
        let selected = expected.steps.get(index).unwrap_or(&fallback);
        if selected.id != step.id || selected.action != step.action {
            reasons.push(format!(
                "{lane} step[{index}]: action identity or order differs"
            ));
        }
        reasons.extend(
            observation::inspect(
                &observation(captured, step),
                &contract(expected, selected),
                lane,
            )?
            .into_iter()
            .map(|reason| format!("step[{index}]: {reason}")),
        );
    }
    Ok(reasons)
}

pub(crate) fn compare(
    left: &observation::Observation,
    right: &observation::Observation,
    expected: &observation::Contract,
    result: &mut Comparison,
) -> Result<(), String> {
    for ((a, b), step) in left.steps.iter().zip(&right.steps).zip(&expected.steps) {
        if a.id != step.id || b.id != step.id || a.action != step.action || b.action != step.action
        {
            continue;
        }
        let compared = observation::compare_boundaries(
            &observation(left, a),
            &observation(right, b),
            &contract(expected, step),
            false,
        )?;
        if compared.verdict == Verdict::Blocked {
            result.verdict = Verdict::Blocked;
        }
        result.reasons.extend(
            compared
                .reasons
                .into_iter()
                .map(|reason| format!("step {}: {reason}", step.id)),
        );
        result
            .differences
            .extend(compared.differences.into_iter().map(|mut difference| {
                let id = step.id.replace('~', "~0").replace('/', "~1");
                difference.path = format!("/steps/{id}{}", difference.path);
                difference
            }));
    }
    Ok(())
}

pub(crate) fn stable(
    left: &observation::Observation,
    right: &observation::Observation,
) -> Result<bool, String> {
    if left.steps.len() != right.steps.len() {
        return Ok(false);
    }
    for (a, b) in left.steps.iter().zip(&right.steps) {
        if a.id != b.id
            || a.action != b.action
            || !observation::stable(&observation(left, a), &observation(right, b))?
        {
            return Ok(false);
        }
    }
    Ok(true)
}
