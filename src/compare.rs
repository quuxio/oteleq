use crate::protocol::{Attempt, Bundle, Case, Scope, Termination};
use serde::Serialize;
use std::collections::BTreeSet;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Verdict {
    EquivalentObserved,
    DifferentObserved,
    Inconclusive,
    Blocked,
}
impl Verdict {
    pub fn exit_code(self) -> i32 {
        match self {
            Self::EquivalentObserved => 0,
            Self::DifferentObserved => 1,
            Self::Inconclusive => 3,
            Self::Blocked => 2,
        }
    }
}
#[derive(Debug, Serialize)]
pub struct Difference {
    pub path: String,
    pub baseline: Vec<u8>,
    pub instrumented_on: Vec<u8>,
}
#[derive(Debug, Serialize)]
pub struct CaseReport {
    pub case_id: String,
    pub verdict: Verdict,
    pub reasons: Vec<String>,
    pub differences: Vec<Difference>,
    pub baseline_attempts: usize,
    pub instrumented_attempts: usize,
}
#[derive(Debug, Serialize)]
pub struct Report {
    pub workload_schema_version: u32,
    pub claim: &'static str,
    pub comparison: &'static str,
    pub verdict: Verdict,
    pub scope: Scope,
    pub cases: Vec<CaseReport>,
}

fn sha(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|c| c.is_ascii_hexdigit())
}
/// Validate bounded structure before evaluating any evidence. The producer owns
/// capture/decoding; this comparator cannot authenticate a hand-written bundle.
pub fn compare(bundle: Bundle) -> Result<Report, String> {
    if bundle.workload_schema_version != 1 {
        return Err("unsupported workload schema".into());
    }
    let s = &bundle.scope;
    let channels: BTreeSet<_> = s.channels.iter().collect();
    if ![
        &s.source_sha256,
        &s.baseline_artefact_sha256,
        &s.instrumented_artefact_sha256,
        &s.policy_sha256,
    ]
    .iter()
    .all(|v| sha(v))
        || s.observer.trim().is_empty()
        || channels.is_empty()
        || channels.len() != s.channels.len()
        || channels.iter().any(|channel| channel.trim().is_empty())
    {
        return Err("scope needs SHA-256 identities, observer and distinct byte channels".into());
    }
    if bundle.cases.is_empty() || bundle.cases.len() > 10000 {
        return Err("require 1..10000 concrete cases".into());
    }
    let mut ids = BTreeSet::new();
    let mut reports = Vec::with_capacity(bundle.cases.len());
    for case in &bundle.cases {
        if case.case_id.trim().is_empty()
            || !ids.insert(&case.case_id)
            || !sha(&case.corpus_sha256)
            || case.expected_spans == 0
            || case.expected_functions.is_empty()
            || case
                .expected_functions
                .values()
                .try_fold(0u64, |sum, count| sum.checked_add(*count))
                != Some(case.expected_spans)
            || case
                .expected_functions
                .iter()
                .any(|(name, count)| name.trim().is_empty() || *count == 0)
            || case.baseline.len() > 100
            || case.instrumented_on.len() > 100
        {
            return Err(
                "invalid/duplicate case, corpus, witness expectation or repeat limit".into(),
            );
        }
        reports.push(compare_case(case, s, &channels));
    }
    // Incomplete evidence takes precedence: a stable difference in another case
    // does not establish that a truncated or unstable experiment is valid.
    let verdict = [
        Verdict::Blocked,
        Verdict::Inconclusive,
        Verdict::DifferentObserved,
    ]
    .into_iter()
    .find(|v| reports.iter().any(|r| r.verdict == *v))
    .unwrap_or(Verdict::EquivalentObserved);
    Ok(Report {
        workload_schema_version: 1,
        claim: "equivalence over these tests and observations",
        comparison: "exact declared byte channels and successful exit; provider-supplied decoded telemetry witness; no graph comparison",
        verdict, scope: bundle.scope, cases: reports,
    })
}

fn compare_case(case: &Case, scope: &Scope, channels: &BTreeSet<&String>) -> CaseReport {
    let mut report = CaseReport {
        case_id: case.case_id.clone(),
        verdict: Verdict::EquivalentObserved,
        reasons: Vec::new(),
        differences: Vec::new(),
        baseline_attempts: case.baseline.len(),
        instrumented_attempts: case.instrumented_on.len(),
    };
    let mut blocked = false;
    if case.baseline.len() < 2 || case.instrumented_on.len() < 2 {
        report
            .reasons
            .push("need at least two independent attempts in both lanes".into());
    }
    for (lane, attempts) in [
        ("baseline", &case.baseline),
        ("instrumented_on", &case.instrumented_on),
    ] {
        for (index, attempt) in attempts.iter().enumerate() {
            let prefix = format!("{lane}[{index}]");
            if attempt.source_sha256_before != scope.source_sha256
                || attempt.source_sha256_after != scope.source_sha256
            {
                blocked = true;
                report.reasons.push(format!(
                    "{prefix}: source identity changed or disagrees with scope"
                ));
            }
            if attempt.termination != (Termination::Exit { code: 0 }) {
                report.reasons.push(format!("{prefix}: target invalid or tool failure; only successful workload exits qualify"));
            }
            if !attempt.capture_complete || !attempt.channels.keys().eq(channels.iter().copied()) {
                report
                    .reasons
                    .push(format!("{prefix}: incomplete or undeclared byte channel"));
            }
            if lane == "baseline" {
                if attempt.witness.is_some() {
                    report.reasons.push(format!(
                        "{prefix}: baseline carries instrumentation witness"
                    ));
                }
            } else if !qualified_witness(attempt, case) {
                report.reasons.push(format!(
                    "{prefix}: missing, mismatched, lossy or incomplete instrumentation witness"
                ));
            }
        }
        if let Some(first) = attempts.first() {
            if attempts
                .iter()
                .skip(1)
                .any(|a| a.channels != first.channels || a.termination != first.termination)
            {
                report.reasons.push(format!(
                    "{lane}: unstable observations; do not filter or normalise these differences"
                ));
            }
        }
    }
    if blocked {
        report.verdict = Verdict::Blocked;
    } else if !report.reasons.is_empty() {
        report.verdict = Verdict::Inconclusive;
    } else if let (Some(baseline), Some(instrumented)) =
        (case.baseline.first(), case.instrumented_on.first())
    {
        for channel in &scope.channels {
            let a = &baseline.channels[channel];
            let b = &instrumented.channels[channel];
            if a != b {
                report.differences.push(Difference {
                    path: format!("channels.{channel}"),
                    baseline: a.clone(),
                    instrumented_on: b.clone(),
                });
            }
        }
        if !report.differences.is_empty() {
            report.verdict = Verdict::DifferentObserved;
        }
    }
    report
}
fn qualified_witness(attempt: &Attempt, case: &Case) -> bool {
    attempt.witness.as_ref().is_some_and(|w| {
        !w.decoder.trim().is_empty()
            && sha(&w.raw_otlp_sha256)
            && w.spans == case.expected_spans
            && w.functions == case.expected_functions
            && w.pending == 0
            && !w.losses.is_empty()
            && w.losses
                .iter()
                .all(|(name, count)| !name.trim().is_empty() && *count == 0)
    })
}
