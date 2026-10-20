use quux_oteleq::{compare, Bundle};
use std::{
    env,
    fs::File,
    io::{BufWriter, Read, Write},
    process::ExitCode,
};
const MAX_BYTES: u64 = 16 * 1024 * 1024;
fn write_report<T: serde::Serialize>(report: &T, code: i32) -> Result<i32, String> {
    let stdout = std::io::stdout();
    let mut output = BufWriter::new(stdout.lock());
    serde_json::to_writer_pretty(&mut output, report).map_err(|e| format!("write report: {e}"))?;
    output
        .write_all(b"\n")
        .and_then(|_| output.flush())
        .map_err(|e| format!("write report: {e}"))?;
    Ok(code)
}
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
    if args.first().is_some_and(|arg| arg == "render-report") {
        if args.get(1).is_some_and(|arg| arg == "--help") && args.len() == 2 {
            println!("quux-oteleq render-report REPORT.json --output-dir NEW_DIRECTORY\nRender retained generation evidence as standalone HTML and JUnit XML without executing target code. Exits: 0 complete matches, 1 observed differences, 2 arguments, 3 incomplete inventory/evidence, 4 input/output/schema error. Existing destinations are refused.");
            return Ok(0);
        }
        if args.len() != 4 || args[2] != "--output-dir" {
            eprintln!("usage: quux-oteleq render-report REPORT.json --output-dir NEW_DIRECTORY");
            return Ok(2);
        }
        return quux_oteleq::reporting::write_report(
            std::path::Path::new(&args[1]),
            std::path::Path::new(&args[3]),
        );
    }
    if args == ["--help"] {
        println!("quux-oteleq compare-workload BUNDLE.json\nquux-oteleq compare-observations TYPED_BUNDLE.json\nquux-oteleq render-report REPORT.json --output-dir NEW_DIRECTORY\nquux-oteleq plan|generate|run|replay|clean|export-tests --help\nGenerate external paired unit harnesses for all eight otelc languages. Set OTELEQ_PYTHON to a Python 3.12+ environment with opentelemetry-proto for execution.\nComparator exits: 0 equivalent, 1 different, 2 invalid/source changed, 3 incomplete, 4 IO/codec error.\nGeneration exits: 0 complete, 1 different, 2 argument error, 3 incomplete/blocked, 4 tool/build/identity error.");
        return Ok(0);
    }
    if args.len() != 2 || !["compare-workload", "compare-observations"].contains(&args[0].as_str())
    {
        eprintln!("usage: quux-oteleq --help for comparison and generation commands");
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
    if args[0] == "compare-observations" {
        let bundle: quux_oteleq::typed::Bundle =
            serde_json::from_slice(&bytes).map_err(|e| format!("decode typed bundle: {e}"))?;
        return match quux_oteleq::typed::compare(bundle) {
            Ok(report) => write_report(&report, report.verdict.exit_code()),
            Err(error) => {
                eprintln!("invalid typed bundle: {error}");
                Ok(2)
            }
        };
    }
    let bundle: Bundle =
        serde_json::from_slice(&bytes).map_err(|e| format!("decode bundle: {e}"))?;
    match compare(bundle) {
        Ok(report) => write_report(&report, report.verdict.exit_code()),
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
