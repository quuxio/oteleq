"""The channel qualifier requires non-UTF8 bytes and an output-only control."""

from pathlib import Path
import subprocess
import sys
import tomllib
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qualify_node_source_channels as qualifier


class NodeSourceChannelTests(unittest.TestCase):
    def test_literal_bytes_include_nul_and_non_utf8_with_a_separate_difference(self):
        self.assertEqual(qualifier.STDOUT, b"\0\xff\n")
        self.assertEqual(qualifier.STDERR, b"\x01\xff\n")
        for function in ("channels.selected_match", "channels.selected_difference"):
            self.assertEqual(qualifier.expected_stdout(function, "baseline"), qualifier.STDOUT)
        self.assertEqual(qualifier.expected_stdout("channels.selected_match", "instrumented_on"), qualifier.STDOUT)
        self.assertEqual(qualifier.expected_stdout("channels.selected_difference", "instrumented_on"), b"\0\xfe\n")
        with self.assertRaisesRegex(ValueError, "unknown"):
            qualifier.expected_stdout("unknown", "baseline")

    def test_policy_and_fixture_bind_actual_source_provider_and_fixed_inputs(self):
        for language in ("javascript", "typescript"):
            for compiler in ("native", "api"):
                value = tomllib.loads(qualifier.policy(language, compiler))
                self.assertEqual(value["adapters"]["node"], {"backend": "source-v1", "typescript_compiler": compiler})
                self.assertEqual([item["cases"] for item in value["fixtures"]], [[[7]], [[7]]])
            self.assertIn("/node-bootstrap.cjs", qualifier.fixture(language))
            self.assertIn("value:number" if language == "typescript" else "value)", qualifier.fixture(language))

    def test_optimisation_cannot_turn_the_qualification_into_an_unchecked_pass(self):
        result = subprocess.run([sys.executable, "-B", "-O", qualifier.__file__, "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("disable -O/PYTHONOPTIMIZE", result.stderr)


if __name__ == "__main__":
    unittest.main()
