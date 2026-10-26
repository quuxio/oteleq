"""Publish only a completed, identity-bound HTTP qualification and current docs."""
import hashlib
import json
from pathlib import Path
import platform

repo=Path('/private/tmp/oteleq-http-work')
root=Path('/private/tmp/oteleq-http-74be0db-evidence')
result=json.loads((root/'QUALIFICATION.json').read_text())
runtime=json.loads(Path('/private/tmp/oteleq-http-74be0db-runtime.json').read_text())
provider=json.loads(Path('/private/tmp/otelc-integrated-provider-0419a51-frozen.json').read_text())
assert result['cli_sha256']==runtime['cli_sha256']==hashlib.sha256(Path(runtime['cli']).read_bytes()).hexdigest()
assert result['cases']==18 and result['matching_cases']==result['same_return_http_difference_cases']==8
assert result['incomplete_effect_cases']==2 and result['source_preserved'] is True
assert result['actual_application_launches']==result['unique_command_identities']==544
assert result['raw_attempt_folders']==576 and result['altered_evidence_controls']==16
assert len(result['reductions'])==8 and all(row['arguments']==[1] for row in result['reductions'])
plan_paths=list((root/'cases').glob('*/plan.json'));assert len(plan_paths)==1
plan=json.loads(plan_paths[0].read_text())
source_names={row['path'] for row in plan['inventory']}
record={'qualification_schema_version':1,'date':'2026-10-20',**result,
 'consumer':{'runtime_commit':runtime['source_commit'],'cli_sha256':runtime['cli_sha256'],
  'qualification_sources_sha256':{name:hashlib.sha256((repo/name).read_bytes()).hexdigest() for name in ('tests/qualify_http.py','tests/effect_qualification.py','tests/qualify_generation.py')}},
 'provider':{'repository':'quuxio/otelc','merged_source_commit':provider['source_commit'],'source_tree':provider['source_tree'],
  'manifest_sha256':hashlib.sha256(Path('/private/tmp/otelc-integrated-provider-0419a51-frozen.json').read_bytes()).hexdigest(),
  'verified_source_records':len(provider['source_sha256']),'verified_product_records':len(provider['products_sha256']),
  'verified_dependency_records':len(provider['dependencies']),'verified_tool_records':len(provider['tools']),
  'cli_sha256':provider['products_sha256']['target/debug/quux-otelc']},
 'platform':{'system':platform.system(),'release':platform.release(),'architecture':platform.machine(),
  'rust_backend':'compiler','typescript_backend':'source',
  'tools':{name:{k:value[k] for k in ('sha256','version')} for name,value in provider['tools'].items()}},
 'corpus':{'languages':['c','cpp','rust','python','java','javascript','typescript','go'],
  'source_files':len(source_names),'inventoried_callables':len(plan['inventory']),
  'selected_callables':sum(row['status']=='ready' for row in plan['inventory']),
  'excluded_helpers':sum(row['status']=='excluded' for row in plan['inventory']),
  'repeats':{'baseline':2,'instrumented_on':2},'request_body_hex':'00ff','different_request_body_hex':'01ff',
  'offered_response_status':201,'offered_response_body_hex':'00ff','all_returns':7,
  'incomplete_controls':['python missing required request','python unsupported chunked request'],
  'routes':{'direct':72,'generated_framework':72,'exported':72,'exported_framework':72},
  'reductions':{'cases':8,'actual_launches':256,'input_from':7,'input_to':1,'status':'candidate_rule_minimal','generated_reduced_framework_and_replay':True}},
 'validation':{'full_regressions':386,'components':{'rust':66,'capture_python':117,'generation_python':186,'node':17},
  'rust_product_line_coverage_percent':97.29,'http_module_line_coverage_percent':99,
  'shared_qualifier_line_coverage_percent':100,'required_per_module_floor_percent':80,
  'retained_filesystem_revalidation':{'actual_launches_revalidated':544,'raw_attempt_folders':576,'new_application_launches':0,'all_original_summary_fields_equal':True}},
 'development':{'matching_route_actual_launches':32,'included_in_final_launch_count':False,
  'incomplete_difference_route':{'actual_attempt_records':62,'independently_checked_complete_attempts':60,'status':'incomplete: ENOSPC during Go builds and Rust link; original strict failure retained'}},
 'limitations':['Diagnostic generated access/entrypoint helpers; no production/shipping artefact qualification.',
  'Whole-worker requests and offered responses, not per-function/action attribution or proof that every response byte was consumed.',
  'Only declared serial loopback HTTP/1 profile with matched literal URL per paired case; no TLS, multiplexing, general concurrency, undeclared network or complete socket lifecycle.',
  'Only explicitly selected raw request header lines are compared; limits, malformed framing and missing required requests remain incomplete.',
  'No hostile-code sandbox; other backend/project/platform combinations require separate qualification.',
  'Name-bound decoded invocation witness; no general invocation-scoped producer rendezvous.']}
