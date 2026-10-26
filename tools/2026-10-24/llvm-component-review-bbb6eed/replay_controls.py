"""Recheck the two independent LLVM findings against the corrected component."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source"
INDEX = json.loads((ROOT / "source-index.json").read_text())


def source_facts() -> dict:
    result = {}
    for name, digest in INDEX["files"].items():
        path = SOURCE / name
        info = path.stat()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, name
        result[name] = (info.st_dev, info.st_ino, info.st_mode, info.st_size,
                        info.st_mtime_ns, info.st_ctime_ns)
    return result


before = source_facts()
sys.path.insert(0, str(SOURCE))
from otelc import llvm_backend as backend
from otelc.config import Policy

work = ROOT / "controls-after"
work.mkdir()
plugin = backend.build(work / "plugin", config=Path("/opt/homebrew/opt/llvm@22/bin/llvm-config"))
record = backend.verify(plugin)
tools = Path(record["toolchain"]["directory"])
library = Path(record["plugin"]["path"])
names = ["otelc_workload", "__cyg_profile_func_workload"]
policy = Policy.parse({"schema_version": 3, "languages": ["c"],
                       "functions": {"include": names}})
assert all(policy.selection("functions").accepts(name) for name in names)
environment = backend.environment(policy, "c")
commands = []


def run(argv: list, *, env=None, success=True) -> subprocess.CompletedProcess:
    argv = list(map(str, argv))
    result = subprocess.run(argv, env=env, capture_output=True, timeout=120)
    commands.append({"argv": argv, "exit_code": result.returncode,
                     "stdout": result.stdout.decode(errors="replace"),
                     "stderr": result.stderr.decode(errors="replace")})
    assert (result.returncode == 0) == success, commands[-1]
    return result


application = work / "application.c"
application.write_text('#include <stdio.h>\n'
                       '__attribute__((noinline)) int otelc_workload(void){return 20;}\n'
                       '__attribute__((noinline)) int __cyg_profile_func_workload(void){return 22;}\n'
                       'int main(void){printf("%d\\n",otelc_workload()+__cyg_profile_func_workload());return 0;}\n')
run([tools / "clang", application, "-o", work / "plain"])
run([tools / "clang", "-fpass-plugin=" + str(library), "-c", application,
     "-o", work / "woven.o"], env=environment)
run([tools / "clang++", "-c", SOURCE / "tests/fixtures/llvm/hooks.cpp", "-o", work / "hooks.o"])
run([tools / "clang++", work / "woven.o", work / "hooks.o", "-pthread", "-o", work / "woven"])
plain = run([work / "plain"])
woven = run([work / "woven"], env=dict(os.environ, PROBE_REPORT=str(work / "report.json")))
assert plain.stdout == woven.stdout == b"42\n" and plain.stderr == woven.stderr == b""
counts = json.loads((work / "report.json").read_text())
assert counts == {"entries": 2, "normal": 2, "unwind": 0, "invalid": 0}

declarations = {
    "enter-fastcc": "declare fastcc i64 @otelc_function_enter_v1(ptr)",
    "leave-fastcc": "declare fastcc void @otelc_function_leave_v1(i64, i32)",
    "enter-memory-none": "declare i64 @otelc_function_enter_v1(ptr) memory(none)",
    "leave-memory-none": "declare void @otelc_function_leave_v1(i64, i32) memory(none)",
    "enter-noreturn": "declare i64 @otelc_function_enter_v1(ptr) noreturn",
    "enter-byval": "declare i64 @otelc_function_enter_v1(ptr byval(i64))",
    "enter-inreg": "declare inreg i64 @otelc_function_enter_v1(ptr)",
}
environment.update(OTELC_FUNCTION_INCLUDE='["workload"]')
for name, declaration in declarations.items():
    source, output = work / (name + ".ll"), work / (name + "-woven.ll")
    source.write_text(declaration + "\ndefine i32 @workload() { ret i32 42 }\n")
    result = run([tools / "opt", "-load-pass-plugin=" + str(library),
                  "-passes=default<O0>", "-S", source, "-o", output],
                 env=environment, success=False)
    assert b"conflicts with the reserved probe ABI" in result.stderr and not output.exists()

backend.verify(plugin)
assert source_facts() == before
(work / "commands.json").write_text(json.dumps(commands, indent=2) + "\n")
receipt = {"head": INDEX["head"], "source_files_bytes_and_facts_held": len(before),
           "selected_functions": names, "common_policy_accepts": True,
           "plain_and_woven_stdout": "42\n", "probe_counts": counts,
           "incompatible_abi_refusals": list(declarations),
           "scope": "LLVM component and diagnostic ABI; no native SDK or oteleq workflow admission."}
(work / "result.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps(receipt))
