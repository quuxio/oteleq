use quux_oteleq::graph::{compare, ComparisonLimit, Encoding, Gap, Node, Snapshot, Value};
use std::collections::BTreeMap;

fn integer(value: impl ToString) -> Value {
    Value::Integer {
        r#type: "python.int".into(),
        value: value.to_string(),
        bits: None,
        signed: true,
    }
}
fn reference(id: &str) -> Value {
    Value::Reference { node_id: id.into() }
}
fn scalar(value: Value) -> Snapshot {
    Snapshot {
        roots: BTreeMap::from([("value".into(), value)]),
        nodes: vec![],
    }
}
fn object(id: &str, value: Value) -> Snapshot {
    Snapshot {
        roots: BTreeMap::from([("receiver".into(), reference(id))]),
        nodes: vec![Node {
            id: id.into(),
            r#type: "example.Counter".into(),
            fields: BTreeMap::from([("calls".into(), value)]),
        }],
    }
}
fn cycle(first: &str, second: &str) -> Snapshot {
    Snapshot {
        roots: BTreeMap::from([
            ("receiver".into(), reference(first)),
            ("alias".into(), reference(second)),
        ]),
        nodes: vec![
            Node {
                id: first.into(),
                r#type: "example.Counter".into(),
                fields: BTreeMap::from([
                    ("calls".into(), integer(3)),
                    ("child".into(), reference(second)),
                ]),
            },
            Node {
                id: second.into(),
                r#type: "example.Child".into(),
                fields: BTreeMap::from([("owner".into(), reference(first))]),
            },
        ],
    }
}
#[test]
fn local_node_labels_and_storage_order_do_not_change_alias_or_cycle_equality() {
    let left = cycle("n1", "n2");
    let mut right = cycle("other-seven", "other-nine");
    right.nodes.reverse();
    assert!(compare(&left, &right).unwrap().equivalent());
    right.nodes[1].fields.insert("calls".into(), integer(4));
    let result = compare(&left, &right).unwrap();
    assert_eq!(result.differences.len(), 1);
    assert!(result.differences[0].path.ends_with("/calls"));
}
#[test]
fn changes_in_aliases_are_differences_even_with_identical_object_fields() {
    let mut shared = object("one", integer(3));
    shared.roots.insert("other".into(), reference("one"));
    let mut split = object("seven", integer(3));
    split.roots.insert("other".into(), reference("nine"));
    split.nodes.push(Node {
        id: "nine".into(),
        r#type: "example.Counter".into(),
        fields: BTreeMap::from([("calls".into(), integer(3))]),
    });
    assert!(compare(&shared, &split)
        .unwrap()
        .differences
        .iter()
        .any(|difference| difference.reason.contains("alias")));
    assert!(compare(&split, &shared)
        .unwrap()
        .differences
        .iter()
        .any(|difference| difference.reason.contains("merged")));
}
#[test]
fn paths_preserve_empty_keys_and_escape_slashes_and_tildes() {
    let mut left = object("n1", integer(4));
    left.nodes[0].fields = BTreeMap::from([("".into(), Value::Null), ("a/b~".into(), integer(4))]);
    let mut right = object("n7", integer(4));
    right.nodes[0].fields = BTreeMap::from([("".into(), Value::Null), ("a/b~".into(), integer(5))]);
    let result = compare(&left, &right).unwrap();
    assert_eq!(result.differences[0].path, "/receiver/a~1b~0");
    assert_eq!(result.differences[0].baseline, Some(integer(4)));
    assert_eq!(result.differences[0].instrumented_on, Some(integer(5)));
    right.nodes[0].fields.remove("");
    assert!(compare(&left, &right)
        .unwrap()
        .differences
        .iter()
        .any(|difference| difference.path == "/receiver/"));
}
#[test]
fn arbitrary_and_fixed_width_integer_contracts_are_lossless_and_bounded() {
    let big = integer("1267650600228229401496703205376");
    assert!(compare(&scalar(big.clone()), &scalar(big))
        .unwrap()
        .equivalent());
    for (value, bits, signed) in [
        (u128::MAX.to_string(), 128, false),
        (i128::MIN.to_string(), 128, true),
        ("255".into(), 8, false),
        ("-128".into(), 8, true),
    ] {
        let snapshot = scalar(Value::Integer {
            r#type: "native.integer".into(),
            value,
            bits: Some(bits),
            signed,
        });
        assert!(compare(&snapshot, &snapshot).unwrap().equivalent());
    }
    for (value, bits, signed) in [
        ("256", Some(8), false),
        ("128", Some(8), true),
        ("-129", Some(8), true),
        ("-1", None, false),
        ("1", Some(7), true),
        ("-0", None, true),
        ("01", None, true),
        ("+1", None, true),
        ("1e3", None, true),
        ("", None, true),
    ] {
        let snapshot = scalar(Value::Integer {
            r#type: "native.integer".into(),
            value: value.into(),
            bits,
            signed,
        });
        assert!(compare(&snapshot, &snapshot).is_err(), "{snapshot:?}");
    }
}
#[test]
fn float_bits_preserve_signed_zero_and_nan_payloads_without_float_parsing() {
    let value = |bits: &str| {
        scalar(Value::Float {
            r#type: "ieee754.binary64".into(),
            bits: bits.into(),
        })
    };
    assert!(
        !compare(&value("0000000000000000"), &value("8000000000000000"))
            .unwrap()
            .equivalent()
    );
    assert!(
        !compare(&value("7ff8000000000001"), &value("7ff8000000000002"))
            .unwrap()
            .equivalent()
    );
    for bits in [
        "0000",
        "80000000",
        "7ff8000000000001",
        "00000000000000000000000000000000",
    ] {
        assert!(compare(&value(bits), &value(bits)).unwrap().equivalent());
    }
    for bits in ["", "0", "NaN", "0x00000000", "ABCDEF00"] {
        assert!(compare(&value(bits), &value(bits)).is_err());
    }
}
#[test]
fn string_encodings_keep_surrogates_nuls_and_raw_non_utf8_bytes_distinct() {
    let value = |encoding, text: &str| {
        scalar(Value::String {
            r#type: "runtime.string".into(),
            encoding,
            value: text.into(),
        })
    };
    for (encoding, text) in [
        (Encoding::Utf8, "c3a900"),
        (Encoding::Utf16Be, "00e90000d83dde00d800"),
        (Encoding::Codepoints32Be, "0001f6000000d800"),
        (Encoding::RawBytes, "ff000a"),
    ] {
        let snapshot = value(encoding, text);
        assert!(compare(&snapshot, &snapshot).unwrap().equivalent());
    }
    assert!(!compare(
        &value(Encoding::Utf16Be, "d800"),
        &value(Encoding::Utf16Be, "d801")
    )
    .unwrap()
    .equivalent());
    for (encoding, text) in [
        (Encoding::Utf8, "ff"),
        (Encoding::Utf16Be, "00"),
        (Encoding::Codepoints32Be, "00110000"),
        (Encoding::Codepoints32Be, "0000"),
        (Encoding::RawBytes, "xz"),
    ] {
        let snapshot = value(encoding, text);
        assert!(compare(&snapshot, &snapshot).is_err());
    }
}
#[test]
fn all_typed_tags_are_observable_and_opaque_state_never_qualifies() {
    for value in [
        Value::Null,
        Value::Undefined,
        Value::Unbound,
        Value::Boolean { value: true },
        Value::Unit {
            r#type: "rust.()".into(),
        },
        Value::Bytes {
            r#type: "bytes".into(),
            hex: "00ff0a".into(),
        },
    ] {
        let snapshot = scalar(value);
        assert!(compare(&snapshot, &snapshot).unwrap().equivalent());
    }
    assert!(!compare(&scalar(Value::Null), &scalar(Value::Undefined))
        .unwrap()
        .equivalent());
    let opaque = Value::Opaque {
        r#type: "DatabaseHandle".into(),
        reason: "provide an observer fixture".into(),
    };
    let left = object("n1", opaque.clone());
    let mut right = object("n7", opaque);
    right.nodes[0].r#type = "different.Type".into();
    let result = compare(&left, &right).unwrap();
    assert!(!result.equivalent());
    assert_eq!(result.gaps.len(), 2);
    assert!(result.gaps[0]
        .description()
        .contains("provide an observer fixture"));
    right.nodes[0].fields.clear();
    assert!(!compare(&left, &right).unwrap().gaps.is_empty());
}
#[test]
fn unknown_duplicate_dangling_and_unreachable_graph_records_are_rejected() {
    let valid = object("n1", integer(3));
    let mut bad = valid.clone();
    bad.nodes.push(bad.nodes[0].clone());
    assert!(compare(&bad, &valid).is_err());
    let mut bad = valid.clone();
    bad.roots.insert("unknown".into(), reference("missing"));
    assert!(compare(&bad, &valid).is_err());
    let mut bad = valid.clone();
    bad.roots.clear();
    assert!(compare(&bad, &valid).is_err());
    let mut bad = valid.clone();
    bad.nodes[0].id.clear();
    assert!(compare(&bad, &valid).is_err());
    let mut bad = valid.clone();
    bad.roots.insert("".into(), Value::Null);
    assert!(compare(&bad, &valid).is_err());
    let duplicate = r#"{"roots":{"a":{"kind":"null"},"a":{"kind":"null"}},"nodes":[]}"#;
    assert!(serde_json::from_str::<Snapshot>(duplicate).is_err());
    let unknown = r#"{"roots":{"a":{"kind":"future_value"}},"nodes":[]}"#;
    assert!(serde_json::from_str::<Snapshot>(unknown).is_err());
}
#[test]
fn bounded_graph_and_difference_limits_cannot_produce_a_truncated_pass() {
    let mut left = object("n1", integer(0));
    let mut right = object("n7", integer(0));
    for index in 0..150 {
        left.nodes[0]
            .fields
            .insert(format!("field{index}"), integer(1));
        right.nodes[0]
            .fields
            .insert(format!("field{index}"), integer(2));
    }
    let result = compare(&left, &right).unwrap();
    assert_eq!(result.differences.len(), 128);
    assert!(!result.gaps.is_empty());
    let oversized = scalar(Value::Bytes {
        r#type: "bytes".into(),
        hex: "00".repeat(150000),
    });
    assert!(compare(&oversized, &oversized).is_err());
    let mut deep = Snapshot {
        roots: BTreeMap::from([("root".into(), reference("n0"))]),
        nodes: vec![],
    };
    for index in 0..35 {
        deep.nodes.push(Node {
            id: format!("n{index}"),
            r#type: "node".into(),
            fields: BTreeMap::from([(
                "child".into(),
                if index == 34 {
                    Value::Null
                } else {
                    reference(&format!("n{}", index + 1))
                },
            )]),
        });
    }
    assert!(compare(&deep, &deep).is_err());
    let too_many = Snapshot {
        roots: BTreeMap::new(),
        nodes: (0..513)
            .map(|index| Node {
                id: index.to_string(),
                r#type: "node".into(),
                fields: BTreeMap::new(),
            })
            .collect(),
    };
    assert!(compare(&too_many, &too_many).is_err());
}

