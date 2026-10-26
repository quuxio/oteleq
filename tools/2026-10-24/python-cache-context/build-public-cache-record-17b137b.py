"""Assemble a bounded public qualification record only after both fresh corpora pass."""
import hashlib,json,re
from pathlib import Path
R=Path(__file__).resolve().parent
DRIVER='17b137b01c22617e2864cd8748b2a52558114f2f'
RUNTIME='95d94aed4fa7e1319392cd8013003cefbcc76888'
def read(name):return json.loads((R/name).read_text())
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
index=read('source-17b137b.json');runtime_index=read('source-95d94ae.json');runtime_identity=read('runtime-95d94ae/identity.json')
assert index['head']==DRIVER and runtime_index['head']==RUNTIME and runtime_identity['head']==RUNTIME
corpora=[]
for label in ['312','314']:
 folder=R/f'portable-full-{label}-17b137b';data=json.loads((folder/'qualification.json').read_text())
 expected={'actual_application_launches':244,'sdk_processes':122,'reports':48,'complete_raw_and_typed_observations':248,'copied_original_observations':4,'recomputed_comparisons':62,'prelaunch_input_mutation_refusals':6,'altered_comparison_refusals':5}
 assert data['totals']==expected and set(data['components'])=={'matrix','receivers','effects'}
 assert data['cli_sha256']==runtime_identity['sha256']
 preserved={}
 for component in ['matrix','receivers','effects']:
  source=folder/component/'provider-inputs.json';preserved[component]=digest(source)
  assert data['components'][component]['new_application_launches_in_audit']==0
 corpora.append({'python':'3.12.15' if label=='312' else '3.14.8','python_hexversion':data['python_hexversion'],
  'result_sha256':digest(folder/'qualification.json'),'totals':expected,'components':data['components'],
  'provider_catalogue_sha256':preserved})
gate=read('full-gate-17b137b/result.json');assert gate['exit_code']==0 and gate['source_preserved'] and gate['tracked_files_checked']==501
gate_log=(R/'full-gate-17b137b/make-check.log').read_text();generation_tests=max(map(int,re.findall(r'Ran (\d+) tests',gate_log)));assert generation_tests==1178
bridge=read('sdk-e8e5861-consumed-input-bridge.json');assert bridge['same_consumed_Python_native_builder_sources_and_modes']
review=Path('/Users/sclarke/github/otelc-qualification/2026-10-24/oteleq-cache-workflow-review-17b137b/review.json');assert review.is_file()
files=['tests/qualify_python_cached_workflows.py','tests/python_cache_receiver_workflows.py',
 'tests/python_cache_effect_workflows.py','tests/python_cache_qualification.py','tests/qualify_python_caches.py',
 'tests/qualify_python_generated_origins.py','tests/python_sequence_fixture.py','tests/sequence_qualification.py',
 'tests/python_origin_effect_workflows.py']
