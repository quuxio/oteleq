"""Keep Go qualification controls focused and retain observed termination."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import qualify_go_builds as qualification


class GoQualificationTests(unittest.TestCase):
    def test_binary_tamper_control_changes_only_its_readonly_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);original=root/'original';original.mkdir()
            (original/'application').write_bytes(b'original executable');(original/'application').chmod(0o500)
            copied=root/'copy';shutil.copytree(original,copied)
            qualification.changed_binary(copied)
            self.assertEqual((original/'application').read_bytes(),b'original executable')
            self.assertEqual((copied/'application').read_bytes(),b'changed')

    def test_empty_graph_control_preserves_settings_and_rehashes_only_changed_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary);settings={'Go':'1.27.2','Toolchain':'','Godebug':None}
            names=('modules-original.json','modules-instrumented.json')
            for name in names:(folder/name).write_text(json.dumps({'Settings':settings,'Modules':{'fixture':{'Main':True}}}))
            (folder/'build.json').write_text(json.dumps({'files':{'application':'unchanged'}}))
            qualification.empty_graphs(folder)
            manifest=json.loads((folder/'build.json').read_text())
            self.assertEqual(manifest['files']['application'],'unchanged')
            for name in names:
                data=json.loads((folder/name).read_text());self.assertEqual(data,{'Settings':settings,'Modules':{}})
                self.assertEqual(manifest['files'][name],qualification.hashlib.sha256((folder/name).read_bytes()).hexdigest())

    def test_actual_status_and_raw_bytes_are_retained_even_on_an_unexpected_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)
            result=subprocess.CompletedProcess([],17,b'\xff\x00',b'\x00')
            with patch.object(qualification.capture,'execute',return_value=result),self.assertRaises(AssertionError):
                qualification.execute_record(['selected'],folder,{},folder,'unexpected',1)
            self.assertEqual((folder/'unexpected.stdout').read_bytes(),b'\xff\x00')
            self.assertEqual((folder/'unexpected.stderr').read_bytes(),b'\x00')
            self.assertEqual(json.loads((folder/'unexpected.status.json').read_text()),{'returncode':17,'expected':1})


if __name__=='__main__':unittest.main()
