"""Retained Go build channels, source/compiler bindings and strict refusal cases."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'examples'))
import otelc_capture as capture


class GoBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.base=Path(self.temporary.name).resolve();self.root=self.base/'provider'
        for name in ('build/otelc-go','go.mod','go.sum','policy/policy.go'):
            path=self.root/'adapters/go'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(name.encode())
        self.project=self.base/'project with spaces';self.project.mkdir()
        self.source=self.project/'app.go';self.source.write_text('package main\nfunc selected(v int)int{return v*3}\n')
        self.original=capture.file_digest(self.source)
        self.evidence=self.base/'evidence';self.evidence.mkdir();self.bundle=self.evidence/'go-bundle'
        self.policy=self.base/'policy.toml';self.policy.write_text('schema_version=2\nlanguages=["go"]\n[functions]\ninclude=["app.selected"]\n[traces]\nenabled=true\n')
        tools=self.base/'tools';tools.mkdir()
        for name in ('go','compile','asm','link'):(tools/name).write_bytes(name.encode())
        self.tools={'go':tools/'go'}
        self.env={name:'' for name in capture.GO_COMPILER_ENV}
        self.env.update({'GOTOOLDIR':str(tools),'GOVERSION':'go1.27.2','GOOS':'darwin','GOARCH':'arm64'})
        self.compiler={'program':str(self.tools['go']),'sha256':capture.file_digest(self.tools['go']),
                       'version':'go1.27.2','environment':self.env,
                       'tools':{str(tools/name):capture.file_digest(tools/name) for name in ('compile','asm','link')}}
        self.private=self.base/'recorded build path'
        inputs={str(self.source):{'sha256':self.original}}
        for name in ('go.mod','go.sum','policy/policy.go'):
            p=self.root/'adapters/go'/name;inputs[str(p)]={'sha256':capture.file_digest(p)}
        self.recipe={'schema_version':1,'source_root':str(self.project),'sdk_root':str(self.root/'adapters/go'),
                     'working_directory':str(self.private),'target':str(self.source),'compiler':self.compiler,'inputs':inputs,
                     'baseline_argv':['build','-mod=readonly','-modfile='+str(self.private/'baseline.mod'),'-o',str(self.private/'baseline'),str(self.source)],
                     'instrumented_argv':['build','-mod=mod','-modfile='+str(self.private/'go.mod'),'-overlay='+str(self.private/'overlay.json'),'-o',str(self.private/'application'),str(self.source)],
                     'baseline_build_info':{'GoVersion':'go1.27.2'},'instrumented_build_info':{'GoVersion':'go1.27.2'}}
        self.resolved={'schema_version':2,'language':'go','backend':'compile','sources':{'include':[],'exclude':[]},
                       'functions':{'include':['app.selected'],'exclude':[]},'annotations':{'read_existing':False,'inject_generated':False},'traces':{'enabled':True}}
        main={'Path':'fixture','Main':True}
        self.graph={'Settings':{'Go':'1.27.2'},'Modules':{'fixture':main}}
        self.on_graph=copy.deepcopy(self.graph)
        self.on_graph['Modules']['io.quux.otelc/go']={'Path':'io.quux.otelc/go','Main':False,'Replace':{'Path':str(self.root/'adapters/go'),'ModHash':capture.file_digest(self.root/'adapters/go/go.mod')}}

    def create_bundle(self,*_):
        self.bundle.mkdir()
        for name in capture.GO_REQUIRED_FILES:
            data=b'0\n' if name.endswith('.status') else b'compiler warning\xff\n' if name.endswith('.stderr') else b'bytes'
            (self.bundle/name).write_bytes(data)
        for name,value in [('recipe.json',self.recipe),('plan.json',self.resolved),('overlay.json',{'Replace':{}}),
                           ('modules-original.json',self.graph),('modules-instrumented.json',self.on_graph)]:
            (self.bundle/name).write_text(json.dumps(value))
        self.metadata={'schema_version':1,'language':'go','backend':'compile','adapter_sha256':capture.file_digest(self.root/'adapters/go/build/otelc-go'),
                       'files':{p.name:capture.file_digest(p) for p in self.bundle.iterdir()}}
        self.save_metadata()

    def save_metadata(self):
        (self.bundle/'build.json').write_text(json.dumps(self.metadata))

    def check_recipe(self):
        return capture.go_recipe(self.root,self.project,self.source,self.bundle,self.compiler,self.original)

    def test_pair_retains_binary_and_compiler_bytes_without_launching_application(self):
        result=subprocess.CompletedProcess([],0,json.dumps(self.env).encode(),b'')
        environment={}
        with patch.object(capture,'execute',return_value=result) as execute,patch.object(capture,'build',side_effect=self.create_bundle) as build:
            commands=capture.commands(self.root,self.project,'go',self.source,self.policy,self.tools,environment,self.evidence)
        self.assertEqual(execute.call_count,1)
        self.assertEqual(execute.call_args.args[0],[self.tools['go'],'env','-json',*capture.GO_COMPILER_ENV])
        self.assertEqual(build.call_count,1)
        self.assertEqual(build.call_args.args[0][-5:],['go','--build',self.source,'--output-dir',self.bundle])
        self.assertEqual([command[-2] for command in commands],['--run-baseline','--run'])
        self.assertTrue(all(command[-1]==self.bundle and self.tools['go'] not in command for command in commands))
        self.assertEqual(environment['GOMODCACHE'],str(self.base/'go-cache/modules'))
        self.assertEqual(environment['GOCACHE'],str(self.base/'go-cache/build'))
        identities=json.loads((self.evidence/'go-build-identities.json').read_text())
        self.assertEqual(identities['baseline'],capture.file_digest(self.bundle/'baseline'))
        self.assertEqual(identities['application'],capture.file_digest(self.bundle/'application'))
        self.assertEqual(identities['loaded_input_count'],4)
        self.assertIn(b'compiler warning\xff',(self.bundle/'baseline-build.stderr').read_bytes())
        self.assertEqual(capture.file_digest(self.source),self.original)

    def test_legacy_provider_failure_does_not_fall_back_to_go_run(self):
        result=subprocess.CompletedProcess([],0,json.dumps(self.env).encode(),b'')
        with patch.object(capture,'execute',return_value=result),patch.object(capture,'build',side_effect=ValueError('unsupported --build')) as build:
            with self.assertRaisesRegex(ValueError,'unsupported --build'):
                capture.go_commands(self.root,self.project,self.source,self.policy,self.tools,{},self.evidence)
        self.assertEqual(build.call_count,1)
        self.assertFalse((self.evidence/'go-build-identities.json').exists())

    def test_manifest_schema_inventory_and_payload_tampering_refuse(self):
        self.create_bundle();original=copy.deepcopy(self.metadata)
        controls=[{**original,'schema_version':True},{**original,'language':'rust'},{**original,'backend':'source'},
                  {**original,'extra':'unknown'},{**original,'adapter_sha256':'0'*64},{**original,'files':[]},
                  {**original,'files':{k:v for k,v in original['files'].items() if k!='baseline'}},
                  {**original,'files':{**original['files'],'baseline':'bad'}}]
        for candidate in controls:
            self.metadata=candidate;self.save_metadata()
            with self.subTest(candidate=candidate),self.assertRaises(ValueError):capture.go_files(self.root,self.bundle)
        self.metadata=original;self.save_metadata();(self.bundle/'application').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'changed'):capture.go_files(self.root,self.bundle)

    def test_unlisted_symlink_oversized_and_unsafe_bundle_files_refuse(self):
        self.create_bundle();extra=self.bundle/'unlisted';extra.write_text('extra')
        with self.assertRaisesRegex(ValueError,'unlisted'):capture.go_files(self.root,self.bundle)
        extra.unlink()
        for name in ('../outside','/absolute','back\\slash','nul\x00','..','build.json'):
            with self.subTest(name=name),self.assertRaises(ValueError):capture.go_bundle_file(self.bundle,name,'0'*64)
        binary=self.bundle/'baseline';content=binary.read_bytes();binary.unlink();binary.symlink_to(self.source)
        with self.assertRaisesRegex(ValueError,'regular'):capture.go_files(self.root,self.bundle)
        binary.unlink();binary.write_bytes(content)
        with binary.open('ab') as output:output.truncate(256*1024*1024+1)
        with self.assertRaisesRegex(ValueError,'size limit'):capture.go_bundle_file(self.bundle,'baseline',self.metadata['files']['baseline'])
        binary.write_bytes(content)
        status=self.bundle/'baseline-build.status';status.write_bytes(b'1\n');self.metadata['files'][status.name]=capture.file_digest(status);self.save_metadata()
        with self.assertRaisesRegex(ValueError,'did not succeed'):capture.go_files(self.root,self.bundle)

    def test_selected_compiler_source_sdk_and_flag_bindings_are_required(self):
        self.create_bundle();original=copy.deepcopy(self.recipe)
        controls=[{**original,'schema_version':True},{**original,'compiler':{}},
                  {**original,'source_root':'/other'},{**original,'target':'/other/app.go'},{**original,'sdk_root':'/other/sdk'},
                  {**original,'baseline_argv':[]},{**original,'baseline_argv':['build','-mod=mod',*original['baseline_argv'][2:]]},
                  {**original,'baseline_argv':['build','-mod=readonly','-modfile=relative/baseline.mod','-o','relative/baseline',str(self.source)]},
                  {**original,'instrumented_argv':['untrusted']},{**original,'inputs':{}},{**original,'baseline_build_info':{}}]
        for candidate in controls:
            (self.bundle/'recipe.json').write_text(json.dumps(candidate))
            with self.subTest(candidate=candidate),self.assertRaises(ValueError):self.check_recipe()
        (self.bundle/'recipe.json').write_text(json.dumps(original))
        self.assertEqual(self.check_recipe(),original)
        self.source.write_text('changed')
        with self.assertRaisesRegex(ValueError,'loaded input changed'):self.check_recipe()

    def test_loaded_dependencies_and_optional_absence_are_checked(self):
        self.create_bundle();dependency=self.base/'dependency.go';dependency.write_text('package dependency')
        self.recipe['inputs'][str(dependency)]={'sha256':capture.file_digest(dependency)}
        missing=self.base/'optional.sum';self.recipe['inputs'][str(missing)]={'absent':True}
        capture.go_inputs(self.recipe,self.source,self.original,self.root)
        missing.write_text('appeared')
        with self.assertRaisesRegex(ValueError,'absent input'):capture.go_inputs(self.recipe,self.source,self.original,self.root)
        missing.unlink();dependency.write_text('changed')
        with self.assertRaisesRegex(ValueError,'loaded input changed'):capture.go_inputs(self.recipe,self.source,self.original,self.root)
        dependency.write_text('package dependency')
        for name,identity in [('relative',{'sha256':'0'*64}),(str(dependency),{'sha256':'bad'}),(str(dependency),{'absent':False})]:
            recipe=copy.deepcopy(self.recipe);recipe['inputs'][name]=identity
            with self.subTest(identity=identity),self.assertRaises(ValueError):capture.go_inputs(recipe,self.source,self.original,self.root)

    def test_resolved_build_policy_is_bound_to_selection_annotations_and_traces(self):
        self.create_bundle();requested={'functions':{'include':['app.selected']},'traces':{'enabled':True}}
        capture.go_plan(self.bundle,requested)
        for field,value in [('schema_version',True),('backend','source'),('sources',{}),('functions',{'include':['other'],'exclude':[]}),('annotations',{}),('traces',[]),('traces',{'enabled':False})]:
            candidate={**self.resolved,field:value};(self.bundle/'plan.json').write_text(json.dumps(candidate))
            with self.subTest(field=field),self.assertRaises(ValueError):capture.go_plan(self.bundle,requested)

    def test_empty_ambiguous_or_unbound_module_graphs_cannot_qualify(self):
        self.create_bundle();capture.go_graphs(self.root,self.bundle)
        settings={'Go':'1.27.2'}
        controls=[{'Settings':settings,'Modules':{}},{'Settings':settings,'Modules':{'fixture':{'Path':'wrong','Main':True}}},
                  {'Settings':settings,'Modules':{'fixture':{'Path':'fixture','Main':False}}},
                  {'Settings':settings,'Modules':{'fixture':{'Path':'fixture','Main':True},'other':{'Path':'other','Main':True}}},
                  {'Settings':{},'Modules':self.graph['Modules']}]
        for graph in controls:
            (self.bundle/'modules-original.json').write_text(json.dumps(graph))
            with self.subTest(graph=graph),self.assertRaises(ValueError):capture.go_graphs(self.root,self.bundle)
        (self.bundle/'modules-original.json').write_text(json.dumps(self.graph))
        (self.bundle/'modules-instrumented.json').write_text(json.dumps(self.graph))
        with self.assertRaisesRegex(ValueError,'SDK module'):capture.go_graphs(self.root,self.bundle)
        changed=copy.deepcopy(self.on_graph);changed['Settings']['Go']='1.26.0'
        (self.bundle/'modules-instrumented.json').write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError,'defaults changed'):capture.go_graphs(self.root,self.bundle)

    def test_compiler_environment_protocol_and_failures_remain_build_errors(self):
        for value in ([],{},dict(self.env,GOTOOLDIR='relative'),dict(self.env,GOARCH=7)):
            result=subprocess.CompletedProcess([],0,json.dumps(value).encode(),b'compiler diagnostic')
            with self.subTest(value=value),patch.object(capture,'execute',return_value=result),self.assertRaises(ValueError):
                capture.go_compiler(self.project,self.tools,{},self.evidence)
        result=subprocess.CompletedProcess([],1,b'',b'failure')
        with patch.object(capture,'execute',return_value=result),self.assertRaisesRegex(ValueError,'environment failed'):
            capture.go_compiler(self.project,self.tools,{},self.evidence)
        self.assertEqual((self.evidence/'go-compiler.stderr').read_bytes(),b'failure')

    def test_reused_cache_roots_cannot_redirect_writes_into_application_sources(self):
        (self.base/'go-cache').symlink_to(self.project,target_is_directory=True)
        with patch.object(capture,'execute') as execute,patch.object(capture,'build') as build:
            with self.assertRaisesRegex(ValueError,'cache location'):
                capture.go_commands(self.root,self.project,self.source,self.policy,self.tools,{},self.evidence)
        execute.assert_not_called();build.assert_not_called()
        (self.base/'go-cache').unlink()
        for location in (self.source,self.project/'cache',self.root/'cache'):
            with self.subTest(location=location),self.assertRaises(ValueError):
                capture.go_caches(self.root,self.project,{'GOCACHE':str(location)},self.evidence)

    def test_valid_new_builds_with_changed_dependency_or_compiler_bytes_refuse(self):
        self.create_bundle()
        first=capture.go_dependency_identity(self.recipe,self.compiler,self.project,self.evidence)
        other=self.base/'second project';other.mkdir()
        recipe=copy.deepcopy(self.recipe)
        recipe['inputs'].pop(str(self.source));recipe['inputs'][str(other/'app.go')]={'sha256':self.original}
        self.assertEqual(capture.go_dependency_identity(recipe,self.compiler,other,self.evidence),first)
        recipe['inputs'][str(self.root/'adapters/go/go.mod')]={'sha256':'0'*64}
        with self.assertRaisesRegex(ValueError,'changed between attempts'):
            capture.go_dependency_identity(recipe,self.compiler,other,self.evidence)
        with self.assertRaisesRegex(ValueError,'changed between attempts'):
            capture.go_dependency_identity(self.recipe,{**self.compiler,'sha256':'0'*64},self.project,self.evidence)


if __name__=='__main__':unittest.main()
