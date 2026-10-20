"""Enforce LLVM line coverage of the compiled passive C++ observer."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

REPO = Path(__file__).resolve().parents[1]


def coverage(document: dict, source: Path) -> float:
    """Only the exact maintained observer counts towards its independent floor."""
    files = [item for unit in document["data"] for item in unit["files"]
             if Path(item["filename"]).resolve() == source.resolve()]
    if len(files) != 1:
        raise ValueError("C++ observer coverage is missing or ambiguous")
    lines = files[0]["summary"]["lines"]
    total, covered = lines["count"], lines["covered"]
    if type(total) is not int or type(covered) is not int or not 0 <= covered <= total or not total or covered / total < 0.8:
        raise ValueError("C++ observer line coverage is below 80% or invalid")
    return 100 * covered / total


def check(repo: Path) -> None:
    """Use coverage tools beside the selected real Clang compiler, with no SDK."""
    selected = shutil.which(os.environ.get("OTELC_CLANGXX", "clang++"))
    if selected is None:
        raise ValueError("C++ coverage requires the selected Clang compiler")
    # clang++ may resolve to clang; retaining argv[0] preserves C++ linking mode.
    compiler = Path(selected)
    tools = {name: compiler.resolve(strict=True).with_name(name) for name in ("llvm-cov", "llvm-profdata")}
    if any(not path.is_file() for path in tools.values()):
        raise ValueError("C++ coverage requires llvm-cov and llvm-profdata beside the selected compiler")
    build = repo / "build"
    build.mkdir(exist_ok=True)
    report = build / "cpp-observer-coverage.json"
    report.unlink(missing_ok=True)
    source = repo / "adapters/generation/cpp_observe.hpp"
    with tempfile.TemporaryDirectory(prefix="cpp-observer-", dir=build) as temporary:
        folder = Path(temporary)
        binary, raw, profile = folder / "probe", folder / "probe.profraw", folder / "probe.profdata"
        subprocess.run([compiler, "-std=c++17", "-O0", "-fprofile-instr-generate", "-fcoverage-mapping",
                        "-I", source.parent, repo / "tests/cpp_observer_probe.cpp", "-o", binary], check=True, timeout=60)
        subprocess.run([binary], env={**os.environ, "LLVM_PROFILE_FILE": str(raw)}, check=True, timeout=30)
        subprocess.run([tools["llvm-profdata"], "merge", "-sparse", raw, "-o", profile], check=True, timeout=30)
        result = subprocess.run([tools["llvm-cov"], "export", binary, "-instr-profile=" + str(profile)],
                                capture_output=True, check=True, timeout=30)
        report.write_bytes(result.stdout)
    print(f"C++ observer line coverage: {coverage(json.loads(report.read_text()), source):.2f}%")


if __name__ == "__main__":
    check(REPO)
