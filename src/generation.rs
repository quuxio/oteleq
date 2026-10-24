//! Embedded adapter host and Rust syntax inventory. Workers never import target code here.
use quote::ToTokens;
use serde_json::{json, Value};
use std::{env, fs, path::Path, process::Command};
use syn::{spanned::Spanned, visit::Visit};

const ADAPTER_BOOTSTRAP: &str = concat!(
    "import runpy, sys; ",
    "root = sys.argv.pop(1); script = sys.argv[1]; ",
    "sys.path.insert(0, root); sys.argv = sys.argv[1:]; ",
    "runpy.run_path(script, run_name='__main__')"
);

const RESOURCES: &[(&str, &str)] = &[
    (
        "python_journal.py",
        include_str!("../adapters/generation/python_journal.py"),
    ),
    (
        "python_code.py",
        include_str!("../adapters/generation/python_code.py"),
    ),
    (
        "python_code_match.py",
        include_str!("../adapters/generation/python_code_match.py"),
    ),
    (
        "python_origin.py",
        include_str!("../adapters/generation/python_origin.py"),
    ),
    (
        "python_selection.py",
        include_str!("../adapters/generation/python_selection.py"),
    ),
    (
        "python_execution.py",
        include_str!("../adapters/generation/python_execution.py"),
    ),
    (
        "python_health.py",
        include_str!("../adapters/generation/python_health.py"),
    ),
    (
        "python_telemetry.py",
        include_str!("../adapters/generation/python_telemetry.py"),
    ),
    (
        "python_prepared.py",
        include_str!("../adapters/generation/python_prepared.py"),
    ),
    (
        "python_provider.py",
        include_str!("../adapters/generation/python_provider.py"),
    ),
    (
        "python_inputs.py",
        include_str!("../adapters/generation/python_inputs.py"),
    ),
    (
        "python_launch.py",
        include_str!("../adapters/generation/python_launch.py"),
    ),
    (
        "project_tests.py",
        include_str!("../adapters/generation/project_tests.py"),
    ),
    (
        "project_runner.py",
        include_str!("../adapters/generation/project_runner.py"),
    ),
    (
        "node_project.py",
        include_str!("../adapters/generation/node_project.py"),
    ),
    (
        "node_context.mjs",
        include_str!("../adapters/generation/node_context.mjs"),
    ),
    (
        "node_source_context.mjs",
        include_str!("../adapters/generation/node_source_context.mjs"),
    ),
    (
        "node_source_context.py",
        include_str!("../adapters/generation/node_source_context.py"),
    ),
    (
        "node_source.py",
        include_str!("../adapters/generation/node_source.py"),
    ),
    (
        "node_source_worker.py",
        include_str!("../adapters/generation/node_source_worker.py"),
    ),
    (
        "node_launch.py",
        include_str!("../adapters/generation/node_launch.py"),
    ),
    (
        "node_inputs.py",
        include_str!("../adapters/generation/node_inputs.py"),
    ),
    (
        "node_execution.py",
        include_str!("../adapters/generation/node_execution.py"),
    ),
    (
        "node_telemetry.py",
        include_str!("../adapters/generation/node_telemetry.py"),
    ),
    (
        "node_control.py",
        include_str!("../adapters/generation/node_control.py"),
    ),
    (
        "node_control_receipt.py",
        include_str!("../adapters/generation/node_control_receipt.py"),
    ),
    (
        "node_live.py",
        include_str!("../adapters/generation/node_live.py"),
    ),
    (
        "node_checkpoint.mjs",
        include_str!("../adapters/generation/node_checkpoint.mjs"),
    ),
    (
        "java_project.py",
        include_str!("../adapters/generation/java_project.py"),
    ),
    (
        "java_classpath.py",
        include_str!("../adapters/generation/java_classpath.py"),
    ),
    (
        "java_archives.py",
        include_str!("../adapters/generation/java_archives.py"),
    ),
    (
        "java_archive_context.py",
        include_str!("../adapters/generation/java_archive_context.py"),
    ),
    (
        "java_helper_binding.py",
        include_str!("../adapters/generation/java_helper_binding.py"),
    ),
    (
        "OteleqArchives.java",
        include_str!("../adapters/generation/OteleqArchives.java"),
    ),
    (
        "native_profile.py",
        include_str!("../adapters/generation/native_profile.py"),
    ),
    (
        "native_project.py",
        include_str!("../adapters/generation/native_project.py"),
    ),
    (
        "native_dependencies.py",
        include_str!("../adapters/generation/native_dependencies.py"),
    ),
    (
        "native_frontend.py",
        include_str!("../adapters/generation/native_frontend.py"),
    ),
    (
        "native_discover.cpp",
        include_str!("../adapters/generation/native_discover.cpp"),
    ),
    (
        "native_context.py",
        include_str!("../adapters/generation/native_context.py"),
    ),
    (
        "native_workers.py",
        include_str!("../adapters/generation/native_workers.py"),
    ),
    (
        "native_workspace.py",
        include_str!("../adapters/generation/native_workspace.py"),
    ),
    (
        "owned_workspace.py",
        include_str!("../adapters/generation/owned_workspace.py"),
    ),
    (
        "native_names.py",
        include_str!("../adapters/generation/native_names.py"),
    ),
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
        "cpp_models.py",
        include_str!("../adapters/generation/cpp_models.py"),
    ),
    (
        "cpp_receivers.py",
        include_str!("../adapters/generation/cpp_receivers.py"),
    ),
    (
        "cpp_worker.py",
        include_str!("../adapters/generation/cpp_worker.py"),
    ),
    (
        "cpp_graph.py",
        include_str!("../adapters/generation/cpp_graph.py"),
    ),
    (
        "cpp_observe.hpp",
        include_str!("../adapters/generation/cpp_observe.hpp"),
    ),
    (
        "harness.py",
        include_str!("../adapters/generation/harness.py"),
    ),
    (
        "python_project.py",
        include_str!("../adapters/generation/python_project.py"),
    ),
    (
        "go_project.py",
        include_str!("../adapters/generation/go_project.py"),
    ),
    (
        "go_receivers.py",
        include_str!("../adapters/generation/go_receivers.py"),
    ),
    (
        "go_graph.py",
        include_str!("../adapters/generation/go_graph.py"),
    ),
    (
        "go_observe.go",
        include_str!("../adapters/generation/go_observe.go"),
    ),
    (
        "node_receivers.py",
        include_str!("../adapters/generation/node_receivers.py"),
    ),
    (
        "java_receivers.py",
        include_str!("../adapters/generation/java_receivers.py"),
    ),
    (
        "java_health.py",
        include_str!("../adapters/generation/java_health.py"),
    ),
    (
        "java_witness.py",
        include_str!("../adapters/generation/java_witness.py"),
    ),
    (
        "java_action.py",
        include_str!("../adapters/generation/java_action.py"),
    ),
    (
        "java_action_session.py",
        include_str!("../adapters/generation/java_action_session.py"),
    ),
    (
        "java_action_receipt.py",
        include_str!("../adapters/generation/java_action_receipt.py"),
    ),
    (
        "java_action_bindings.py",
        include_str!("../adapters/generation/java_action_bindings.py"),
    ),
    (
        "java_handle_callers.py",
        include_str!("../adapters/generation/java_handle_callers.py"),
    ),
    (
        "OteleqRendezvous.java",
        include_str!("../adapters/generation/OteleqRendezvous.java"),
    ),
    (
        "java_control.py",
        include_str!("../adapters/generation/java_control.py"),
    ),
    (
        "java_profiles.py",
        include_str!("../adapters/generation/java_profiles.py"),
    ),
    (
        "java_live.py",
        include_str!("../adapters/generation/java_live.py"),
    ),
    (
        "java_control_receipt.py",
        include_str!("../adapters/generation/java_control_receipt.py"),
    ),
    (
        "java_launch.py",
        include_str!("../adapters/generation/java_launch.py"),
    ),
    (
        "java_provider.py",
        include_str!("../adapters/generation/java_provider.py"),
    ),
    (
        "java_telemetry.py",
        include_str!("../adapters/generation/java_telemetry.py"),
    ),
    (
        "java_build.py",
        include_str!("../adapters/generation/java_build.py"),
    ),
    (
        "OteleqCompile.java",
        include_str!("../adapters/generation/OteleqCompile.java"),
    ),
    (
        "java_graph.py",
        include_str!("../adapters/generation/java_graph.py"),
    ),
    (
        "OteleqGraph.java",
        include_str!("../adapters/generation/OteleqGraph.java"),
    ),
    (
        "typescript_provider.py",
        include_str!("../adapters/generation/typescript_provider.py"),
    ),
    (
        "sequences.py",
        include_str!("../adapters/generation/sequences.py"),
    ),
    (
        "filesystem_effects.py",
        include_str!("../adapters/generation/filesystem_effects.py"),
    ),
    (
        "http_effects.py",
        include_str!("../adapters/generation/http_effects.py"),
    ),
    (
        "policy.py",
        include_str!("../adapters/generation/policy.py"),
    ),
    (
        "return_expectations.py",
        include_str!("../adapters/generation/return_expectations.py"),
    ),
    (
        "domains.py",
        include_str!("../adapters/generation/domains.py"),
    ),
    (
        "preconditions.py",
        include_str!("../adapters/generation/preconditions.py"),
    ),
    (
        "shrinking.py",
        include_str!("../adapters/generation/shrinking.py"),
    ),
    (
        "observe.py",
        include_str!("../adapters/generation/observe.py"),
    ),
    (
        "node_observe.mjs",
        include_str!("../adapters/generation/node_observe.mjs"),
    ),
    (
        "node_sequence.mjs",
        include_str!("../adapters/generation/node_sequence.mjs"),
    ),
    (
        "typed_capture.py",
        include_str!("../adapters/generation/typed_capture.py"),
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
        "otelc_rust_build.py",
        include_str!("../examples/otelc_rust_build.py"),
    ),
    (
        "otelc_collection.py",
        include_str!("../examples/otelc_collection.py"),
    ),
    (
        "otelc_resource.py",
        include_str!("../examples/otelc_resource.py"),
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
    (
        "otelc-typescript-native-workloads.json",
        include_str!("../examples/otelc-typescript-native-workloads.json"),
    ),
    (
        "otelc-collection-workloads.json",
        include_str!("../examples/otelc-collection-workloads.json"),
    ),
    (
        "otelc-resource-workloads.json",
        include_str!("../examples/otelc-resource-workloads.json"),
    ),
];

pub fn launch(args: &[String]) -> Result<i32, String> {
    let parent = Path::new("/tmp")
        .canonicalize()
        .map_err(|e| format!("adapter temporary parent: {e}"))?;
    for (index, argument) in args.iter().enumerate() {
        let (option, assigned) = argument
            .split_once('=')
            .map(|(option, value)| (option, Some(value)))
            .unwrap_or((argument.as_str(), None));
        if ["--source", "--otelc-root", "--workspace"].contains(&option) {
            let Some(value) = assigned.or_else(|| args.get(index + 1).map(String::as_str)) else {
                continue;
            };
            let root = Path::new(value)
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
        .args(["-I", "-B", "-c", ADAPTER_BOOTSTRAP])
        .arg(directory.path())
        .arg(directory.path().join("generation.py"))
        .args(args)
        .env_remove("PYTHONPATH")
        .env_remove("PYTHONHOME")
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
            "column":span.start().column, "parameters":parameters,"output":output,"reason":reason,
            "entrypoint": !method && self.depth == 0 && sig.ident == "main"}),
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
