//! Repeated typed observations retain the workload comparator's exact byte,
//! source-preservation and decoded-witness checks. Producers remain responsible
//! for authentic capture and binding the selected function to its witness.
use crate::{
    compare::{self, CaseReport, Verdict},
    observation::{self, Contract, Observation},
    protocol::{self, Attempt, Scope},
};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct TypedAttempt {
    pub execution: Attempt,
    pub observation: Observation,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Case {
    pub contract: Contract,
    pub corpus_sha256: String,
    #[serde(deserialize_with = "protocol::unique_map")]
    pub expected_functions: BTreeMap<String, u64>,
    pub expected_spans: u64,
    pub baseline: Vec<TypedAttempt>,
    pub instrumented_on: Vec<TypedAttempt>,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Bundle {
    pub typed_schema_version: u32,
    pub scope: Scope,
    pub cases: Vec<Case>,
}
#[derive(Debug, Serialize)]
pub struct PairReport {
    pub baseline_attempt: usize,
    pub instrumented_attempt: usize,
    pub comparison: observation::Comparison,
}
#[derive(Debug, Serialize)]
pub struct TypedCaseReport {
    pub case_id: String,
    pub verdict: Verdict,
    pub execution: CaseReport,
    pub reasons: Vec<String>,
    pub pairs: Vec<PairReport>,
}
#[derive(Debug, Serialize)]
pub struct Report {
    pub typed_schema_version: u32,
    pub claim: &'static str,
    pub comparison: &'static str,
    pub verdict: Verdict,
    pub scope: Scope,
    pub cases: Vec<TypedCaseReport>,
}
fn verdict(values: impl IntoIterator<Item = Verdict>) -> Verdict {
    let values: Vec<_> = values.into_iter().collect();
    [
        Verdict::Blocked,
        Verdict::Inconclusive,
        Verdict::DifferentObserved,
    ]
    .into_iter()
    .find(|value| values.contains(value))
    .unwrap_or(Verdict::EquivalentObserved)
}
fn workload_case(case: &Case) -> protocol::Case {
    protocol::Case {
        case_id: case.contract.case_id.clone(),
        corpus_sha256: case.corpus_sha256.clone(),
        expected_functions: case.expected_functions.clone(),
        expected_spans: case.expected_spans,
        baseline: case.baseline.iter().map(|a| a.execution.clone()).collect(),
        instrumented_on: case
            .instrumented_on
            .iter()
            .map(|a| a.execution.clone())
            .collect(),
    }
}
fn compare_case(case: &Case, execution: CaseReport) -> Result<TypedCaseReport, String> {
    case.contract.validate()?;
    if case
        .expected_functions
        .get(&case.contract.function_id)
        .copied()
        .unwrap_or(0)
        == 0
    {
        return Err("typed function identity is absent from the witness expectation".into());
    }
    let mut reasons = Vec::new();
    let mut pairs = Vec::new();
    // Every attempt is inspected, including when the other lane has no first
    // attempt. Self-comparison validates identity and fixture evidence without
    // substituting for the independent repeat or cross-lane requirements.
    let mut validity = Vec::new();
    for (lane, attempts) in [
        ("baseline", &case.baseline),
        ("instrumented_on", &case.instrumented_on),
    ] {
        for (index, attempt) in attempts.iter().enumerate() {
            let checked =
                observation::compare(&attempt.observation, &attempt.observation, &case.contract)?;
            // The instrumented lane may consistently introduce an exception.
            // Validate its capture/identity against the real baseline below.
            if lane == "baseline" || case.baseline.is_empty() {
                validity.push(checked.verdict);
                reasons.extend(
                    checked
                        .reasons
                        .into_iter()
                        .map(|r| format!("{lane}[{index}]: {r}")),
                );
            }
        }
        if let Some(first) = attempts.first() {
            for (index, attempt) in attempts.iter().enumerate().skip(1) {
                if !observation::stable(&first.observation, &attempt.observation)? {
                    reasons.push(format!("{lane}[{index}]: unstable typed observations"));
                    validity.push(Verdict::Inconclusive);
                }
            }
        }
    }
    // All instrumented attempts are checked against the baseline, then all
    // remaining baseline attempts against the first instrumented attempt.
    // This is linear in repeats and retains each independently captured pair.
    if let (Some(left), Some(right)) = (case.baseline.first(), case.instrumented_on.first()) {
        for (index, attempt) in case.instrumented_on.iter().enumerate() {
            pairs.push(PairReport {
                baseline_attempt: 0,
                instrumented_attempt: index,
                comparison: observation::compare(
                    &left.observation,
                    &attempt.observation,
                    &case.contract,
                )?,
            });
        }
        for (index, attempt) in case.baseline.iter().enumerate().skip(1) {
            pairs.push(PairReport {
                baseline_attempt: index,
                instrumented_attempt: 0,
                comparison: observation::compare(
                    &attempt.observation,
                    &right.observation,
                    &case.contract,
                )?,
            });
        }
    }
    let result = verdict(
        std::iter::once(execution.verdict)
            .chain(validity)
            .chain(pairs.iter().map(|pair| pair.comparison.verdict)),
    );
    Ok(TypedCaseReport {
        case_id: case.contract.case_id.clone(),
        verdict: result,
        execution,
        reasons,
        pairs,
    })
}
/// Compare producer-supplied evidence. This validates a bounded protocol, not
/// the truth of a hand-authored capture or an unsupported language codec.
pub fn compare(bundle: Bundle) -> Result<Report, String> {
    if bundle.typed_schema_version != 1 {
        return Err("unsupported typed bundle schema".into());
    }
    let workload = compare::compare(protocol::Bundle {
        workload_schema_version: 1,
        scope: bundle.scope.clone(),
        cases: bundle.cases.iter().map(workload_case).collect(),
    })?;
    let cases: Vec<_> = bundle
        .cases
        .iter()
        .zip(workload.cases)
        .map(|(case, execution)| compare_case(case, execution))
        .collect::<Result<_, _>>()?;
    Ok(Report {typed_schema_version:1, claim:"equivalence over these tests and observations",
        comparison:"exact byte channels and typed boundary graphs; repeated independent attempts; producer-supplied decoded instrumentation witness",
        verdict:verdict(cases.iter().map(|case|case.verdict)), scope:bundle.scope,cases})
}
