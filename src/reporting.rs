//! Offline presentation of retained generated-run reports. Rendering does not
//! authenticate the producer or rerun application/telemetry observations.
use crate::{
    compare::CaseReport,
    protocol::{ArtefactClass, Language, Scope},
    Verdict,
};
use serde::Deserialize;
use serde_json::value::RawValue;
use std::{
    collections::{BTreeMap, BTreeSet},
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::Path,
};

const MAX_BYTES: u64 = 16 * 1024 * 1024;
const CLAIM: &str = "equivalence over these tests and observations";

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RunReport {
    schema_version: u32,
    claim: String,
    exit_code: i32,
    cases: Vec<Case>,
    blocked: Vec<Callable>,
    inventory: Vec<Callable>,
    source_sha256: String,
    source_preserved: bool,
    workspace: String,
    artefact_class: String,
    configuration: Box<RawValue>,
    configuration_sha256: String,
    #[serde(default)]
    owned_source_exclusions: Vec<OwnedSourceExclusion>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct OwnedSourceExclusion {
    path: String,
    workspace_id: Option<String>,
    plan_sha256: String,
    reason: String,
}
#[derive(Deserialize)]
struct Callable {
    id: String,
    language: Language,
    path: String,
    otelc_function: String,
    otelc_runtime_function: Option<String>,
    go_context: Option<GoContext>,
    status: String,
    reason: String,
}
#[derive(Deserialize)]
struct GoContext {
    module_root: String,
}
impl Callable {
    fn runtime_function(&self) -> Result<&str, String> {
        let Some(runtime) = self.otelc_runtime_function.as_deref() else {
            if self.go_context.is_some() {
                return Err("Go module context is missing its runtime function binding".into());
            }
            return Ok(&self.otelc_function);
        };
        let context = self
            .go_context
            .as_ref()
            .ok_or("runtime function requires a Go module context")?;
        let root = &context.module_root;
        let canonical = root == "."
            || (!root.is_empty()
                && root
                    .split('/')
                    .all(|part| !part.is_empty() && part != "." && part != ".."));
        if self.language != Language::Go
            || !canonical
            || root.contains(['\\', ':'])
            || runtime.is_empty()
        {
            return Err("invalid Go runtime function binding".into());
        }
        let expected = if root == "." {
            Some(self.otelc_function.as_str())
        } else if self.path.starts_with(&format!("{root}/")) {
            self.otelc_function
                .strip_prefix(&format!("{}.", root.replace('/', ".")))
        } else {
            None
        };
        if expected != Some(runtime) {
            return Err(
                "Go runtime function differs from its source-relative module binding".into(),
            );
        }
        Ok(runtime)
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Case {
    case: String,
    function: String,
    exit_code: i32,
    arguments: Box<RawValue>,
    argument_types: Vec<String>,
    arguments_requested: Option<Box<RawValue>>,
    receiver_fixture: Option<Box<RawValue>>,
    sequence: Option<Box<RawValue>>,
    comparison: Option<Comparison>,
    error: Option<String>,
}
#[derive(Deserialize)]
struct DeclaredStep {
    id: String,
    action: crate::sequence::Action,
    expected_baseline: Option<crate::observation::ExpectedOutcome>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ByteComparison {
    workload_schema_version: u32,
    claim: String,
    comparison: String,
    verdict: Verdict,
    scope: Scope,
    cases: Vec<CaseReport>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct TypedComparison {
    typed_schema_version: u32,
    claim: String,
    comparison: String,
    verdict: Verdict,
    scope: Scope,
    cases: Vec<crate::typed::TypedCaseReport>,
}
#[derive(Deserialize)]
#[serde(untagged)]
enum Comparison {
    Bytes(ByteComparison),
    Typed(TypedComparison),
}
impl Comparison {
    fn validate_sequence(&self, case: &Case) -> Result<(), String> {
        let steps = match self {
            Self::Typed(value) => value.cases[0].contract.steps.as_slice(),
            Self::Bytes(_) => &[],
        };
        let Some(raw) = &case.sequence else {
            return if steps.is_empty() {
                Ok(())
            } else {
                Err("ordered contract is missing its declared sequence".into())
            };
        };
        let declared: Vec<DeclaredStep> = serde_json::from_str(raw.get())
            .map_err(|error| format!("sequence metadata: {error}"))?;
        if declared.is_empty()
            || declared.len() != steps.len()
            || declared.iter().zip(steps).any(|(item, step)| {
                item.id != step.id
                    || item.action != step.action
                    || item
                        .expected_baseline
                        .as_ref()
                        .unwrap_or(&crate::observation::ExpectedOutcome::Return)
                        != &step.expected_baseline
            })
        {
            return Err("declared sequence differs from the typed step contract".into());
        }
        Ok(())
    }
    fn verdict(&self) -> Verdict {
        match self {
            Self::Bytes(value) => value.verdict,
            Self::Typed(value) => value.verdict,
        }
    }
    fn scope(&self) -> &Scope {
        match self {
            Self::Bytes(value) => &value.scope,
            Self::Typed(value) => &value.scope,
        }
    }
    fn description(&self) -> &str {
        match self {
            Self::Bytes(value) => &value.comparison,
            Self::Typed(value) => &value.comparison,
        }
    }
    fn detail(&self) -> Result<String, serde_json::Error> {
        match self {
            Self::Bytes(value) => serde_json::to_string_pretty(&value.cases[0]),
            Self::Typed(value) => serde_json::to_string_pretty(&value.cases[0]),
        }
    }
    fn validate_receiver(&self, case: &Case) -> Result<(), String> {
        if case.receiver_fixture.is_none() {
            return Ok(());
        }
        if let Self::Typed(value) = self {
            if value.cases[0]
                .contract
                .required_roots
                .iter()
                .any(|root| root == "receiver")
            {
                return Ok(());
            }
        }
        Err("receiver fixture requires a typed receiver observation contract".into())
    }
    fn validate(&self, case: &Case, entry: &Callable, report: &RunReport) -> Result<(), String> {
        let (version, claim, count, id, verdict) = match self {
            Self::Bytes(value) => (
                value.workload_schema_version,
                value.claim.as_str(),
                value.cases.len(),
                value.cases.first().map(|row| row.case_id.as_str()),
                value.cases.first().map(|row| row.verdict),
            ),
            Self::Typed(value) => (
                value.typed_schema_version,
                value.claim.as_str(),
                value.cases.len(),
                value.cases.first().map(|row| row.case_id.as_str()),
                value.cases.first().map(|row| row.verdict),
            ),
        };
        if version != 1
            || claim != CLAIM
            || count != 1
            || id != Some(case.case.as_str())
            || verdict != Some(self.verdict())
            || self.verdict().exit_code() != case.exit_code
            || self.scope().source_sha256 != report.source_sha256
            || self.scope().language != entry.language
            || !matches!(self.scope().artefact_class, ArtefactClass::Diagnostic)
        {
            return Err("case comparison identity or verdict is inconsistent".into());
        }
        self.validate_receiver(case)?;
        self.validate_sequence(case)?;
        match self {
            Self::Bytes(value) => validate_byte_case(&value.cases[0]),
            Self::Typed(value) => validate_typed_case(&value.cases[0], entry.runtime_function()?),
        }
    }
}
fn qualified(verdict: Verdict) -> bool {
    matches!(
        verdict,
        Verdict::EquivalentObserved | Verdict::DifferentObserved
    )
}
fn validate_byte_case(result: &CaseReport) -> Result<(), String> {
    if qualified(result.verdict)
        && ((!result.differences.is_empty()) != (result.verdict == Verdict::DifferentObserved)
            || !result.reasons.is_empty()
            || !(2..=100).contains(&result.baseline_attempts)
            || !(2..=100).contains(&result.instrumented_attempts))
    {
        return Err("qualified verdict contradicts differences, gaps or repeat counts".into());
    }
    Ok(())
}
fn validate_typed_case(
    result: &crate::typed::TypedCaseReport,
    function: &str,
) -> Result<(), String> {
    let execution = &result.execution;
    result.contract.validate()?;
    validate_byte_case(execution)?;
    if result.contract.function_id != function
        || result.contract.case_id != result.case_id
        || execution.case_id != result.case_id
        || execution.baseline_attempts > 100
        || execution.instrumented_attempts > 100
    {
        return Err("typed case identity or repeat limit is inconsistent".into());
    }
    let expected: BTreeSet<_> =
        if execution.baseline_attempts == 0 || execution.instrumented_attempts == 0 {
            BTreeSet::new()
        } else {
            (0..execution.instrumented_attempts)
                .map(|index| (0, index))
                .chain((1..execution.baseline_attempts).map(|index| (index, 0)))
                .collect()
        };
    let actual: BTreeSet<_> = result
        .pairs
        .iter()
        .map(|pair| (pair.baseline_attempt, pair.instrumented_attempt))
        .collect();
    if actual != expected || actual.len() != result.pairs.len() {
        return Err("typed comparison pairs are missing, duplicated or out of range".into());
    }
    let mut difference = execution.verdict == Verdict::DifferentObserved;
    for pair in &result.pairs {
        let comparison = &pair.comparison;
        if qualified(comparison.verdict)
            && (!comparison.reasons.is_empty()
                || !comparison.initial_differences.is_empty()
                || (!comparison.differences.is_empty())
                    != (comparison.verdict == Verdict::DifferentObserved))
        {
            return Err("typed pair verdict contradicts differences or gaps".into());
        }
        difference |= comparison.verdict == Verdict::DifferentObserved;
    }
    if qualified(result.verdict)
        && (!qualified(execution.verdict)
            || !result.reasons.is_empty()
            || result
                .pairs
                .iter()
                .any(|pair| !qualified(pair.comparison.verdict))
            || difference != (result.verdict == Verdict::DifferentObserved))
    {
        return Err(
            "qualified typed verdict contradicts its complete execution/pair evidence".into(),
        );
    }
    Ok(())
}
#[derive(Clone, Copy, PartialEq)]
enum Outcome {
    Match,
    Difference,
    Error,
    Excluded,
}
impl Outcome {
    fn label(self) -> &'static str {
        match self {
            Self::Match => "equivalent_observed",
            Self::Difference => "different_observed",
            Self::Error => "incomplete",
            Self::Excluded => "excluded",
        }
    }
}
struct Row {
    name: String,
    class: String,
    outcome: Outcome,
    details: String,
}

/// A self-contained HTML page and JUnit XML, with strict denominators. The exit
/// status also fails when inventory entries lack cases, including partial replay.
pub struct RenderedReport {
    pub html: String,
    pub junit: String,
    pub exit_code: i32,
}

fn language_name(language: &Language) -> &'static str {
    match language {
        Language::C => "c",
        Language::Cpp => "cpp",
        Language::Rust => "rust",
        Language::Python => "python",
        Language::Java => "java",
        Language::Javascript => "javascript",
        Language::Typescript => "typescript",
        Language::Go => "go",
    }
}
fn sha(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit())
}
fn exclusion_summary(report: &RunReport) -> Result<String, String> {
    if report.owned_source_exclusions.len() > 10000 {
        return Err("too many retained workspace exclusions".into());
    }
    let mut paths = BTreeSet::new();
    let mut summary = format!(
        "Retained oteleq output excluded from application inputs: {}",
        report.owned_source_exclusions.len()
    );
    for entry in &report.owned_source_exclusions {
        if entry.path.is_empty()
            || entry.path.len() > 4096
            || entry.path.starts_with('/')
            || entry
                .path
                .split('/')
                .any(|part| matches!(part, "" | "." | ".."))
            || !sha(&entry.plan_sha256)
            || entry.reason != "verified retained oteleq workspace"
            || !paths.insert(&entry.path)
        {
            return Err("invalid retained workspace exclusion".into());
        }
        summary.push_str(&format!(
            "\n{}; workspace {}; plan {}; {}",
            entry.path,
            entry.workspace_id.as_deref().unwrap_or("unavailable"),
            entry.plan_sha256,
            entry.reason
        ));
    }
    Ok(summary)
}
fn validate_inventory(report: &RunReport) -> Result<BTreeMap<&str, &Callable>, String> {
    if report.schema_version != 1
        || report.claim != CLAIM
        || report.artefact_class != "diagnostic"
        || !sha(&report.source_sha256)
        || !sha(&report.configuration_sha256)
        || report.inventory.len() > 10000
        || report.cases.len() > 1024
        || !(0..=4).contains(&report.exit_code)
    {
        return Err("unsupported or invalid generated report identity, schema or size".into());
    }
    let mut inventory = BTreeMap::new();
    for entry in &report.inventory {
        entry.runtime_function()?;
        if entry.id.len() != 20
            || !entry.id.bytes().all(|byte| byte.is_ascii_hexdigit())
            || entry.otelc_function.is_empty()
            || entry.path.is_empty()
            || !["ready", "blocked", "excluded"].contains(&entry.status.as_str())
            || inventory.insert(entry.id.as_str(), entry).is_some()
        {
            return Err("invalid or duplicate callable inventory".into());
        }
    }
    let mut blocked = BTreeSet::new();
    for entry in &report.blocked {
        let Some(original) = inventory.get(entry.id.as_str()) else {
            return Err("unknown blocked callable".into());
        };
        if original.status != "blocked"
            || entry.status != "blocked"
            || original.reason != entry.reason
            || !blocked.insert(&entry.id)
        {
            return Err("inconsistent blocked callable".into());
        }
    }
    Ok(inventory)
}
fn case_details(case: &Case, comparison: &Comparison) -> Result<String, String> {
    let detail = comparison
        .detail()
        .map_err(|error| format!("render comparison: {error}"))?;
    let scope = serde_json::to_string_pretty(comparison.scope())
        .map_err(|error| format!("render scope: {error}"))?;
    Ok(format!(
        "Argument types: {:?}\nActual arguments: {}\nRequested arguments: {}\nReceiver fixture: {}\nSequence: {}\n{}\n{}\n{}",
        case.argument_types,
        case.arguments.get(),
        case.arguments_requested
            .as_ref()
            .map_or("not separately configured", |value| value.get()),
        case.receiver_fixture
            .as_ref()
            .map_or("none", |value| value.get()),
        case.sequence.as_ref().map_or("none", |value| value.get()),
        comparison.description(),
        detail,
        scope
    ))
}
fn case_row(case: &Case, entry: &Callable, report: &RunReport) -> Result<Row, String> {
    if entry.status != "ready" || case.function != entry.otelc_function {
        return Err("case is not mapped to a ready inventory callable".into());
    }
    let (outcome, details) = match (&case.comparison, &case.error) {
        (Some(comparison), None) => {
            comparison.validate(case, entry, report)?;
            let outcome = match comparison.verdict() {
                Verdict::EquivalentObserved => Outcome::Match,
                Verdict::DifferentObserved => Outcome::Difference,
                _ => Outcome::Error,
            };
            (outcome, case_details(case, comparison)?)
        }
        (None, Some(error)) if case.exit_code == 4 => (Outcome::Error, error.clone()),
        _ => return Err("case needs a consistent comparison or tool error".into()),
    };
    Ok(Row {
        name: format!("{} [{}]", entry.otelc_function, case.case),
        class: format!("{}:{}", language_name(&entry.language), entry.path),
        outcome,
        details,
    })
}
fn rows(report: &RunReport) -> Result<Vec<Row>, String> {
    let inventory = validate_inventory(report)?;
    let mut rows = Vec::new();
    let mut ids = BTreeSet::new();
    let mut tested = BTreeSet::new();
    for case in &report.cases {
        let Some((id, index)) = case.case.rsplit_once('-') else {
            return Err("invalid generated case ID".into());
        };
        if index.is_empty()
            || !index.bytes().all(|byte| byte.is_ascii_digit())
            || !ids.insert(&case.case)
        {
            return Err("invalid or duplicate generated case ID".into());
        }
        let Some(entry) = inventory.get(id) else {
            return Err("case references unknown callable".into());
        };
        rows.push(case_row(case, entry, report)?);
        tested.insert(id);
    }
    for entry in inventory.values() {
        let (outcome, details) = match entry.status.as_str() {
            "excluded" => (Outcome::Excluded, "Deliberately excluded; no equivalence claim.".to_owned()),
            "blocked" => (Outcome::Error, format!("Blocked callable: {}", entry.reason)),
            _ if !tested.contains(entry.id.as_str()) => (Outcome::Error, "Ready callable has no retained case in this report. A partial replay does not cover the complete inventory.".to_owned()),
            _ => continue,
        };
        rows.push(Row {
            name: entry.otelc_function.clone(),
            class: format!("{}:{}", language_name(&entry.language), entry.path),
            outcome,
            details,
        });
    }
    if report.cases.is_empty()
        || !report.source_preserved
        || report.exit_code != 0
            && rows
                .iter()
                .all(|row| matches!(row.outcome, Outcome::Match | Outcome::Excluded))
    {
        rows.push(Row {
            name: "Run qualification".into(),
            class: "oteleq".into(),
            outcome: Outcome::Error,
            details: format!(
                "No complete successful run: {} cases, source_preserved={}, recorded exit={}",
                report.cases.len(),
                report.source_preserved,
                report.exit_code
            ),
        });
    }
    Ok(rows)
}

// Escape once for both XML 1.0 and HTML. Represent invalid XML/control characters
// visibly rather than dropping observed application data from the presentation.
fn escaped(text: &str) -> String {
    let mut output = String::new();
    for character in text.chars() {
        match character {
            '&' => output.push_str("&amp;"),
            '<' => output.push_str("&lt;"),
            '>' => output.push_str("&gt;"),
            '"' => output.push_str("&quot;"),
            '\'' => output.push_str("&apos;"),
            '\t' => output.push_str("&#9;"),
            '\n' => output.push_str("&#10;"),
            '\r' => output.push_str("&#13;"),
            c if c.is_control() || matches!(c, '\u{fffe}' | '\u{ffff}') => {
                output.push_str(&format!("\\u{{{:x}}}", c as u32))
            }
            c => output.push(c),
        }
    }
    output
}

/// Render a schema-1 generated-run report without executing its code or paths.
/// Raw scalar arguments retain their JSON digits, including 128-bit integers.
pub fn render(bytes: &[u8]) -> Result<RenderedReport, String> {
    if bytes.len() as u64 > MAX_BYTES {
        return Err("report exceeds 16 MiB".into());
    }
    let report: RunReport = serde_json::from_slice(bytes)
        .map_err(|error| format!("decode generated report: {error}"))?;
    let rows = rows(&report)?;
    let exclusions = exclusion_summary(&report)?;
    let count = |outcome| rows.iter().filter(|row| row.outcome == outcome).count();
    let (matched, failures, errors, skipped) = (
        count(Outcome::Match),
        count(Outcome::Difference),
        count(Outcome::Error),
        count(Outcome::Excluded),
    );
    let exit_code = if errors > 0 {
        3
    } else if failures > 0 {
        1
    } else {
        0
    };
    let summary = format!("{} paired cases matched; {} observed differences; {} incomplete/error entries; {} excluded callables. Inventory: {} callables; retained cases: {}.", matched, failures, errors, skipped, report.inventory.len(), report.cases.len());
    let identity = format!("Source: {}\nSource preserved: {}\nConfiguration: {}\nWorkspace recorded by producer: {}\nArtefact class: {}\nPolicy: {}\n{}", report.source_sha256, report.source_preserved, report.configuration_sha256, report.workspace, report.artefact_class, report.configuration.get(), exclusions);
    let mut html = format!("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width\"><meta http-equiv=\"Content-Security-Policy\" content=\"default-src &apos;none&apos;; style-src &apos;unsafe-inline&apos;\"><title>oteleq observations</title><style>body{{font:16px system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#17212b;background:#fff}}table{{border-collapse:collapse;width:100%}}th,td{{padding:.6rem;text-align:left;border-bottom:1px solid #ccd4db;vertical-align:top}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f0f3f6;padding:1rem}}td{{overflow-wrap:anywhere}}details{{margin:.4rem 0}}.incomplete,.different_observed{{font-weight:bold}}caption{{text-align:left;padding:1rem 0}}h1{{font-size:1.8rem}}</style></head><body><h1>oteleq observations</h1><p><strong>{CLAIM}</strong></p><p>{}</p><p>Diagnostic harness evidence applies to the recorded tests and dimensions. Rendering presents producer-supplied evidence; it does not rerun or authenticate capture. It provides no blanket proof for other inputs or shipping artefacts. Redaction is not applied: treat this page and XML as application data.</p><details><summary>Source, policy and execution identity</summary><pre>{}</pre></details><table><caption>All retained cases and inventory gaps</caption><thead><tr><th scope=\"col\">Callable / case</th><th scope=\"col\">Source</th><th scope=\"col\">Result and observations</th></tr></thead><tbody>", escaped(&summary), escaped(&identity));
    let mut junit = format!("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<testsuites tests=\"{}\" failures=\"{failures}\" errors=\"{errors}\" skipped=\"{skipped}\"><testsuite name=\"oteleq.observed-equivalence\" tests=\"{}\" failures=\"{failures}\" errors=\"{errors}\" skipped=\"{skipped}\"><properties><property name=\"claim\" value=\"{CLAIM}\"/><property name=\"artefact_class\" value=\"diagnostic\"/><property name=\"source_sha256\" value=\"{}\"/><property name=\"configuration_sha256\" value=\"{}\"/><property name=\"summary\" value=\"{}\"/><property name=\"owned_source_exclusions\" value=\"{}\"/></properties>\n", rows.len(), rows.len(), escaped(&report.source_sha256), escaped(&report.configuration_sha256), escaped(&summary), escaped(&exclusions));
    for row in rows {
        let (name, class, details) = (
            escaped(&row.name),
            escaped(&row.class),
            escaped(&row.details),
        );
        html.push_str(&format!("<tr><td>{name}</td><td>{class}</td><td class=\"{}\">{}<details><summary>Details and limits</summary><pre>{details}</pre></details></td></tr>\n", row.outcome.label(), row.outcome.label()));
        junit.push_str(&format!("<testcase name=\"{name}\" classname=\"{class}\">"));
        match row.outcome {
            Outcome::Match => {},
            Outcome::Difference => junit.push_str(&format!("<failure type=\"observed_difference\" message=\"Declared observations differ\">{details}</failure>")),
            Outcome::Error => junit.push_str(&format!("<error type=\"incomplete_evidence\" message=\"Equivalence not established\">{details}</error>")),
            Outcome::Excluded => junit.push_str(&format!("<skipped message=\"Explicitly excluded\">{details}</skipped>")),
        }
        junit.push_str(&format!("<system-out>{details}</system-out></testcase>\n"));
    }
    html.push_str("</tbody></table></body></html>\n");
    junit.push_str("</testsuite></testsuites>\n");
    Ok(RenderedReport {
        html,
        junit,
        exit_code,
    })
}

/// Read one bounded report and create a private, new presentation directory.
/// Existing paths are never overwritten. No path recorded by the report is read.
pub fn write_report(input: &Path, destination: &Path) -> Result<i32, String> {
    let file = File::open(input).map_err(|error| format!("open report: {error}"))?;
    let mut bytes = Vec::new();
    file.take(MAX_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|error| format!("read report: {error}"))?;
    let rendered = render(&bytes)?;
    let mut builder = fs::DirBuilder::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;
        builder.mode(0o700);
    }
    builder
        .create(destination)
        .map_err(|error| format!("create new report directory: {error}"))?;
    for (name, text) in [
        ("index.html", &rendered.html),
        ("junit.xml", &rendered.junit),
    ] {
        let mut options = OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        options
            .open(destination.join(name))
            .and_then(|mut file| file.write_all(text.as_bytes()))
            .map_err(|error| format!("write {name}: {error}"))?;
    }
    Ok(rendered.exit_code)
}
