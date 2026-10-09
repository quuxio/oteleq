//! Embedded adapter host and Rust syntax inventory. Workers never import target code here.
use quote::ToTokens;
use serde_json::{json, Value};
use std::{env, fs, path::Path, process::Command};
use syn::{spanned::Spanned, visit::Visit};

const RESOURCES: &[(&str, &str)] = &[
    (
        "GENERATED-LICENSE.txt",
        include_str!("../adapters/generation/GENERATED-LICENSE.txt"),
    ),
    (
        "generation.py",
        include_str!("../adapters/generation/generation.py"),
    ),
    (
        "discovery.py",
        include_str!("../adapters/generation/discovery.py"),
    ),
    (
        "harness.py",
        include_str!("../adapters/generation/harness.py"),
    ),
    (
        "observe.py",
        include_str!("../adapters/generation/observe.py"),
    ),
    (
        "discover.mjs",
        include_str!("../adapters/generation/discover.mjs"),
    ),
    (
        "discover.go",
        include_str!("../adapters/generation/discover.go"),
    ),
    (
        "Discover.java",
        include_str!("../adapters/generation/Discover.java"),
    ),
    (
        "otelc_capture.py",
        include_str!("../examples/otelc_capture.py"),
    ),
    (
        "capture_otelc_languages.py",
        include_str!("../examples/capture_otelc_languages.py"),
    ),
    (
        "otelc-workloads.json",
        include_str!("../examples/otelc-workloads.json"),
    ),
    (
        "otelc-worker-workloads.json",
        include_str!("../examples/otelc-worker-workloads.json"),
    ),
];

pub fn launch(args: &[String]) -> Result<i32, String> {
    let parent = Path::new("/tmp")
        .canonicalize()
        .map_err(|e| format!("adapter temporary parent: {e}"))?;
    for pair in args.windows(2) {
        if ["--source", "--otelc-root", "--workspace"].contains(&pair[0].as_str()) {
            let root = Path::new(&pair[1])
                .canonicalize()
                .map_err(|e| format!("input path: {e}"))?;
            if parent.starts_with(root) {
                return Err("adapter directory must be outside input repositories".into());
            }
        }
    }
    let directory = tempfile::Builder::new()
        .prefix("oteleq-adapter-")
        .tempdir_in(parent)
        .map_err(|e| format!("create adapter directory: {e}"))?;
    for (name, source) in RESOURCES {
        fs::write(directory.path().join(name), source)
            .map_err(|e| format!("write adapter: {e}"))?;
    }
    let executable = env::current_exe().map_err(|e| format!("CLI identity: {e}"))?;
    let python = env::var("OTELEQ_PYTHON").unwrap_or_else(|_| "python3".into());
    let status = Command::new(python)
        .arg(directory.path().join("generation.py"))
        .args(args)
        .env("OTELEQ_EXECUTABLE", executable)
        .env("PYTHONDONTWRITEBYTECODE", "1")
        .status()
        .map_err(|e| format!("start adapter host (set OTELEQ_PYTHON): {e}"))?;
    Ok(status.code().unwrap_or(4))
}

struct Inventory {
    entries: Vec<Value>,
    globals: Vec<Value>,
    depth: usize,
}
impl Inventory {
    fn function(&mut self, sig: &syn::Signature, body: bool, method: bool) {
        let parameters: Vec<String> = sig
            .inputs
            .iter()
            .map(|input| match input {
                syn::FnArg::Typed(arg) => arg.ty.to_token_stream().to_string(),
                syn::FnArg::Receiver(_) => "self".into(),
            })
            .collect();
        let output = match &sig.output {
            syn::ReturnType::Default => "()".into(),
            syn::ReturnType::Type(_, ty) => ty.to_token_stream().to_string(),
        };
        let reason = if method || self.depth > 0 {
            "method or nested callable needs an access fixture"
        } else if !sig.generics.params.is_empty() {
            "generic callable needs a concrete instantiation"
        } else if sig.asyncness.is_some()
            || matches!(sig.safety, syn::Safety::Unsafe(_))
            || sig.variadic.is_some()
            || !body
        {
            "async, unsafe, variadic or external callable needs a fixture"
        } else {
            ""
        };
        let span = sig.ident.span();
        self.entries.push(
            json!({"name":sig.ident.to_string(), "line":span.start().line,
            "column":span.start().column, "parameters":parameters,"output":output,"reason":reason}),
        );
    }
}
impl<'ast> Visit<'ast> for Inventory {
    fn visit_item_fn(&mut self, node: &'ast syn::ItemFn) {
        self.function(&node.sig, true, false);
        self.depth += 1;
        syn::visit::visit_item_fn(self, node);
        self.depth -= 1;
    }
    fn visit_impl_item_fn(&mut self, node: &'ast syn::ImplItemFn) {
        self.function(&node.sig, true, true);
        self.depth += 1;
        syn::visit::visit_impl_item_fn(self, node);
        self.depth -= 1;
    }
    fn visit_trait_item_fn(&mut self, node: &'ast syn::TraitItemFn) {
        self.function(&node.sig, node.default.is_some(), true);
        syn::visit::visit_trait_item_fn(self, node);
    }
    fn visit_expr_closure(&mut self, node: &'ast syn::ExprClosure) {
        self.entries
            .push(json!({"name":"<closure>","line":node.span().start().line,"column":node.span().start().column,
            "parameters":[],"output":"unknown","reason":"closure needs a capture fixture"}));
        syn::visit::visit_expr_closure(self, node);
    }
    fn visit_item_mod(&mut self, node: &'ast syn::ItemMod) {
        self.depth += 1;
        syn::visit::visit_item_mod(self, node);
        self.depth -= 1;
        if node.content.is_none() {
            self.entries.push(json!({"name":node.ident.to_string(),"line":node.span().start().line,"column":node.span().start().column,
                "parameters":[],"output":"unknown","reason":"external module requires crate build context"}));
        }
    }
    fn visit_item_static(&mut self, node: &'ast syn::ItemStatic) {
        self.globals.push(json!({"name":node.ident.to_string(),
            "type":node.ty.to_token_stream().to_string(),"inaccessible":self.depth > 0,
            "mutable":matches!(node.mutability,syn::StaticMutability::Mut(_))}));
    }
    fn visit_item_macro(&mut self, node: &'ast syn::ItemMacro) {
        self.entries
            .push(json!({"name":node.mac.path.to_token_stream().to_string(),
            "line":node.span().start().line,"column":node.span().start().column,"parameters":[],"output":"unknown",
            "reason":"macro expansion requires crate build context"}));
    }
}
pub fn inventory(path: &Path) -> Result<Value, String> {
    let source = fs::read_to_string(path).map_err(|e| format!("read Rust source: {e}"))?;
    let syntax = syn::parse_file(&source).map_err(|e| format!("parse Rust source: {e}"))?;
    let mut inventory = Inventory {
        entries: vec![],
        globals: vec![],
        depth: 0,
    };
    inventory.visit_file(&syntax);
    Ok(json!({"functions":inventory.entries,"globals":inventory.globals,"parser":"syn 3.0.6"}))
}
