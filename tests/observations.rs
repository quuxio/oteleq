use quux_oteleq::{
    graph::{Node, Snapshot, Value},
    observation::{
        compare, CaptureGap, Contract, ErrorCategory, ExpectedOutcome, Fixture, Observation,
        Outcome, Phase,
    },
    Verdict,
};
use std::collections::BTreeMap;

fn integer(value: i32) -> Value {
    Value::Integer {
        r#type: "python.int".into(),
        value: value.to_string(),
        bits: None,
        signed: true,
    }
}
fn snapshot(id: &str, calls: i32) -> Snapshot {
    Snapshot {
        roots: BTreeMap::from([("receiver".into(), Value::Reference { node_id: id.into() })]),
        nodes: vec![Node {
            id: id.into(),
            r#type: "Counter".into(),
            fields: BTreeMap::from([("calls".into(), integer(calls))]),
        }],
    }
}
fn contract() -> Contract {
    Contract {
        observation_schema_version: 1,
        case_id: "counter-case".into(),
        function_id: "example.Counter.increment".into(),
        fixture_sha256: "f".repeat(64),
        required_roots: vec!["receiver".into()],
        expected_baseline: ExpectedOutcome::Return,
        steps: vec![],
    }
}
fn observation(id: &str) -> Observation {
    let mut returned = snapshot(id, 4);
    returned.roots.insert("result".into(), integer(4));
    Observation {
        observation_schema_version: 1,
        case_id: "counter-case".into(),
        function_id: "example.Counter.increment".into(),
        fixture_sha256: "f".repeat(64),
        fixture: Fixture::Ready,
        gaps: vec![],
        before: snapshot(id, 3),
        outcome: Outcome::Return { graph: returned },
        after: snapshot(id, 4),
        steps: vec![],
    }
}
fn thrown(observation: &mut Observation, category: ErrorCategory, type_name: &str) {
    let mut error = observation.after.clone();
    error.roots.insert(
        "error".into(),
        Value::Reference {
            node_id: "exception".into(),
        },
    );
    error.nodes.push(Node {
        id: "exception".into(),
        r#type: type_name.into(),
        fields: BTreeMap::new(),
    });
    observation.outcome = Outcome::Error {
        category,
        graph: error,
    };
}
#[test]
fn equivalent_values_aliases_and_cycles_are_independent_of_node_labels() {
    let result = compare(&observation("n1"), &observation("n7"), &contract()).unwrap();
    assert_eq!(result.verdict, Verdict::EquivalentObserved);
    assert!(result.initial_differences.is_empty());
    assert!(result.differences.is_empty());
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
        let mut specification = contract();
        specification.function_id = format!("{language}:Counter.increment");
        let mut left = observation("first");
        left.function_id = specification.function_id.clone();
        let mut right = observation("second");
        right.function_id = specification.function_id.clone();
        assert_eq!(
            compare(&left, &right, &specification).unwrap().verdict,
            Verdict::EquivalentObserved
        );
    }
}
#[test]
fn same_return_with_different_receiver_fields_has_a_precise_after_path() {
    let left = observation("n1");
    let mut right = observation("n7");
    right.after.nodes[0]
        .fields
        .insert("calls".into(), integer(5));
    let Outcome::Return { graph } = &mut right.outcome else {
        unreachable!()
    };
    graph.nodes[0].fields.insert("calls".into(), integer(5));
    let result = compare(&left, &right, &contract()).unwrap();
    assert_eq!(result.verdict, Verdict::DifferentObserved);
    assert!(result
        .differences
        .iter()
        .any(|difference| difference.path == "/after/receiver/calls"));
    assert!(result
        .differences
        .iter()
        .all(|difference| !difference.path.ends_with("result")));
}
#[test]
fn unequal_initial_fixtures_are_invalid_even_when_return_and_final_state_match() {
    let left = observation("n1");
    let mut right = observation("n7");
    right.before.nodes[0]
        .fields
        .insert("calls".into(), integer(9));
    let result = compare(&left, &right, &contract()).unwrap();
    assert_eq!(result.verdict, Verdict::Blocked);
    assert_eq!(result.initial_differences[0].path, "/before/receiver/calls");
    assert!(result.differences.is_empty());
}
#[test]
fn matching_unexpected_errors_are_invalid_and_declared_errors_can_qualify() {
    let mut left = observation("n1");
    let mut right = observation("n7");
    thrown(&mut left, ErrorCategory::Exception, "builtins.ValueError");
    thrown(&mut right, ErrorCategory::Exception, "builtins.ValueError");
    assert_eq!(
        compare(&left, &right, &contract()).unwrap().verdict,
        Verdict::Blocked
    );
    let mut specification = contract();
    specification.expected_baseline = ExpectedOutcome::Error {
        category: ErrorCategory::Exception,
        r#type: "builtins.ValueError".into(),
    };
    assert_eq!(
        compare(&left, &right, &specification).unwrap().verdict,
        Verdict::EquivalentObserved
    );
    specification.expected_baseline = ExpectedOutcome::Error {
        category: ErrorCategory::Panic,
        r#type: "builtins.ValueError".into(),
    };
    assert_eq!(
        compare(&left, &right, &specification).unwrap().verdict,
        Verdict::Blocked
    );
    for observed in [&mut left, &mut right] {
        let mut graph = observed.after.clone();
        graph.roots.insert(
            "error".into(),
            Value::Boolean {
                r#type: Some("go.main.Flag".into()),
                value: true,
            },
        );
        observed.outcome = Outcome::Error {
            category: ErrorCategory::Panic,
            graph,
        };
    }
    for (label, verdict) in [
        ("go.main.Flag", Verdict::EquivalentObserved),
        ("go.bool", Verdict::Blocked),
    ] {
        specification.expected_baseline = ExpectedOutcome::Error {
            category: ErrorCategory::Panic,
            r#type: label.into(),
        };
        assert_eq!(
            compare(&left, &right, &specification).unwrap().verdict,
            verdict
        );
    }
}
#[test]
fn instrumentation_introducing_an_exception_is_a_difference_with_a_valid_baseline() {
    let left = observation("n1");
    let mut right = observation("n7");
    thrown(
        &mut right,
        ErrorCategory::Exception,
        "builtins.RuntimeError",
    );
    let result = compare(&left, &right, &contract()).unwrap();
    assert_eq!(result.verdict, Verdict::DifferentObserved);
    assert!(result
        .differences
        .iter()
        .any(|difference| difference.path == "/outcome"));
}
#[test]
fn root_gaps_opaque_fields_and_explicit_capture_failures_never_pass() {
    let left = observation("n1");
    let mut right = observation("n7");
    right.after.roots.clear();
    right.after.nodes.clear();
    assert_eq!(
        compare(&left, &right, &contract()).unwrap().verdict,
        Verdict::Inconclusive
    );
    let mut right = observation("n7");
    right.gaps.push(CaptureGap {
        phase: Phase::After,
        path: "/receiver".into(),
        reason: "requested cleanup capture missing".into(),
    });
    assert_eq!(
        compare(&left, &right, &contract()).unwrap().verdict,
        Verdict::Inconclusive
    );
    let mut right = observation("n7");
    right.after.nodes[0].fields.insert(
        "handle".into(),
        Value::Opaque {
            r#type: "Database".into(),
            reason: "observer required".into(),
        },
    );
    assert_eq!(
        compare(&left, &right, &contract()).unwrap().verdict,
        Verdict::Inconclusive
    );
}
#[test]
fn case_function_fixture_mismatches_and_invalid_construction_are_blocked() {
    let left = observation("n1");
    for field in ["case", "function", "fixture"] {
        let mut right = observation("n7");
        match field {
            "case" => right.case_id = "other".into(),
            "function" => right.function_id = "other".into(),
            _ => right.fixture_sha256 = "a".repeat(64),
        }
        assert_eq!(
            compare(&left, &right, &contract()).unwrap().verdict,
            Verdict::Blocked
        );
    }
    let mut invalid = observation("n1");
    invalid.fixture = Fixture::Invalid {
        reason: "factory failed".into(),
    };
    invalid.outcome = Outcome::NotRun {
        reason: "factory failed".into(),
    };
    assert_eq!(
        compare(&invalid, &invalid, &contract()).unwrap().verdict,
        Verdict::Blocked
    );
    let mut malformed = observation("n1");
    malformed.outcome = Outcome::NotRun {
        reason: "none".into(),
    };
    assert!(compare(&malformed, &malformed, &contract()).is_err());
}
#[test]
fn malformed_contracts_versions_and_graph_payloads_are_protocol_failures() {
    let left = observation("n1");
    let mut bad = contract();
    bad.observation_schema_version = 2;
    assert!(compare(&left, &left, &bad).is_err());
    let mut bad = contract();
    bad.required_roots.push("receiver".into());
    assert!(bad.validate().is_err());
    let mut bad = contract();
    bad.required_roots.push("result".into());
    assert!(bad.validate().is_err());
    let mut bad = contract();
    bad.fixture_sha256 = "not a hash".into();
    assert!(bad.validate().is_err());
    let mut bad = observation("n1");
    bad.observation_schema_version = 2;
    assert!(compare(&left, &bad, &contract()).is_err());
    let mut bad = observation("n1");
    bad.after.nodes.clear();
    assert!(compare(&left, &bad, &contract()).is_err());
    let mut bad = observation("n1");
    bad.gaps.push(CaptureGap {
        phase: Phase::Before,
        path: "/receiver".into(),
        reason: String::new(),
    });
    assert!(compare(&left, &bad, &contract()).is_err());
}

#[test]
fn missing_initial_capture_is_incomplete_not_evidence_of_unequal_fixtures() {
    let left = observation("n1");
    let mut right = observation("n7");
    right.before.roots.clear();
    right.before.nodes.clear();
    assert_eq!(
        compare(&left, &right, &contract()).unwrap().verdict,
        Verdict::Inconclusive
    );
    let mut left = observation("n1");
    let mut right = observation("n7");
    thrown(&mut left, ErrorCategory::Exception, "ExpectedError");
    thrown(&mut right, ErrorCategory::Exception, "ExpectedError");
    let Outcome::Error { graph, .. } = &mut left.outcome else {
        unreachable!()
    };
    graph.roots.remove("error");
    graph.nodes.retain(|node| node.id != "exception");
    let mut specification = contract();
    specification.expected_baseline = ExpectedOutcome::Error {
        category: ErrorCategory::Exception,
        r#type: "ExpectedError".into(),
    };
    assert_eq!(
        compare(&left, &right, &specification).unwrap().verdict,
        Verdict::Inconclusive
    );
}
