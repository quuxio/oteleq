use quux_oteleq::generation::inventory;
use std::{fs, process::Command};

#[test]
fn rust_inventory_keeps_nested_methods_closures_macros_and_generics_as_gaps() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("source.rs");
    fs::write(&path, "static mut STATE:i32=0; fn main(){} fn plain(x:i32)->i32{x} fn nested(){fn inner(){} let _=|x:i32|x;} fn generic<T>(x:T)->T{x} async fn asynchronous(){} unsafe fn dangerous(){} mod outside; mod inside{fn member(){}} struct S; impl S{fn method(&self){}} trait Trait{fn abstracted(&self);fn provided(&self){}} example!();").unwrap();
    let result = inventory(&path).unwrap();
    let entries = result["functions"].as_array().unwrap();
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
    let help = Command::new(exe).args(["plan", "--help"]).output().unwrap();
    assert!(
        help.status.success(),
        "{}",
        String::from_utf8_lossy(&help.stderr)
    );
    assert!(String::from_utf8_lossy(&help.stdout).contains("--otelc-root"));
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
