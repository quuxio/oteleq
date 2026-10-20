use quux_oteleq::{typed, Verdict};
use serde_json::{json, Value};
use std::{fs, process::Command};

fn fixture() -> Value {
    let hash = "a".repeat(64);
    let integer = json!({"kind":"integer","type":"i32","value":"4","bits":32,"signed":true});
    let state = json!({"roots":{"receiver":{"kind":"reference","node_id":"local"}},
        "nodes":[{"id":"local","type":"Counter","fields":{"calls":integer}}]});
    let mut outcome = state.clone();
    outcome["roots"]["result"] = integer;
    let attempt = json!({"execution":{"source_sha256_before":hash,"source_sha256_after":hash,
        "termination":{"kind":"exit","code":0},"channels":{"stdout":[255,0],"stderr":[]},
        "capture_complete":true,"witness":null},
        "observation":{"observation_schema_version":1,"case_id":"counter","function_id":"Counter.increment",
        "fixture_sha256":hash,"fixture":{"status":"ready"},"gaps":[],"before":state,"after":state,
        "outcome":{"kind":"return","graph":outcome}}});
    let mut on = attempt.clone();
    on["execution"]["witness"] = json!({"decoder":"fixture-decoder","raw_otlp_sha256":hash,
        "functions":{"Counter.increment":1},"spans":1,"losses":{"export":0},"pending":0});
    json!({"typed_schema_version":1,"scope":{"language":"python","artefact_class":"diagnostic",
        "source_sha256":hash,"baseline_artefact_sha256":hash,"instrumented_artefact_sha256":hash,
        "policy_sha256":hash,"observer":"explicit test codec","channels":["stdout","stderr"],"gaps":["unrequested filesystem"]},
        "cases":[{"contract":{"observation_schema_version":1,"case_id":"counter","function_id":"Counter.increment",
        "fixture_sha256":hash,"required_roots":["receiver"],"expected_baseline":{"kind":"return"}},
        "corpus_sha256":hash,"expected_functions":{"Counter.increment":1},"expected_spans":1,
        "baseline":[attempt.clone(),attempt],"instrumented_on":[on.clone(),on]}]})
}
fn evaluate(value: Value) -> typed::Report {
    typed::compare(serde_json::from_value(value).unwrap()).unwrap()
}
fn sequence_fixture() -> Value {
    let mut data = fixture();
    let steps = json!([
        {"id":"first","action":"call","required_roots":["receiver"],"expected_baseline":{"kind":"return"}},
        {"id":"second","action":"call","required_roots":["receiver"],"expected_baseline":{"kind":"return"}}
    ]);
    data["cases"][0]["contract"]["steps"] = steps;
    for lane in ["baseline", "instrumented_on"] {
        for attempt in data["cases"][0][lane].as_array_mut().unwrap() {
            let observed = &mut attempt["observation"];
            observed["steps"] = json!(["first", "second"].map(|id| json!({
                "id":id,"action":"call","gaps":[],"before":observed["before"],
                "outcome":observed["outcome"],"after":observed["after"]
            })));
        }
    }
    data
}

#[test]
fn ordered_steps_detect_transient_state_changes_and_later_initial_differences() {
    let data = sequence_fixture();
    assert_eq!(evaluate(data.clone()).verdict, Verdict::EquivalentObserved);
    let mut altered = data;
    for attempt in altered["cases"][0]["instrumented_on"]
        .as_array_mut()
        .unwrap()
    {
        attempt["observation"]["steps"][0]["after"]["nodes"][0]["fields"]["calls"]["value"] =
            json!("5");
        attempt["observation"]["steps"][1]["before"]["nodes"][0]["fields"]["calls"]["value"] =
            json!("5");
    }
    let compared = evaluate(altered);
    assert_eq!(compared.verdict, Verdict::DifferentObserved);
    let differences = &compared.cases[0].pairs[0].comparison.differences;
    assert!(differences
        .iter()
        .any(|item| item.path == "/steps/first/after/receiver/calls"));
    assert!(differences
        .iter()
        .any(|item| item.path == "/steps/second/before/receiver/calls"));
    assert!(compared.cases[0].pairs[0]
        .comparison
        .initial_differences
        .is_empty());
}

