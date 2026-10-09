use quux_oteleq::{compare, Bundle, Verdict};
use serde_json::{json, Value};
use std::{
    fs,
    process::{Command, Stdio},
};
fn fixture() -> Value {
    let hash = "a".repeat(64);
    let attempt = json!({"source_sha256_before":hash,"source_sha256_after":hash,
        "termination":{"kind":"exit","code":0},"channels":{"stdout":[255,0,42],"stderr":[]},
        "capture_complete":true,"witness":null});
    let mut on = attempt.clone();
    on["witness"] = json!({"decoder":"otlp-protobuf-test-v1","raw_otlp_sha256":hash,
        "functions":{"work":1},"spans":1,"losses":{"export":0},"pending":0});
    json!({"workload_schema_version":1,"scope":{"language":"python","artefact_class":"diagnostic",
        "source_sha256":hash,"baseline_artefact_sha256":hash,"instrumented_artefact_sha256":hash,
        "policy_sha256":hash,"observer":"independent subprocess capture v1",
        "channels":["stdout","stderr"],"gaps":["globals and receiver state not captured"]},
        "cases":[{"case_id":"work","corpus_sha256":hash,"expected_functions":{"work":1},
            "expected_spans":1,"baseline":[attempt.clone(),attempt],"instrumented_on":[on.clone(),on]}]})
}
fn evaluate(value: Value) -> quux_oteleq::Report {
    compare(serde_json::from_value::<Bundle>(value).unwrap()).unwrap()
}
#[test]
fn exact_non_unicode_channels_repeated_and_gaps_preserved() {
    let report = evaluate(fixture());
    assert_eq!(report.verdict, Verdict::EquivalentObserved);
    assert_eq!(
        report.scope.gaps,
        ["globals and receiver state not captured"]
    );
    assert_eq!(
        report.claim,
        "equivalence over these tests and observations"
    );
    assert_eq!(report.cases[0].baseline_attempts, 2);
}
#[test]
fn same_return_but_different_effect_bytes_is_a_difference() {
    for channel in ["stdout", "stderr"] {
        let mut f = fixture();
        for attempt in f["cases"][0]["instrumented_on"].as_array_mut().unwrap() {
            attempt["channels"][channel] = json!([3, 5]);
        }
        let report = evaluate(f);
        assert_eq!(report.verdict, Verdict::DifferentObserved);
        assert_eq!(
            report.cases[0].differences[0].path,
            format!("channels.{channel}")
        );
        assert_eq!(report.verdict.exit_code(), 1);
    }
}
#[test]
fn all_eight_language_ids_use_the_same_comparator() {
    for language in [
        "c",
        "cpp",
        "rust",
        "python",
        "java",
        "javascript",
        "typescript",
        "go",
    ] {
        let mut f = fixture();
        f["scope"]["language"] = json!(language);
        assert_eq!(evaluate(f).verdict, Verdict::EquivalentObserved);
    }
    let mut f = fixture();
    f["scope"]["language"] = json!("ruby");
    assert!(serde_json::from_value::<Bundle>(f).is_err());
}
#[test]
fn either_unstable_lane_is_inconclusive_without_filtering() {
    for lane in ["baseline", "instrumented_on"] {
        let mut f = fixture();
        f["cases"][0][lane][1]["channels"]["stdout"] = json!([13]);
        let report = evaluate(f);
        assert_eq!(report.verdict, Verdict::Inconclusive);
        assert!(report.cases[0]
            .reasons
            .iter()
            .any(|r| r.contains("unstable")));
        assert!(report.cases[0].differences.is_empty());
    }
}
#[test]
fn zero_cases_and_invalid_contracts_are_not_success() {
    for (path, replacement) in [
        (vec!["workload_schema_version"], json!(2)),
        (vec!["cases"], json!([])),
        (vec!["scope", "channels"], json!([])),
        (vec!["scope", "channels"], json!(["stdout", "stdout"])),
        (vec!["scope", "channels"], json!([""])),
        (vec!["scope", "observer"], json!("")),
        (vec!["scope", "source_sha256"], json!("bad")),
    ] {
        let mut f = fixture();
        let mut item = &mut f;
        for key in path {
            item = &mut item[key];
        }
        *item = replacement;
        assert!(compare(serde_json::from_value(f).unwrap()).is_err());
    }
    for field in ["case_id", "corpus_sha256"] {
        let mut f = fixture();
        f["cases"][0][field] = json!("");
        assert!(compare(serde_json::from_value(f).unwrap()).is_err());
    }
    for (field, value) in [
        ("expected_spans", json!(0)),
        ("expected_functions", json!({})),
        ("expected_functions", json!({"":1})),
        ("expected_functions", json!({"work":0})),
        ("expected_functions", json!({"work":2})),
        (
            "expected_functions",
            json!({"work":18446744073709551615u64,"other":1}),
        ),
    ] {
        let mut f = fixture();
        f["cases"][0][field] = value;
        assert!(compare(serde_json::from_value(f).unwrap()).is_err());
    }
    let mut f = fixture();
    let duplicate = f["cases"][0].clone();
    f["cases"].as_array_mut().unwrap().push(duplicate);
    assert!(compare(serde_json::from_value(f).unwrap()).is_err());
}
#[test]
fn repeat_bounds_and_missing_attempts_are_explicit() {
    for lane in ["baseline", "instrumented_on"] {
        let mut f = fixture();
        f["cases"][0][lane] = json!([]);
        assert_eq!(evaluate(f).verdict, Verdict::Inconclusive);
        let mut f = fixture();
        f["cases"][0][lane].as_array_mut().unwrap().pop();
        assert_eq!(evaluate(f).verdict, Verdict::Inconclusive);
        let mut f = fixture();
        let attempt = f["cases"][0][lane][0].clone();
        f["cases"][0][lane] = json!(vec![attempt; 101]);
        assert!(compare(serde_json::from_value(f).unwrap()).is_err());
    }
}
#[test]
fn missing_incomplete_and_undeclared_channels_never_pass() {
    for lane in ["baseline", "instrumented_on"] {
        for mode in ["missing", "extra", "truncated"] {
            let mut f = fixture();
            for attempt in f["cases"][0][lane].as_array_mut().unwrap() {
                match mode {
                    "missing" => {
                        attempt["channels"]
                            .as_object_mut()
                            .unwrap()
                            .remove("stderr");
                    }
                    "extra" => {
                        attempt["channels"]["undeclared"] = json!([]);
                    }
                    _ => {
                        attempt["capture_complete"] = json!(false);
                    }
                }
            }
            assert_eq!(evaluate(f).verdict, Verdict::Inconclusive);
        }
    }
}
#[test]
fn matching_crashes_nonzero_exits_timeouts_and_tool_failures_are_not_equivalence() {
    for termination in [
        json!({"kind":"exit","code":7}),
        json!({"kind":"signal","number":11}),
        json!({"kind":"timeout"}),
        json!({"kind":"tool_error"}),
    ] {
        let mut f = fixture();
        for lane in ["baseline", "instrumented_on"] {
            for a in f["cases"][0][lane].as_array_mut().unwrap() {
                a["termination"] = termination.clone();
            }
        }
        assert_eq!(evaluate(f).verdict, Verdict::Inconclusive);
    }
}
#[test]
fn source_mutation_in_either_lane_blocks_and_has_precedence() {
    for lane in ["baseline", "instrumented_on"] {
        for position in ["source_sha256_before", "source_sha256_after"] {
            let mut f = fixture();
            f["cases"][0][lane][0][position] = json!("b".repeat(64));
            assert_eq!(evaluate(f).verdict, Verdict::Blocked);
        }
    }
    assert_eq!(Verdict::Blocked.exit_code(), 2);
}
#[test]
fn witness_missing_wrong_count_wrong_identity_loss_or_pending_is_incomplete() {
    for replacement in [
        Value::Null,
        json!({"decoder":"decoder","raw_otlp_sha256":"x",
        "functions":{"work":1},"spans":1,"losses":{},"pending":0}),
    ] {
        let mut f = fixture();
        f["cases"][0]["instrumented_on"][0]["witness"] = replacement;
        assert_eq!(evaluate(f).verdict, Verdict::Inconclusive);
    }
    for (field, value) in [
        ("decoder", json!("")),
        ("functions", json!({"other":1})),
        ("spans", json!(2)),
        ("losses", json!({"export":1})),
        ("losses", json!({})),
        ("losses", json!({" ":0})),
        ("pending", json!(1)),
    ] {
        let mut f = fixture();
        f["cases"][0]["instrumented_on"][0]["witness"][field] = value;
        assert_eq!(evaluate(f).verdict, Verdict::Inconclusive);
    }
    let mut f = fixture();
    f["cases"][0]["baseline"][0]["witness"] =
        f["cases"][0]["instrumented_on"][0]["witness"].clone();
    assert_eq!(evaluate(f).verdict, Verdict::Inconclusive);
    assert_eq!(Verdict::Inconclusive.exit_code(), 3);
}
#[test]
fn duplicate_evidence_map_keys_are_rejected_before_comparison() {
    let original = fixture().to_string();
    for (needle, replacement) in [
        ("\"export\":0", "\"export\":99,\"export\":0"),
        (
            "\"stdout\":[255,0,42]",
            "\"stdout\":[13],\"stdout\":[255,0,42]",
        ),
        (
            "\"expected_functions\":{\"work\":1}",
            "\"expected_functions\":{\"work\":2,\"work\":1}",
        ),
        (
            "\"functions\":{\"work\":1}",
            "\"functions\":{\"work\":2,\"work\":1}",
        ),
    ] {
        assert!(original.contains(needle));
        let raw = original.replace(needle, replacement);
        let error = serde_json::from_str::<Bundle>(&raw).unwrap_err();
        assert!(error.to_string().contains("duplicate map key"));
    }
}