record={'qualification_schema_version':1,'date':'2026-10-24','claim':'equivalence over these tests and observations',
 'artefact_class':'diagnostic','scope_status':'qualified recorded ordinary-loader cache and synchronous generated diagnostic workflows',
 'platform':{'os':'macOS','architecture':'arm64','python':['3.12.15','3.14.8']},
 'runtime':{'repository':'quuxio/oteleq','commit':RUNTIME,'source_archive_sha256':runtime_index['archive_sha256'],
  'source_files':len(runtime_index['files']),'cli_sha256':runtime_identity['sha256'],
  'exact_embedded_production_modules':runtime_identity['exact_embedded_modules'],'runtime_sources_unchanged_in_driver':True},
 'verifier':{'commit':DRIVER,'source_archive_sha256':index['archive_sha256'],'source_files_preserved':501,
  'entrypoint':'tests/qualify_python_cached_workflows.py','execution_command':'make generation-python-cache-workflows-otelc',
  'retained_options':['--recheck','--audit-dir NEW_EXTERNAL_DIRECTORY'],'components':['matrix','receivers','effects','all'],
  'files_sha256':{name:index['files'][name] for name in files}},
 'provider':{'repository':'quuxio/otelc','commit':'ce4cf749279c1b4416ca79e18c194c8c908471f6',
  'source_archive_sha256':'f15d9b9f2278988962f07828a013a77e33b84625d93592a2c60f12d7e74c8606',
  'source_files':389,'profile':'python-native-cache-origins-v3',
  'protocols':{'request':3,'plan':3,'prepared':3,'command':3,'execution':3,'journal':3,'code':2,'health':2,'sdk':1,'code_comparisons':None,'source_complete':False},
  'candidate_source_compatibility':{'commit':bridge['candidate'],'tree':bridge['candidate_tree'],
   'consumed_static_source_paths_each_runtime':85,'all_blob_bytes_and_executable_modes_identical':True,
   'bridge_sha256':digest(R/'sdk-e8e5861-consumed-input-bridge.json'),'new_target_or_binary_executions':0,
   'scope':'Static consumed Python/native/builder input compatibility only; actual products/execution remain the frozen ce4 evidence. No Go or whole-SDK admission.'}},
 'results':{'completed_runtime_corpora':2,'actual_application_launches':488,'sdk_processes':244,'reports':96,
  'recomputed_comparisons':124,'complete_raw_and_typed_observations':496,'copied_original_observations':8,
  'prelaunch_input_mutation_refusals':12,'altered_comparison_refusals':10,'new_target_applications_in_retained_audits':0},
 'corpora':corpora,
 'checked_behaviour':['Ordinary timestamp, checked-hash and unchecked-hash cache use; accepted older unchecked body; missing/stale/invalid-magic source fallback',
  'Original and private source/cache bytes, bounded catalogues, timestamps, permissions, original identities and independently recomputed plan source hashes',
  'Every observed cache root, including unexecuted roots, bound to independently frozen consumed cache bytes; selected target/creator and SDK code joins checked separately',
  'Real package receivers/factories, own statics/globals/instance fields, aliases/cycles, recursion, exceptions and every ordered intermediate graph',
  'Generated domains, complete independent raw and typed return/state/effect oracles, exact filesystem bytes/permissions and scripted HTTP requests/responses',
  'Generated/replay/unittest/detached/reduced suites and fresh unchanged/changed/added-function source promotion with independent historical-stage inputs',
  'Actual supervisor/application/SDK ownership, raw native journals/descriptors, direct final health and decoded OTLP signals',
  'Exact route argv and terminal receipts; deliberately altered inputs refused before an additional process-start record; retained-only audits preserve original records and do not rerun mutations'],
 'review':{'portable_driver_and_original_full_corpus_review_sha256':digest(review),
  'scope':'Reviewed implementation and retained original corpus; fresh corpus and final publication/delivery reviews recorded separately.'},
 'validation':{'full_gate_commit':DRIVER,'full_gate_exit_code':0,'source_files_held':501,
  'full_gate_result_sha256':digest(R/'full-gate-17b137b/result.json'),'full_gate_log_sha256':digest(R/'full-gate-17b137b/make-check.log'),
  'generation_tests':generation_tests,'rust_product_line_coverage_percent':97.38,'focused_python_tests_each_runtime':216,'makefile_tests':8,'qualification_targets_in_three_directory_modes':44,
  'scope':'The Python3.12 qualifier host is measured separately. Application/native/SDK launch recipes are unchanged and contain no host-coverage startup.'},
 'preserved_failures':['d376 harness copy reset source timestamps; explicit cache-only copy2 and a failing-before/passing-after regression corrected it',
  '622 expected-body direct compilation rejected valid older unchecked cache code; explicit write-disabled ordinary get_code corrected it, defaults unchanged',
  '294 retained auditor expected equivalent instead of equivalent_observed; exact full public-response equality and repeatable read-only comparison corrected it',
  '294 full gate found an obsolete42-target recipe expectation; every subsequently added target is explicitly tested in default, relative and spaced target directories',
  'Earlier standalone observer/external audit commands omitted required module paths; corrected scoped runs preserve the original failures'],
 'limits':['Only recorded CPython ordinary application-root source-loader/cache-return profiles are qualified; unsupported/sourceless/custom loaders and general dependency closure remain open',
  'A consumed cache binding is not proof of compilation from current source; cache optimisation3 is unknown and the source-only defaults remain separate',
  'General object arguments/factories, async/generator/resource actions, live Python metric controls and invocation-scoped attribution require separate work',
  'First-execution identities are not invocation counts; health and decoded telemetry supply their separate observations',
  'Generated diagnostic callers and native observers are part of the tested workload, not independent shipping-artefact proof',
  'Other toolchain/platform/provider/callable/build profiles and complete interpreter/OS/import closure are outside this record',
  'All21 acceptance areas in docs/completion.md remain in force; full-project completion is not claimed']}
(R/'public-python-generated-caches-2026-10-24.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps({'runtime':RUNTIME,'driver':DRIVER,'results':record['results'],'record_sha256':digest(R/'public-python-generated-caches-2026-10-24.json')}),flush=True)