#[test]
fn requested_steps_cannot_be_omitted_reordered_or_silently_added() {
    for lane in ["baseline", "instrumented_on"] {
        for mode in [
            "missing",
            "reordered",
            "extra",
            "kind",
            "missing-root",
            "collection-gap",
        ] {
            let mut data = sequence_fixture();
            for attempt in data["cases"][0][lane].as_array_mut().unwrap() {
                let steps = attempt["observation"]["steps"].as_array_mut().unwrap();
                match mode {
                    "missing" => steps.clear(),
                    "reordered" => steps.swap(0, 1),
                    "extra" => {
                        let mut item = steps[0].clone();
                        item["id"] = json!("extra");
                        steps.push(item);
                    }
                    "kind" => steps[0]["action"] = json!("collect"),
                    "missing-root" => steps[0]["before"] = json!({"roots":{},"nodes":[]}),
                    "collection-gap" => {
                        steps[0]["gaps"] = json!([{"phase":"after","path":"/collection","reason":"not observed within the declared bound"}])
                    }
                    _ => unreachable!(),
                }
            }
            assert_eq!(
                evaluate(data).verdict,
                Verdict::Inconclusive,
                "{lane} {mode}"
            );
        }
    }
}

#[test]
fn step_only_repeat_instability_is_inconclusive() {
    let mut data = sequence_fixture();
    data["cases"][0]["instrumented_on"][1]["observation"]["steps"][0]["after"]["nodes"][0]
        ["fields"]["calls"]["value"] = json!("6");
    assert_eq!(evaluate(data).verdict, Verdict::Inconclusive);
}

#[test]
fn intermediate_unexpected_baseline_errors_block_even_when_the_final_call_returns() {
    let mut data = sequence_fixture();
    for lane in ["baseline", "instrumented_on"] {
        for attempt in data["cases"][0][lane].as_array_mut().unwrap() {
            let step = &mut attempt["observation"]["steps"][0];
            let mut graph = step["after"].clone();
            graph["roots"]["error"] = json!({"kind":"reference","node_id":"error"});
            graph["nodes"]
                .as_array_mut()
                .unwrap()
                .push(json!({"id":"error","type":"RuntimeError","fields":{}}));
            step["outcome"] = json!({"kind":"error","category":"exception","graph":graph});
        }
    }
    assert_eq!(evaluate(data.clone()).verdict, Verdict::Blocked);
    data["cases"][0]["contract"]["steps"][0]["expected_baseline"] =
        json!({"kind":"error","category":"exception","type":"RuntimeError"});
    assert_eq!(evaluate(data).verdict, Verdict::EquivalentObserved);
}