#[test]
fn declared_channel_order_does_not_change_exact_membership_checks() {
    let mut f = fixture();
    f["scope"]["channels"] = json!(["stderr", "stdout"]);
    assert_eq!(evaluate(f).verdict, Verdict::EquivalentObserved);
}
#[test]
fn mixed_cases_keep_all_results_and_completeness_precedes_difference() {
    let mut f = fixture();
    let mut other = f["cases"][0].clone();
    other["case_id"] = json!("other");
    other["baseline"] = json!([]);
    f["cases"].as_array_mut().unwrap().push(other);
    for a in f["cases"][0]["instrumented_on"].as_array_mut().unwrap() {
        a["channels"]["stdout"] = json!([42]);
    }
    let report = evaluate(f);
    assert_eq!(report.verdict, Verdict::Inconclusive);
    assert_eq!(report.cases.len(), 2);
    assert_eq!(report.cases[0].verdict, Verdict::DifferentObserved);
}
#[test]
fn cli_reports_outcomes_and_never_accepts_missing_malformed_or_oversized_bundle() {
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("bundle.json");
    let cli = env!("CARGO_BIN_EXE_quux-oteleq");
    let run = || {
        Command::new(cli)
            .arg("compare-workload")
            .arg(&path)
            .output()
            .unwrap()
    };
    fs::write(&path, fixture().to_string()).unwrap();
    let result = run();
    assert!(result.status.success());
    let report: Value = serde_json::from_slice(&result.stdout).unwrap();
    assert_eq!(report["verdict"], "equivalent_observed");
    let mut f = fixture();
    for a in f["cases"][0]["instrumented_on"].as_array_mut().unwrap() {
        a["channels"]["stdout"] = json!([0]);
    }
    fs::write(&path, f.to_string()).unwrap();
    assert_eq!(run().status.code(), Some(1));
    let mut f = fixture();
    f["cases"][0]["baseline"] = json!([]);
    fs::write(&path, f.to_string()).unwrap();
    assert_eq!(run().status.code(), Some(3));
    let mut f = fixture();
    f["cases"] = json!([]);
    fs::write(&path, f.to_string()).unwrap();
    assert_eq!(run().status.code(), Some(2));
    fs::write(&path, "broken").unwrap();
    assert_eq!(run().status.code(), Some(4));
    fs::write(&path, vec![b' '; 16 * 1024 * 1024 + 1]).unwrap();
    assert_eq!(run().status.code(), Some(4));
    fs::remove_file(&path).unwrap();
    assert_eq!(run().status.code(), Some(4));
    assert_eq!(Command::new(cli).output().unwrap().status.code(), Some(2));
    assert_eq!(
        Command::new(cli)
            .arg("wrong")
            .arg("file")
            .output()
            .unwrap()
            .status
            .code(),
        Some(2)
    );
    let help = Command::new(cli).arg("--help").output().unwrap();
    assert!(help.status.success());
    assert!(String::from_utf8(help.stdout)
        .unwrap()
        .contains("No execution or test generation"));
}
#[test]
fn schema_is_strict_and_untyped_numeric_bytes_cannot_overflow() {
    let mut f = fixture();
    f["scope"]["ignored"] = json!(true);
    assert!(serde_json::from_value::<Bundle>(f).is_err());
    let mut f = fixture();
    f["cases"][0]["baseline"][0]["channels"]["stdout"] = json!([256]);
    assert!(serde_json::from_value::<Bundle>(f).is_err());
    let mut f = fixture();
    f["cases"][0]["baseline"][0]["termination"]["ignored"] = json!(0);
    assert!(serde_json::from_value::<Bundle>(f).is_err());
    assert_eq!(Verdict::EquivalentObserved.exit_code(), 0);
}

#[test]
fn cli_reports_output_failure_instead_of_losing_buffered_report_bytes() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("bundle.json");
    let mut f = fixture();
    for attempt in f["cases"][0]["instrumented_on"].as_array_mut().unwrap() {
        attempt["channels"]["stdout"] = json!(vec![42; 100_000]);
    }
    fs::write(&path, f.to_string()).unwrap();
    let mut child = Command::new(env!("CARGO_BIN_EXE_quux-oteleq"))
        .arg("compare-workload")
        .arg(&path)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    drop(child.stdout.take());
    let result = child.wait_with_output().unwrap();
    assert_eq!(result.status.code(), Some(4));
    assert!(!result.stderr.is_empty());
}