fn deep_fanout(value: Value) -> Snapshot {
    let mut snapshot = Snapshot {
        roots: BTreeMap::from([("root".into(), reference("n0"))]),
        nodes: vec![],
    };
    for index in 0..32 {
        snapshot.nodes.push(Node {
            id: format!("n{index}"),
            r#type: "node".into(),
            fields: if index == 31 {
                (0..512)
                    .map(|field| (format!("f{field}"), value.clone()))
                    .collect()
            } else {
                BTreeMap::from([("x".repeat(1024), reference(&format!("n{}", index + 1)))])
            },
        });
    }
    snapshot
}

#[test]
fn long_paths_respect_diagnostic_payload_and_record_budgets() {
    let opaque = deep_fanout(Value::Opaque {
        r#type: "handle".into(),
        reason: "unknown".into(),
    });
    let result = compare(&opaque, &opaque).unwrap();
    let payload: usize = result.gaps.iter().map(|gap| gap.description().len()).sum();
    eprintln!(
        "opaque input bytes={}, gap records={}, diagnostic bytes={payload}",
        serde_json::to_vec(&opaque).unwrap().len(),
        result.gaps.len()
    );
    assert!(!result.equivalent());
    assert!(payload <= 2 * (262144 + 1024));
    assert!(result.gaps.len() <= 258);
    let result = compare(&deep_fanout(integer(1)), &deep_fanout(integer(2))).unwrap();
    let payload: usize = result
        .differences
        .iter()
        .map(|difference| difference.path.len())
        .sum();
    assert!(!result.equivalent());
    assert!(payload <= 262144);
    assert!(!result.gaps.is_empty());
    let flat = Snapshot {
        roots: (0..150)
            .map(|index| {
                (
                    index.to_string(),
                    Value::Opaque {
                        r#type: "handle".into(),
                        reason: "unknown".into(),
                    },
                )
            })
            .collect(),
        nodes: vec![],
    };
    let result = compare(&flat, &flat).unwrap();
    assert_eq!(result.gaps.len(), 258);
    assert_eq!(
        result
            .gaps
            .iter()
            .filter(|gap| matches!(
                gap,
                Gap::Limit {
                    limit: ComparisonLimit::Diagnostics,
                    ..
                }
            ))
            .count(),
        2
    );
    assert!(!result.equivalent());
}
