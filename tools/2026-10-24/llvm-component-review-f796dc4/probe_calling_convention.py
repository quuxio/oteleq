"""An incompatible declaration must not be accepted as the fixed C probe ABI."""
from pathlib import Path
import hashlib,json,os,subprocess
r=Path(__file__).resolve().parent;work=r/'calling-convention-before';work.mkdir()
plugin=r/'prefix-before/plugin';manifest=json.loads((plugin/'llvm-plugin.json').read_text());library=Path(manifest['plugin']['path']);assert hashlib.sha256(library.read_bytes()).hexdigest()==manifest['plugin']['sha256']
bin=Path(manifest['toolchain']['directory'])
source=work/'fastcc.ll';source.write_text('declare fastcc i64 @otelc_function_enter_v1(ptr)\ndeclare void @otelc_function_leave_v1(i64, i32)\ndefine i32 @workload() { ret i32 42 }\n')
env={k:v for k,v in os.environ.items() if not k.startswith('OTELC_')};env.update(OTELC_FUNCTION_INCLUDE='["workload"]',OTELC_FUNCTION_EXCLUDE='[]',OTELC_READ_ANNOTATIONS='0')
output=work/'woven.ll';argv=[str(bin/'opt'),'-load-pass-plugin='+str(library),'-passes=default<O0>','-S',str(source),'-o',str(output)]
result=subprocess.run(argv,env=env,capture_output=True,timeout=90)
(work/'stdout').write_bytes(result.stdout);(work/'stderr').write_bytes(result.stderr)
text=output.read_text() if output.exists() else ''
receipt={'head':'f796dc457b968416235260f126b1cba716e4a16b','argv':argv,'exit_code':result.returncode,
 'expected_refusal':'Reserved C ABI declaration has fastcc calling convention.',
 'accepted_fastcc_declaration':result.returncode==0 and 'declare fastcc i64 @otelc_function_enter_v1' in text,
 'inserted_c_call':'call i64 @otelc_function_enter_v1' in text,
 'scope':'IR-only compiler boundary probe; no application, SDK runtime or crash claim.'}
(work/'result.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
