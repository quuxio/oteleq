"""Generated Go callers retain the common bundle identities for each lane."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'adapters/generation'),str(Path(__file__).resolve().parents[1]/'examples')]
import generation as gen


class GeneratedGoBuildTests(unittest.TestCase):
    def test_each_lane_retains_the_pair_identity_and_uses_no_build_launch(self):
        for lane,expected in [('baseline','plain'),('instrumented_on','on')]:
            with self.subTest(lane=lane),tempfile.TemporaryDirectory() as temporary:
                folder=Path(temporary)
                identity={'baseline':'a'*64,'application':'b'*64,'compiler':{'version':'qualified'}}
                def commands(*_):
                    (folder/'go-build-identities.json').write_text(json.dumps(identity))
                    return ['plain'],['on']
                execute=gen.capture.execute
                with patch.object(gen.capture,'commands',side_effect=commands):
                    command=gen.build_command(folder,folder,{'language':'go'},folder/'app.go',folder/'policy',{}, {},folder,folder,lane)
                self.assertEqual(command,[expected])
                self.assertEqual(json.loads((folder/gen.BUILD_IDENTITIES).read_text()),identity)
                self.assertIs(gen.capture.execute,execute)


if __name__=='__main__':unittest.main()