#[test]
fn sequence_metadata_and_extra_malformed_graphs_refuse_the_protocol() {
    for mode in [
        "duplicate-contract",
        "duplicate-observation",
        "too-many-contracts",
        "too-many-observations",
        "bad-extra-graph",
        "release-error",
    ] {
        let mut data = sequence_fixture();
        let case = &mut data["cases"][0];
        match mode {
            "duplicate-contract" => case["contract"]["steps"][1]["id"] = json!("first"),
            "duplicate-observation" => {
                case["baseline"][0]["observation"]["steps"][1]["id"] = json!("first")
            }
            "too-many-contracts" => {
                case["contract"]["steps"] = json!(vec![case["contract"]["steps"][0].clone(); 33])
            }
            "too-many-observations" => {
                case["baseline"][0]["observation"]["steps"] =
                    json!(vec![
                        case["baseline"][0]["observation"]["steps"][0].clone();
                        33
                    ])
            }
            "bad-extra-graph" => {
                let mut step = case["baseline"][0]["observation"]["steps"][0].clone();
                step["id"] = json!("extra");
                step["before"]["roots"]["receiver"]["node_id"] = json!("orphan");
                case["baseline"][0]["observation"]["steps"]
                    .as_array_mut()
                    .unwrap()
                    .push(step);
            }
            "release-error" => {
                case["contract"]["steps"][0]["action"] = json!("release");
                case["contract"]["steps"][0]["expected_baseline"] =
                    json!({"kind":"error","category":"exception","type":"RuntimeError"});
            }
            _ => unreachable!(),
        }
        assert!(
            typed::compare(serde_json::from_value(data).unwrap()).is_err(),
            "{mode}"
        );
    }
}
fn throw(attempt: &mut Value) {
    let mut graph = attempt["observation"]["after"].clone();
    graph["roots"]["error"] = json!({"kind":"reference","node_id":"error"});
    graph["nodes"]
        .as_array_mut()
        .unwrap()
        .push(json!({"id":"error","type":"RuntimeError","fields":{}}));
    attempt["observation"]["outcome"] =
        json!({"kind":"error","category":"exception","graph":graph});
}
#[test]
fn common_protocol_handles_all_language_ids_and_retains_declared_scope() {
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
        data["scope"]["language"] = json!(language);
        let report = evaluate(data);
        assert_eq!(report.verdict, Verdict::EquivalentObserved);
        assert_eq!(report.cases[0].pairs.len(), 3);
        assert_eq!(report.scope.gaps, ["unrequested filesystem"]);
        assert_eq!(
            report.claim,
            "equivalence over these tests and observations"
        );
    }
}
#[test]
fn fields_have_typed_paths_and_stable_introduced_errors_remain_differences() {
    let mut data = fixture();
    for attempt in data["cases"][0]["instrumented_on"].as_array_mut().unwrap() {
        attempt["observation"]["after"]["nodes"][0]["fields"]["calls"]["value"] = json!("5");
    }
    let report = evaluate(data);
    assert_eq!(report.verdict, Verdict::DifferentObserved);
    assert_eq!(
        report.cases[0].pairs[0].comparison.differences[0].path,
        "/after/receiver/calls"
    );
    let mut data = fixture();
    for attempt in data["cases"][0]["instrumented_on"].as_array_mut().unwrap() {
        throw(attempt);
    }
    assert_eq!(evaluate(data.clone()).verdict, Verdict::DifferentObserved);
    for attempt in data["cases"][0]["baseline"].as_array_mut().unwrap() {
        throw(attempt);
    }
    assert_eq!(evaluate(data.clone()).verdict, Verdict::Blocked);
    data["cases"][0]["contract"]["expected_baseline"] =
        json!({"kind":"error","category":"exception","type":"RuntimeError"});
    assert_eq!(evaluate(data).verdict, Verdict::EquivalentObserved);
}
#[test]
fn each_attempt_has_identity_fixture_completeness_and_repeat_checks() {
    for lane in ["baseline", "instrumented_on"] {
        let mut data = fixture();
        data["cases"][0][lane][1]["observation"]["after"]["nodes"][0]["fields"]["calls"]["value"] =
            json!("5");
        let report = evaluate(data);
        assert_eq!(report.verdict, Verdict::Inconclusive);
        assert!(report.cases[0]
            .reasons
            .iter()
            .any(|r| r.contains("unstable")));
        for field in ["case_id", "function_id", "fixture_sha256"] {
            let mut data = fixture();
            data["cases"][0][lane][1]["observation"][field] = json!(if field == "fixture_sha256" {
                "b".repeat(64)
            } else {
                "wrong".into()
            });
            assert_eq!(evaluate(data).verdict, Verdict::Blocked);
        }
    }
    let mut data = fixture();
    for attempt in data["cases"][0]["instrumented_on"].as_array_mut().unwrap() {
        attempt["observation"]["before"]["nodes"][0]["fields"]["calls"]["value"] = json!("7");
    }
    assert_eq!(evaluate(data).verdict, Verdict::Blocked);
}
#[test]
fn opaque_gaps_and_missing_roots_cannot_produce_a_pass() {
    for replacement in [
        json!({"kind":"opaque","type":"Handle","reason":"unsupported"}),
        json!({"kind":"unbound"}),
    ] {
        let mut data = fixture();
        data["cases"][0]["instrumented_on"][1]["observation"]["after"]["nodes"][0]["fields"]
            ["calls"] = replacement;
        assert_eq!(evaluate(data).verdict, Verdict::Inconclusive);
    }
    for phase in ["before", "after"] {
        let mut data = fixture();
        data["cases"][0]["instrumented_on"][1]["observation"][phase] =
            json!({"roots":{},"nodes":[]});
        assert_eq!(evaluate(data).verdict, Verdict::Inconclusive);
    }
    let mut data = fixture();
    data["cases"][0]["instrumented_on"][0]["observation"]["gaps"] =
        json!([{"phase":"after","path":"/receiver","reason":"capture failed"}]);
    assert_eq!(evaluate(data).verdict, Verdict::Inconclusive);
}
#[test]
fn byte_channels_termination_source_and_decoded_witness_checks_still_apply() {
    for (field, value, expected) in [
        (
            "source_sha256_after",
            json!("b".repeat(64)),
            Verdict::Blocked,
        ),
        ("capture_complete", json!(false), Verdict::Inconclusive),
        ("witness", json!(null), Verdict::Inconclusive),
        (
            "termination",
            json!({"kind":"signal","number":11}),
            Verdict::Inconclusive,
        ),
    ] {
        let mut data = fixture();
        data["cases"][0]["instrumented_on"][0]["execution"][field] = value;
        assert_eq!(evaluate(data).verdict, expected);
    }
    let mut data = fixture();
    for attempt in data["cases"][0]["instrumented_on"].as_array_mut().unwrap() {
        attempt["execution"]["channels"]["stdout"] = json!([1]);
    }
    assert_eq!(evaluate(data).verdict, Verdict::DifferentObserved);
}
#[test]
fn no_attempt_or_case_and_malformed_or_unbound_protocols_are_never_success() {
    for lane in ["baseline", "instrumented_on"] {
        let mut data = fixture();
        data["cases"][0][lane] = json!([]);
        assert_eq!(evaluate(data).verdict, Verdict::Inconclusive);
    }
    let mut data = fixture();
    data["cases"][0]["baseline"] = json!([]);
    data["cases"][0]["instrumented_on"][1]["observation"]["observation_schema_version"] = json!(2);
    assert!(typed::compare(serde_json::from_value(data).unwrap()).is_err());
    for (path, value) in [
        (vec!["typed_schema_version"], json!(2)),
        (vec!["cases"], json!([])),
        (vec!["cases", "0", "expected_functions"], json!({"other":1})),
    ] {
        let mut data = fixture();
        let mut current = &mut data;
        for part in path {
            current = if part == "0" {
                &mut current[0]
            } else {
                &mut current[part]
            };
        }
        *current = value;
        assert!(typed::compare(serde_json::from_value(data).unwrap()).is_err());
    }
    let mut data = fixture();
    data["unexpected"] = json!(true);
    assert!(serde_json::from_value::<typed::Bundle>(data).is_err());
    let encoded = serde_json::to_string(&fixture()).unwrap().replace(
        "\"receiver\":{",
        "\"receiver\":{\"kind\":\"null\"},\"receiver\":{",
    );
    assert!(serde_json::from_str::<typed::Bundle>(&encoded).is_err());
}
#[test]
fn actual_cli_reports_comparison_and_protocol_failures() {
    let folder = std::env::temp_dir().join(format!("oteleq-typed-cli-{}", std::process::id()));
    fs::create_dir(&folder).unwrap();
    let input = folder.join("bundle.json");
    for (data, code) in [
        (fixture(), 0),
        (
            {
                let mut f = fixture();
                f["typed_schema_version"] = json!(2);
                f
            },
            2,
        ),
    ] {
        fs::write(&input, serde_json::to_vec(&data).unwrap()).unwrap();
        let result = Command::new(env!("CARGO_BIN_EXE_quux-oteleq"))
            .args(["compare-observations", input.to_str().unwrap()])
            .output()
            .unwrap();
        assert_eq!(result.status.code(), Some(code));
        if code == 0 {
            assert_eq!(
                serde_json::from_slice::<Value>(&result.stdout).unwrap()["verdict"],
                "equivalent_observed"
            );
        }
    }
    fs::write(&input, b"{}").unwrap();
    assert_eq!(
        Command::new(env!("CARGO_BIN_EXE_quux-oteleq"))
            .args(["compare-observations", input.to_str().unwrap()])
            .output()
            .unwrap()
            .status
            .code(),
        Some(4)
    );
    fs::remove_dir_all(&folder).unwrap();
}

#[test]
fn documented_acceptance_example_is_an_observed_difference() {
    let bundle: typed::Bundle =
        serde_json::from_str(include_str!("../examples/typed-observations.json")).unwrap();
    let report = typed::compare(bundle).unwrap();
    assert_eq!(report.verdict, Verdict::DifferentObserved);
    assert_eq!(
        report.cases[0].pairs[0].comparison.differences[0].path,
        "/after/receiver/calls"
    );
}
