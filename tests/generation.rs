use quux_oteleq::generation::inventory;
use std::{fs, process::Command};

#[test]
fn rust_inventory_keeps_nested_methods_closures_macros_and_generics_as_gaps() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("source.rs");
    fs::write(&path, "static mut STATE:i32=0; fn main(){} fn plain(x:i32)->i32{x} fn nested(){fn main(){} fn inner(){} let _=|x:i32|x;} fn generic<T>(x:T)->T{x} async fn asynchronous(){} unsafe fn dangerous(){} mod outside; mod inside{fn member(){}} struct S; impl S{fn method(&self){} fn main(){}} trait Trait{fn abstracted(&self);fn provided(&self){}} example!();").unwrap();
    let result = inventory(&path).unwrap();
    let entries = result["functions"].as_array().unwrap();
    let mains: Vec<_> = entries.iter().filter(|e| e["name"] == "main").collect();
    assert_eq!(mains.len(), 3);
    assert_eq!(mains[0]["entrypoint"], true);
    assert_eq!(mains[1]["entrypoint"], false);
    assert_eq!(mains[2]["entrypoint"], false);
    assert!(entries.iter().any(|e| e["name"] == "plain"
        && e["reason"] == ""
        && e["parameters"][0] == "i32"
        && e["output"] == "i32"));
    for name in [
        "inner",
        "<closure>",
        "generic",
        "asynchronous",
        "dangerous",
        "outside",
        "member",
        "method",
        "abstracted",
        "provided",
        "example",
    ] {
        assert!(
            entries
                .iter()
                .any(|e| e["name"] == name && e["reason"] != ""),
            "missing gap {name}"
        );
    }
    assert_eq!(result["globals"][0]["name"], "STATE");
    assert_eq!(result["globals"][0]["mutable"], true);
    fs::write(&path, "invalid Rust {{{").unwrap();
    assert!(inventory(&path).is_err());
    assert!(inventory(&dir.path().join("missing")).is_err());
}

#[test]
fn cli_embeds_generation_workers_and_exposes_subcommand_help() {
    let exe = env!("CARGO_BIN_EXE_quux-oteleq");
    let overview = Command::new(exe).arg("--help").output().unwrap();
    assert!(overview.status.success());
    let overview = String::from_utf8(overview.stdout).unwrap();
    assert!(overview.contains("Comparator exits: 0 equivalent"));
    assert!(overview.contains("Generation exits: 0 complete"));
    assert!(overview.contains("4 tool/build/identity error"));
    let help = Command::new(exe).args(["plan", "--help"]).output().unwrap();
    assert!(
        help.status.success(),
        "{}",
        String::from_utf8_lossy(&help.stderr)
    );
    assert!(String::from_utf8_lossy(&help.stdout).contains("--otelc-root"));
    let missing_value = Command::new(exe)
        .args(["plan", "--source"])
        .output()
        .unwrap();
    assert_eq!(missing_value.status.code(), Some(2));
    let missing = Command::new(exe)
        .args([
            "generate",
            "--workspace",
            "/tmp/oteleq-never-existing-workspace",
        ])
        .output()
        .unwrap();
    assert!(!missing.status.success());
    let unsafe_root = Command::new(exe)
        .args(["plan", "--source", "/tmp"])
        .output()
        .unwrap();
    assert!(!unsafe_root.status.success());
    for option in ["--source=/tmp", "--otelc-root=/tmp", "--workspace=/tmp"] {
        let unsafe_root = Command::new(exe).args(["plan", option]).output().unwrap();
        assert_eq!(unsafe_root.status.code(), Some(4));
        assert!(String::from_utf8_lossy(&unsafe_root.stderr)
            .contains("adapter directory must be outside input repositories"));
    }
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("source.rs");
    fs::write(&file, "fn sample(){}").unwrap();
    let result = Command::new(exe)
        .args(["inventory-rust", file.to_str().unwrap()])
        .output()
        .unwrap();
    assert!(result.status.success());
    assert!(String::from_utf8_lossy(&result.stdout).contains("sample"));
}
