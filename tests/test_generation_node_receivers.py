"""Real parser, source binding and receiver graph contracts for both Node IDs."""
import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'adapters/generation'),
                str(Path(__file__).resolve().parents[1] / 'examples')]
import generation as gen
import harness
import node_receivers
import policy
import shrinking
import typed_capture as typed

REPO = Path(__file__).resolve().parents[1]
NODE = os.environ.get('OTELC_NODE') or shutil.which('node')
SOURCE = '''export class Counter {
 static total=0;
 static shared=[];
 constructor(start){this.value=start;this.alias=this;this.shared=Counter.shared;}
 add(amount){this.value+=amount;Counter.total+=amount;Counter.shared.push(amount);return this;}
 async later(amount){await Promise.resolve();return this.add(amount);}
}
function make_counter(start){return new Counter(start);}
'''


class NodeReceiverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.provider = Path(cls.temporary.name)
        package = cls.provider/'adapters/node'
        package.mkdir(parents=True)
        (package/'package.json').write_text('{"private":true}')
        (package/'node_modules').mkdir()
        compiler = REPO/'ci/markdownlint/node_modules/typescript'
        if not compiler.is_dir():
            raise RuntimeError('run make setup: the pinned TypeScript parser is required for inventory regressions')
        (package/'node_modules/typescript').symlink_to(compiler,target_is_directory=True)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def parse(self, source=SOURCE, path='sample.mjs'):
        result = subprocess.run([NODE,REPO/'adapters/generation/discover.mjs',self.provider],
                                input=json.dumps({'filename':path,'source':source}).encode(),
                                capture_output=True,timeout=30,check=False)
        self.assertEqual(result.returncode,0,result.stderr)
        return json.loads(result.stdout)

    def candidate(self, folder, source=SOURCE, language='javascript', method='add', factory='Counter', arguments=None):
        path = 'sample.mts' if language == 'typescript' else 'sample.mjs'
        (folder/path).write_text(source)
        parsed = self.parse(source,path)
        parsed['entrypoints'] = []
        config = policy.validate({'languages':[language],'functions':{'include':['sample.Counter.'+method]},
                                  'fixtures':[{'function':'sample.Counter.'+method,'cases':[[7]],
                                               'receiver':{'factory':factory,'arguments':[10] if arguments is None else arguments},
                                               'domains':[{'kind':'integer','minimum':0,'maximum':7}]}]})
        function = next(item for item in parsed['functions'] if item['name']=='Counter.'+method)
        entry = gen.inventory_entry(function,parsed,path,language,'a'*64,folder,argparse.Namespace(configuration=config,cases=1))
        return entry,parsed,config

    def worker(self, folder, source=SOURCE, language='javascript', method='add', factory='Counter', arguments=None):
        entry,_,_ = self.candidate(folder,source,language,method,factory,arguments)
        self.assertEqual(entry['status'],'ready',entry['reason'])
        driver = harness.materialise(folder,entry,[7.0])
        path = folder/'observation.json'
        result = subprocess.run([NODE,driver],cwd=folder,env={**os.environ,'OTELEQ_OBSERVATION':str(path)},
                                capture_output=True,timeout=30,check=False)
        return entry,result,path

    def test_inventory_uses_class_qualified_names_constructor_types_and_utf8_offsets(self):
        source = '#!/usr/bin/env node\n"use strict";\nconst emoji="😀";\n'+SOURCE
        parsed = self.parse(source)
        entries = {item['name']:item for item in parsed['functions']}
        self.assertIn('Counter.constructor',entries)
        self.assertIn('Counter.add',entries)
        self.assertIn('Counter.later',entries)
        self.assertEqual(entries['Counter.constructor']['node_constructor_parameters'],['unknown'])
        self.assertTrue(entries['Counter.later']['async'])
        position = entries['Counter.add']['node_class_capture_offset']
        self.assertEqual(source.encode()[position-1:position],b'{')
        self.assertEqual([item['name'] for item in entries['Counter.add']['node_class_roots']],['total','shared'])
        self.assertEqual([item['name'] for item in parsed['globals']],['emoji'])

    def test_nested_closures_generators_and_destructured_globals_remain_accounted_for(self):
        parsed = self.parse('const [left,right]=[1,2];\nclass Counter { add(value){function inner(){return 1}return value;} *items(){yield 1;} }')
        entries = {item['name']:item for item in parsed['functions']}
        self.assertTrue(entries['Counter.add.inner']['reason'])
        self.assertIn('generator',entries['Counter.items']['reason'])
        self.assertEqual(parsed['globals'][0]['name'],'<destructured>')

    def test_private_accessor_inherited_generic_and_duplicate_class_forms_stay_blocked(self):
        sources = [SOURCE.replace('static total=0;','#hidden=0;'),
                   SOURCE.replace('static total=0;','get total(){return 0;}'),
                   SOURCE.replace('class Counter {','class Counter extends Object {'),
                   SOURCE.replace('class Counter {','class Counter<T> {'),
                   SOURCE.replace('static total=0;','private hidden=0;'),
                   SOURCE.replace('static total=0;','accessor total=0;'),
                   SOURCE.replace('static total=0;','["hidden"]=0;'),
                   SOURCE.replace('static total=0;','add(amount){return amount;}'),
                   SOURCE.replace('static total=0;','static total=0;static total=1;')]
        for source in sources:
            with self.subTest(source=source),tempfile.TemporaryDirectory() as temporary:
                entry,_,_ = self.candidate(Path(temporary),source,language='typescript')
                self.assertEqual(entry['status'],'blocked')
                self.assertTrue(entry['reason'])

    def test_both_languages_construct_instances_keep_aliases_and_require_declared_tags(self):
        for language in ('javascript','typescript'):
            source = (SOURCE.replace('constructor(start)', 'constructor(start:number)')
                      .replace('make_counter(start)', 'make_counter(start:number)')
                      .replace('add(amount){', 'add(amount:number){')
                      .replace('later(amount){', 'later(amount:number){')) if language=='typescript' else SOURCE
            with self.subTest(language=language),tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                entry,result,path = self.worker(folder,source,language)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(result.stdout,b'')
                raw = json.loads(path.read_text())
                with self.assertRaisesRegex(ValueError,'unsupported prototype'):
                    typed.dynamic_graph(raw['after'],language)
                graph = typed.dynamic_graph(raw['outcome']['value'],language,(node_receivers.prototype_label(entry),))
                receiver = graph['roots']['receiver']
                self.assertEqual(graph['roots']['result'],receiver)
                node = next(item for item in graph['nodes'] if item['id']==receiver['node_id'])
                self.assertEqual(node['fields']['property:alias'],receiver)
                self.assertIn('static:Counter.total',typed.required_roots(entry))
                value = node['fields']['property:value']['bits']
                self.assertEqual(struct.unpack('>d',bytes.fromhex(value))[0],17)

    def test_existing_factory_and_awaited_method_reconstruct_the_receiver(self):
        with tempfile.TemporaryDirectory() as temporary:
            entry,result,path = self.worker(Path(temporary),method='later',factory='make_counter')
            self.assertEqual(entry['receiver_fixture']['kind'],'function')
            self.assertEqual(result.returncode,0,result.stderr)
            raw = json.loads(path.read_text())
            self.assertEqual(raw['outcome']['kind'],'return')
            self.assertEqual(raw['outcome']['value']['roots']['result'],raw['outcome']['value']['roots']['receiver'])

    def test_implicit_constructor_needs_no_application_factory(self):
        source = 'class Counter {value=10;add(amount){this.value+=amount;return this.value;}}'
        with tempfile.TemporaryDirectory() as temporary:
            entry,result,path = self.worker(Path(temporary),source,arguments=[])
            self.assertIsNone(entry['receiver_fixture']['source_function'])
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(path.read_text())['outcome']['kind'],'return')

    def test_class_capture_precedes_original_static_initialisers_and_factory_rebinding(self):
        controls = [(SOURCE.replace('static total=0;','static total=(Counter.prototype.add=()=>7,0);'),'Counter'),
                    (SOURCE+'make_counter=()=>({});\n','make_counter')]
        for source,factory in controls:
            with self.subTest(factory=factory),tempfile.TemporaryDirectory() as temporary:
                _,result,path = self.worker(Path(temporary),source,factory=factory)
                self.assertNotEqual(result.returncode,0)
                self.assertIn(b'binding changed',result.stderr)
                self.assertFalse(path.exists())

    def test_module_class_or_factory_rebinding_inside_construction_and_call_refuses(self):
        controls = [SOURCE.replace('return new Counter(start);','const result=new Counter(start);Counter=class Other{};return result;'),
                    SOURCE.replace('return new Counter(start);','const result=new Counter(start);make_counter=()=>result;return result;'),
                    SOURCE.replace('this.value+=amount;','change_class();this.value+=amount;')+'function change_class(){Counter=class Other{};}\n']
        for source in controls:
            with self.subTest(source=source),tempfile.TemporaryDirectory() as temporary:
                _,result,path = self.worker(Path(temporary),source,factory='make_counter')
                self.assertNotEqual(result.returncode,0)
                self.assertIn(b'binding changed',result.stderr)
                self.assertFalse(path.exists())

    def test_constructor_return_overrides_require_an_allocation_fixture(self):
        for expression in ('new Date()','{}','Object.create(Counter.prototype)'):
            source=SOURCE.replace('this.value=start;',f'return {expression};this.value=start;')
            with self.subTest(expression=expression),tempfile.TemporaryDirectory() as temporary:
                entry,_,_=self.candidate(Path(temporary),source)
                self.assertEqual(entry['status'],'blocked')
                self.assertIn('allocation fixture',entry['reason'])
        source=SOURCE.replace('this.value=start;','const nested=()=>{return {};};this.value=start;').replace('this.shared=Counter.shared;','this.shared=Counter.shared;return this;')
        with tempfile.TemporaryDirectory() as temporary:
            entry,_,_=self.candidate(Path(temporary),source)
            self.assertEqual(entry['status'],'ready',entry['reason'])

    def test_proxy_wrong_class_and_opaque_own_state_refuse_observations(self):
        controls = [SOURCE.replace('return new Counter(start);','return {};'),
                    SOURCE.replace('return new Counter(start);','return new Proxy(new Counter(start),{});'),
                    SOURCE.replace('this.value=start;','this.add=7;this.value=start;'),
                    SOURCE.replace('return new Counter(start);','return Object.setPrototypeOf([],Counter.prototype);'),
                    SOURCE.replace('this.value=start;','this.value=new Date();')]
        for source in controls:
            with self.subTest(source=source),tempfile.TemporaryDirectory() as temporary:
                _,result,path = self.worker(Path(temporary),source,factory='make_counter')
                self.assertNotEqual(result.returncode,0)
                self.assertFalse(path.exists())

    def test_missing_ambiguous_async_and_invalid_factory_inputs_are_blocked(self):
        controls = [(SOURCE,'missing',[10]),(SOURCE,'Counter',[]),
                    (SOURCE.replace('function make_counter','async function make_counter'),'make_counter',[10]),
                    (SOURCE+'function make_counter(start){return new Counter(start);}\n','make_counter',[10])]
        for source,factory,arguments in controls:
            with self.subTest(factory=factory),tempfile.TemporaryDirectory() as temporary:
                entry,_,_ = self.candidate(Path(temporary),source,factory=factory,arguments=arguments)
                self.assertEqual(entry['status'],'blocked')

    def test_receiver_shrink_plan_keeps_factory_inputs_and_method_domains(self):
        with tempfile.TemporaryDirectory() as temporary:
            entry,_,config = self.candidate(Path(temporary))
            entry['id']='target'
            original={'configuration':config,'configuration_sha256':gen.identity(config),'inventory':[entry]}
            case=gen.generation_case(entry,0,[7.0])
            derived=shrinking.derived_data(gen,original,entry,case)
            self.assertEqual(derived['configuration']['fixtures'][0]['receiver'],config['fixtures'][0]['receiver'])
            self.assertEqual(policy.validate(derived['configuration']),derived['configuration'])
            self.assertEqual(derived['inventory'][0]['receiver_fixture']['arguments'],[10.0])
            changed=copy.deepcopy(case);changed['receiver_fixture']['arguments']=[11.0]
            self.assertNotEqual(gen.identity(case),gen.identity(changed))

    def test_invalid_parser_input_and_capture_offsets_do_not_run_application_code(self):
        result = subprocess.run([NODE,REPO/'adapters/generation/discover.mjs',self.provider],
                                input=json.dumps({'filename':'bad.mjs','source':'class {'}).encode(),capture_output=True,check=False)
        self.assertNotEqual(result.returncode,0)
        with tempfile.TemporaryDirectory() as temporary:
            entry,_,_ = self.candidate(Path(temporary))
            entry['node_class_capture_offset']=len(SOURCE.encode())+1
            with self.assertRaisesRegex(ValueError,'offset'):
                node_receivers.driver(entry,[7],SOURCE)


if __name__=='__main__':
    unittest.main()
