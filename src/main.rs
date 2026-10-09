use quux_oteleq::{compare, Bundle};
use std::{
    env,
    fs::File,
    io::{BufWriter, Read, Write},
    process::ExitCode,
};
const MAX_BYTES: u64 = 16 * 1024 * 1024;
fn run(args: &[String]) -> Result<i32, String> {
    if args.len() == 2 && args[0] == "inventory-rust" {
        let inventory = quux_oteleq::generation::inventory(std::path::Path::new(&args[1]))?;
        println!("{inventory}");
        return Ok(0);
    }
    if args.first().is_some_and(|arg| {
        ["plan", "generate", "run", "replay", "clean", "export-tests"].contains(&arg.as_str())
    }) {
        return quux_oteleq::generation::launch(args);
    }
    if args == ["--help"] {
        println!("quux-oteleq compare-workload BUNDLE.json\nquux-oteleq plan|generate|run|replay|clean|export-tests --help\nGenerate external paired unit harnesses for all eight otelc languages. Set OTELEQ_PYTHON to a Python 3.12+ environment with opentelemetry-proto for execution. Exit: 0 equivalent, 1 different, 2 invalid/source changed, 3 incomplete, 4 IO/codec error.");
        return Ok(0);
    }
    if args.len() != 2 || args[0] != "compare-workload" {
        eprintln!("usage: quux-oteleq compare-workload BUNDLE.json (or --help)");
        return Ok(2);
    }
    let file = File::open(&args[1]).map_err(|e| format!("open bundle: {e}"))?;
    let mut bytes = Vec::new();
    file.take(MAX_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|e| format!("read bundle: {e}"))?;
    if bytes.len() as u64 > MAX_BYTES {
        return Err("bundle exceeds 16 MiB; comparison incomplete".into());
    }
    let bundle: Bundle =
        serde_json::from_slice(&bytes).map_err(|e| format!("decode bundle: {e}"))?;
    match compare(bundle) {
        Ok(report) => {
            let code = report.verdict.exit_code();
            let stdout = std::io::stdout();
            let mut output = BufWriter::new(stdout.lock());
            serde_json::to_writer_pretty(&mut output, &report)
                .map_err(|e| format!("write report: {e}"))?;
            output
                .write_all(b"\n")
                .and_then(|_| output.flush())
                .map_err(|e| format!("write report: {e}"))?;
            Ok(code)
        }
        Err(error) => {
            eprintln!("invalid workload bundle: {error}");
            Ok(2)
        }
    }
}
fn main() -> ExitCode {
    match run(&env::args().skip(1).collect::<Vec<_>>()) {
        Ok(code) => ExitCode::from(code as u8),
        Err(error) => {
            eprintln!("{error}");
            ExitCode::from(4)
        }
    }
}
