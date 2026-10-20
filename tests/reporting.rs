use quux_oteleq::reporting::{render, write_report};
use serde_json::{json, Value};
use std::{fs, process::Command};

const ID: &str = "0123456789abcdef0123";
fn fixture() -> Value {
    let source = "a".repeat(64);
    let callable = json!({"id":ID,"language":"python","path":"package/target.py","otelc_function":"package.target.add","status":"ready","reason":""});
    let comparison = json!({"workload_schema_version":1,"claim":"equivalence over these tests and observations","comparison":"exact declared byte channels","verdict":"equivalent_observed","scope":{"language":"python","artefact_class":"diagnostic","source_sha256":source,"baseline_artefact_sha256":"b".repeat(64),"instrumented_artefact_sha256":"c".repeat(64),"policy_sha256":"d".repeat(64),"observer":"qualified local witness","channels":["stdout","state-and-outcome"],"gaps":["diagnostic only; no shipping claim"]},"cases":[{"case_id":format!("{ID}-0"),"verdict":"equivalent_observed","reasons":[],"differences":[],"baseline_attempts":2,"instrumented_attempts":2}]});
    json!({"schema_version":1,"claim":"equivalence over these tests and observations","exit_code":0,"cases":[{"case":format!("{ID}-0"),"function":"package.target.add","exit_code":0,"arguments":[1],"argument_types":["int"],"comparison":comparison}],"blocked":[],"inventory":[callable],"source_sha256":source,"source_preserved":true,"workspace":"/private/retained/workspace","artefact_class":"diagnostic","configuration":{"generation":{"seed":7}},"configuration_sha256":"e".repeat(64)})
}
fn rendered(data: &Value) -> quux_oteleq::reporting::RenderedReport {
    render(&serde_json::to_vec(data).unwrap()).unwrap()
}
#[test]
fn matching_report_retains_identity_scope_and_exact_large_arguments() {
    let data = fixture();
    let bytes = serde_json::to_string(&data).unwrap().replace(
        "\"arguments\":[1]",
        "\"arguments\":[340282366920938463463374607431768211455]",
    );
    let output = render(bytes.as_bytes()).unwrap();
    assert_eq!(output.exit_code, 0);
    for expected in [
        "340282366920938463463374607431768211455",
        "1 paired cases matched",
        "Inventory: 1 callables",
        "diagnostic only; no shipping claim",
        "Source preserved: true",
        "does not rerun or authenticate",
    ] {
        assert!(output.html.contains(expected), "{expected}");
    }
    assert!(output
        .junit
        .contains("tests=\"1\" failures=\"0\" errors=\"0\" skipped=\"0\""));
    assert!(output
        .junit
        .contains("equivalence over these tests and observations"));
}
#[test]
fn mixed_results_keep_blocked_untested_excluded_and_cases_in_denominators() {
    let mut data = fixture();
    let callable = data["inventory"][0].clone();
    for (id, status) in [
        ("11111111111111111111", "blocked"),
        ("22222222222222222222", "excluded"),
        ("33333333333333333333", "ready"),
    ] {
        let mut entry = callable.clone();
        entry["id"] = json!(id);
        entry["status"] = json!(status);
        entry["otelc_function"] = json!(format!("target.{status}"));
        entry["reason"] = json!("needs a receiver fixture");
        if status == "blocked" {
            data["blocked"].as_array_mut().unwrap().push(entry.clone());
        }
        data["inventory"].as_array_mut().unwrap().push(entry);
    }
    data["exit_code"] = json!(3);
    let output = rendered(&data);
    assert_eq!(output.exit_code, 3);
    assert!(output.html.contains("1 paired cases matched; 0 observed differences; 2 incomplete/error entries; 1 excluded callables"));
    assert!(output
        .junit
        .contains("tests=\"4\" failures=\"0\" errors=\"2\" skipped=\"1\""));
    assert!(output.junit.contains("Blocked callable"));
    assert!(output.junit.contains("partial replay"));
}
#[test]
fn stable_difference_is_a_junit_failure_and_incomplete_takes_precedence() {
    let mut data = fixture();
    data["exit_code"] = json!(1);
    let case = &mut data["cases"][0];
    case["exit_code"] = json!(1);
    case["comparison"]["verdict"] = json!("different_observed");
    case["comparison"]["cases"][0]["verdict"] = json!("different_observed");
    case["comparison"]["cases"][0]["differences"] =
        json!([{"path":"state-and-outcome","baseline":[0,255],"instrumented_on":[1,254]}]);
    let output = rendered(&data);
    assert_eq!(output.exit_code, 1);
    assert!(output
        .junit
        .contains("<failure type=\"observed_difference\""));
    assert!(output.html.contains("state-and-outcome"));
    data["source_preserved"] = json!(false);
    assert_eq!(rendered(&data).exit_code, 3);
}
#[test]
fn tool_errors_and_comparator_incompleteness_are_not_skipped_or_passed() {
    let mut data = fixture();
    data["exit_code"] = json!(4);
    data["cases"][0]
        .as_object_mut()
        .unwrap()
        .remove("comparison");
    data["cases"][0]["exit_code"] = json!(4);
    data["cases"][0]["error"] = json!("build failed");
    let output = rendered(&data);
    assert_eq!(output.exit_code, 3);
    assert!(output.junit.contains("<error type=\"incomplete_evidence\""));
    assert!(output.html.contains("build failed"));
    for (verdict, exit_code) in [("inconclusive", 3), ("blocked", 2)] {
        let mut data = fixture();
        data["exit_code"] = json!(exit_code);
        data["cases"][0]["exit_code"] = json!(exit_code);
        data["cases"][0]["comparison"]["verdict"] = json!(verdict);
        data["cases"][0]["comparison"]["cases"][0]["verdict"] = json!(verdict);
        assert_eq!(rendered(&data).exit_code, 3);
    }
}
#[test]
fn zero_cases_or_false_success_status_never_become_a_green_suite() {
    let mut data = fixture();
    data["cases"] = json!([]);
    assert_eq!(rendered(&data).exit_code, 3);
    data["inventory"] = json!([]);
    assert_eq!(rendered(&data).exit_code, 3);
    let mut data = fixture();
    data["exit_code"] = json!(4);
    assert_eq!(rendered(&data).exit_code, 3);
}
#[test]
fn invalid_and_contradictory_reports_are_rejected_before_rendering() {
    let changes = [
        ("schema_version", json!(2)),
        ("claim", json!("all functions proved identical")),
        ("artefact_class", json!("production_workload")),
        ("source_sha256", json!("bad")),
        ("configuration_sha256", json!("bad")),
        ("exit_code", json!(5)),
    ];
    for (field, value) in changes {
        let mut data = fixture();
        data[field] = value;
        assert!(render(&serde_json::to_vec(&data).unwrap()).is_err());
    }
    let mut cases = Vec::new();
    let mut data = fixture();
    data["inventory"][0]["language"] = json!("unknown");
    cases.push(data);
    let mut data = fixture();
    data["inventory"][0]["status"] = json!("skipped");
    cases.push(data);
    let mut data = fixture();
    data["inventory"][0]["id"] = json!("bad");
    cases.push(data);
    let mut data = fixture();
    let duplicate = data["inventory"][0].clone();
    data["inventory"].as_array_mut().unwrap().push(duplicate);
    cases.push(data);
    let mut data = fixture();
    data["cases"][0]["case"] = json!("unknown-0");
    cases.push(data);
    let mut data = fixture();
    data["cases"][0]["case"] = json!("bad");
    cases.push(data);
    let mut data = fixture();
    data["cases"][0]["case"] = json!(format!("{ID}-abc"));
    cases.push(data);
    let mut data = fixture();
    let duplicate = data["cases"][0].clone();
    data["cases"].as_array_mut().unwrap().push(duplicate);
    cases.push(data);
    let mut data = fixture();
    data["cases"][0]["function"] = json!("other");
    cases.push(data);
    let mut data = fixture();
    data["cases"][0]["error"] = json!("error alongside comparison");
    cases.push(data);
    let mut data = fixture();
    data["cases"][0]["exit_code"] = json!(1);
    cases.push(data);
    for field in ["baseline_attempts", "instrumented_attempts"] {
        let mut data = fixture();
        data["cases"][0]["comparison"]["cases"][0][field] = json!(1);
        cases.push(data);
    }
    let mut data = fixture();
    data["cases"][0]["comparison"]["cases"][0]["reasons"] = json!(["gap"]);
    cases.push(data);
    let mut data = fixture();
    data["cases"][0]["comparison"]["cases"] = json!([]);
    cases.push(data);
    let mut data = fixture();
    data["cases"][0]["comparison"]["scope"]["source_sha256"] = json!("b".repeat(64));
    cases.push(data);
    let mut data = fixture();
    data["blocked"] = json!([data["inventory"][0]]);
    cases.push(data);
    let mut data = fixture();
    data["cases"][0]["comparison"]["scope"]["language"] = json!("rust");
    cases.push(data);
    let mut data = fixture();
    data["cases"][0]["comparison"]["scope"]["artefact_class"] = json!("production_workload");
    cases.push(data);
    let mut data = fixture();
    data["cases"][0]["exit_code"] = json!(1);
    data["cases"][0]["comparison"]["verdict"] = json!("different_observed");
    data["cases"][0]["comparison"]["cases"][0]["verdict"] = json!("different_observed");
    cases.push(data);
    for data in cases {
        assert!(
            render(&serde_json::to_vec(&data).unwrap()).is_err(),
            "{data}"
        );
    }
    assert!(render(b"not JSON").is_err());
    assert!(render(&vec![b' '; 16 * 1024 * 1024 + 1]).is_err());
    let duplicate = serde_json::to_string(&fixture()).unwrap().replace(
        "\"schema_version\":1",
        "\"schema_version\":1,\"schema_version\":1",
    );
    assert!(render(duplicate.as_bytes()).is_err());
}
#[test]
fn html_and_xml_escape_application_text_and_make_binary_controls_visible() {
    let mut data = fixture();
    let malicious = "<script>alert('x')</script>&\"\u{0000}\u{ffff}";
    data["inventory"][0]["otelc_function"] = json!(malicious);
    data["cases"][0]["function"] = json!(malicious);
    let output = rendered(&data);
    for text in [&output.html, &output.junit] {
        assert!(!text.contains("<script>"));
        assert!(!text.contains('\0'));
        assert!(text.contains("&lt;script&gt;"));
        assert!(text.contains("&amp;&quot;\\u{0}\\u{ffff}"));
    }
    assert!(output.html.contains("Content-Security-Policy"));
    assert!(!output.html.contains("<script"));
}
#[test]
fn filesystem_and_cli_create_private_new_reports_without_reading_workspace() {
    let base = tempfile::tempdir().unwrap();
    let input = base.path().join("report.json");
    fs::write(&input, serde_json::to_vec(&fixture()).unwrap()).unwrap();
    let output = base.path().join("html");
    assert_eq!(write_report(&input, &output).unwrap(), 0);
    assert!(write_report(&input, &output).is_err());
    assert!(write_report(&base.path().join("missing"), &base.path().join("none")).is_err());
    assert!(!base.path().join("none").exists());
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        assert_eq!(
            fs::metadata(&output).unwrap().permissions().mode() & 0o777,
            0o700
        );
        assert_eq!(
            fs::metadata(output.join("index.html"))
                .unwrap()
                .permissions()
                .mode()
                & 0o777,
            0o600
        );
    }
    let cli = env!("CARGO_BIN_EXE_quux-oteleq");
    assert!(Command::new(cli)
        .args(["render-report", "--help"])
        .status()
        .unwrap()
        .success());
    let new_output = base.path().join("cli");
    assert!(
        Command::new(cli)
            .args(["render-report"])
            .status()
            .unwrap()
            .code()
            == Some(2)
    );
    assert!(Command::new(cli)
        .args([
            "render-report",
            input.to_str().unwrap(),
            "--output-dir",
            new_output.to_str().unwrap()
        ])
        .status()
        .unwrap()
        .success());
    assert_eq!(
        Command::new(cli)
            .args([
                "render-report",
                input.to_str().unwrap(),
                "--output-dir",
                new_output.to_str().unwrap()
            ])
            .status()
            .unwrap()
            .code(),
        Some(4)
    );
    assert_eq!(
        Command::new(cli)
            .args([
                "render-report",
                input.to_str().unwrap(),
                "--bad",
                new_output.to_str().unwrap()
            ])
            .status()
            .unwrap()
            .code(),
        Some(2)
    );
    fs::write(&input, "{}").unwrap();
    assert!(write_report(&input, &base.path().join("invalid")).is_err());
    assert!(!base.path().join("invalid").exists());
}

#[test]
fn all_eight_languages_use_the_same_reporting_contract() {
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
        let mut data = fixture();
        data["inventory"][0]["language"] = json!(language);
        data["cases"][0]["comparison"]["scope"]["language"] = json!(language);
        let output = rendered(&data);
        assert_eq!(output.exit_code, 0);
        assert!(output
            .html
            .contains(&format!("{language}:package/target.py")));
    }
}
