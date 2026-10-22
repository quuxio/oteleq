"""Source SDK effect qualification binds concrete fixtures and opaque identities."""

from pathlib import Path
import subprocess
import sys
import tomllib
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qualify_node_source_effects as qualifier


class NodeSourceEffectsTests(unittest.TestCase):
    def test_replay_verdict_uses_inventory_binding_instead_of_the_opaque_id(self):
        inventory = [{"id": "1234", "otelc_function": "effects.selected_difference"},
                     {"id": "selected_difference", "otelc_function": "effects.selected_match"}]
        self.assertTrue(qualifier.replay_difference({"function_id": "1234"}, inventory))
        self.assertFalse(qualifier.replay_difference({"function_id": "selected_difference"}, inventory))
        with self.assertRaisesRegex(ValueError, "unexpected"):
            qualifier.replay_difference({"function_id": "other"}, [{"id": "other", "otelc_function": "effects.other"}])
        with self.assertRaises(KeyError):
            qualifier.replay_difference({"function_id": "missing"}, inventory)

    def test_fixed_policy_declares_both_required_effects_and_scalar_cases(self):
        for language in ("javascript", "typescript"):
            for compiler in ("native", "api"):
                value = tomllib.loads(qualifier.policy(language, compiler))
                self.assertEqual(value["languages"], [language])
                self.assertEqual(value["adapters"]["node"], {"backend": "source-v1", "typescript_compiler": compiler})
                self.assertEqual([item["cases"] for item in value["fixtures"]], [[[7]], [[7]]])
                self.assertEqual(value["effects"]["filesystem"][0]["files"], [{"path": "seed.bin", "hex": "00ff", "mode": 0o600}])
                self.assertEqual(value["effects"]["http"][0]["min_requests"], 1)
                self.assertEqual(value["effects"]["http"][0]["responses"], [{"status": 201, "hex": "00ff"}])
        self.assertEqual(qualifier.graph(7, 2, 16)["roots"]["result"], qualifier.number(16))

    def test_optimisation_cannot_remove_the_qualification_assertions(self):
        result = subprocess.run([sys.executable, "-B", "-O", qualifier.__file__, "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("disable -O/PYTHONOPTIMIZE", result.stderr)


if __name__ == "__main__":
    unittest.main()