assert record['corpus']['source_files']==8 and record['corpus']['selected_callables']==18
(repo/'docs/qualification/http-fixtures-2026-10-20.json').write_text(json.dumps(record,indent=2)+'\n')

def replace(file,old,new):
 p=repo/file;s=p.read_text();assert s.count(old)==1,(file,old[:100]);p.write_text(s.replace(old,new))

replace('docs/http-fixtures.md',
 'Focused regressions exercise real plain workers in all eight languages, framing/budget refusals and typed-channel enforcement. A separate development corpus completed 32 paired SDK application launches across the eight default language routes with binary request/response oracles and preserved sources. Final retained generated/exported-suite, same-return difference and shrinking qualification remains pending. A development result does not qualify a release, another provider or a shipping artefact.',
 'The [20 October qualification](qualification/http-fixtures-2026-10-20.json) records runtime `74be0db` against frozen otelc `0419a51` on macOS ARM64: 18 cases and 544 actual application launches. All four direct/generated/exported routes retain eight matching cases, eight same-return request-body differences and two incomplete controls. Sixteen altered-evidence controls and all eight scalar reductions from seven to one, reduced generated suites and replay passed. Sources remained unchanged. Literal binary request/response, selected headers, actual URL bindings and decoded instrumentation are checked independently of lane agreement.\n\nFull validation passes 386 regressions, with Rust line coverage 97.29%, HTTP capture 99% and the shared qualification runner 100%. Separate earlier development runs remain outside the final count, including the retained ENOSPC failure. This diagnostic qualification does not cover another provider, backend, platform or shipping artefact.')
replace('docs/completion.md',
 'Scripted [HTTP fixtures](http-fixtures.md) implement bounded serial loopback requests/offered responses for all eight runners; their development corpus passed 32 actual launches, with final difference/export/shrinking qualification pending.',
 'Scripted [HTTP fixtures](http-fixtures.md) implement bounded serial loopback requests/offered responses for all eight runners. Their [18-case/544-launch diagnostic corpus](qualification/http-fixtures-2026-10-20.json) qualifies generated/exported suites, eight same-return request differences, two incomplete controls and all eight scalar reductions/replays.')
replace('docs/languages.md',
 'Their 32-launch development corpus passed; final retained qualification remains pending.',
 'Their [18-case/544-launch diagnostic corpus](qualification/http-fixtures-2026-10-20.json) qualifies matching, same-return request differences, incomplete capture, generated/exported suites and all eight scalar reductions/replays.')
replace('docs/quality.md',
 'A separate development corpus passed 32 actual paired SDK launches. The maintained `generation-http-otelc` target separately qualifies generated/exported suites, deliberate differences and shrinking; final exact-revision qualification remains pending.',
 'The [exact-revision HTTP corpus](qualification/http-fixtures-2026-10-20.json) completes 18 cases and 544 actual launches against runtime `74be0db` and frozen provider `0419a51`: eight matches, eight same-return request differences, two incomplete controls, 16 altered-evidence controls and all eight scalar reductions/replays across generated/exported suites. Earlier development and ENOSPC attempts remain separate from that count.')
replace('README.md',
 'Fixed diagnostic corpora also qualify',
 'The [HTTP qualification](docs/qualification/http-fixtures-2026-10-20.json) covers 18 cases and 544 actual launches across all eight languages, including same-return request differences, incomplete capture and scalar shrinking/replay.\n\nFixed diagnostic corpora also qualify')
print(json.dumps({'qualification':str(repo/'docs/qualification/http-fixtures-2026-10-20.json'),'launches':544,'inventory':record['corpus']['inventoried_callables']}))
