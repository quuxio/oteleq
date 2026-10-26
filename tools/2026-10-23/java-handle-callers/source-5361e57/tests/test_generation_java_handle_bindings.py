"""Handle bindings must match caller intent as well as frozen class products."""

import copy
import hashlib
import json
import unittest

import test_generation_java_action_bindings as direct
import java_action_bindings as bindings
import java_witness as witness

PROFILE = witness.HANDLE_PROFILE
ROUTE_KEYS = ("kind", "field_owner", "field_name", "field_descriptor", "site_instruction",
              "invoke_owner", "invoke_name", "invoke_descriptor", "reference_kind")


def route_digest(route, roles):
    fields = [PROFILE, *(str(route[key]) for key in ROUTE_KEYS),
              roles["wrapper"]["probe_id"], roles["target"]["probe_id"]]
    return hashlib.sha256("\n".join(fields).encode()).hexdigest()


def document(expected, class_sha, *, kind=5):
    value = direct.document(expected, class_sha, profile=PROFILE)
    route = {"kind": "direct_method_handle", "field_owner": expected["wrapper"]["owner"],
             "field_name": "HANDLE", "field_descriptor": "Ljava/lang/invoke/MethodHandle;",
             "site_instruction": 0, "invoke_owner": "java/lang/invoke/MethodHandle",
             "invoke_name": "invokeExact", "invoke_descriptor": expected["wrapper"]["descriptor"],
             "reference_kind": kind}
    route["sha256"] = route_digest(route, value["bindings"])
    value["route"] = route
    return value


class JavaHandleBindingTests(unittest.TestCase):
    def setUp(self):
        direct.JavaActionBindingsTests.setUp(self)
        for role in ("wrapper", "envelope"):
            self.expected[role]["descriptor"] = "(LWork;I)I"
        self.route = bindings.HandleRoute("HANDLE", 5)
        self.value = document(self.expected, self.class_sha)

    def verify(self, value, *, expected=None, route=None):
        return bindings.verify(value, self.expected if expected is None else expected,
                               self.application, self.classes, profile=PROFILE,
                               route=self.route if route is None else route)

    def test_explicit_instance_static_wide_and_void_routes(self):
        for kind, target in ((5, "(I)I"), (6, "(JD)D"), (5, "([JLjava/lang/String;)V"), (6, "()V")):
            expected = direct.declarations()
            expected["target"]["descriptor"] = target
            signature = target if kind == 6 else "(LWork;" + target[1:]
            for role in ("wrapper", "envelope"):expected[role]["descriptor"] = signature
            value = document(expected, self.class_sha, kind=kind)
            route = bindings.HandleRoute("HANDLE", kind)
            with self.subTest(kind=kind, target=target):
                self.assertEqual(self.verify(value, expected=expected, route=route), value)

    def test_profile_and_independent_route_are_never_inferred(self):
        with self.assertRaises(ValueError):
            bindings.verify(self.value, self.expected, self.application, self.classes)
        with self.assertRaises(ValueError):
            bindings.verify(self.value, self.expected, self.application, self.classes, profile=PROFILE)
        ordinary = direct.document(self.expected, self.class_sha)
        with self.assertRaises(ValueError):self.verify(ordinary)
        with self.assertRaises(ValueError):bindings.selected_route(witness.PROFILE, self.route)
        for profile in (None, "future", True):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                bindings.selected_route(profile, self.route)
        with self.assertRaises(ValueError):
            direct.JavaActionBindingsTests.compile(self, profile=PROFILE, audits=0)
        self.assertFalse((self.root / "bindings").exists())

    def test_each_closed_route_field_and_its_type_must_match_the_caller(self):
        for key in self.value["route"]:
            changed = copy.deepcopy(self.value);del changed["route"][key]
            with self.subTest(missing=key), self.assertRaises(ValueError):self.verify(changed)
        edits = (("kind", "reflection"), ("field_owner", "Other"), ("field_name", "OTHER"),
                 ("field_descriptor", "Ljava/lang/Object;"), ("site_instruction", False),
                 ("site_instruction", 1), ("invoke_owner", "Other"), ("invoke_name", "invoke"),
                 ("invoke_descriptor", "(I)I"), ("reference_kind", 6), ("sha256", "0" * 64), ("extra", 1))
        for key, replacement in edits:
            changed = copy.deepcopy(self.value);changed["route"][key] = replacement
            with self.subTest(key=key), self.assertRaises(ValueError):self.verify(changed)
        for value in (None, [], True):
            changed = {**self.value, "route": value}
            with self.assertRaises(ValueError):self.verify(changed)

    def test_rehashed_producer_changes_cannot_replace_caller_intent(self):
        for key, replacement in (("field_name", "OTHER"), ("field_owner", "Other"),
                                 ("reference_kind", 6), ("invoke_descriptor", "(I)I")):
            changed = copy.deepcopy(self.value);changed["route"][key] = replacement
            changed["route"]["sha256"] = route_digest(changed["route"], changed["bindings"])
            with self.subTest(key=key), self.assertRaises(ValueError):self.verify(changed)
        changed = copy.deepcopy(self.value)
        changed["bindings"]["target"]["probe_id"] = direct.document(self.expected, self.class_sha)["bindings"]["target"]["probe_id"]
        with self.assertRaises(ValueError):self.verify(changed)

    def test_expected_route_field_and_jvm_slot_limits_are_checked(self):
        for field, kind in ((None, 5), ("", 5), ("x.y", 5), ("bad\n", 6),
                            ("<init>", 5), ("HANDLE", True), ("HANDLE", 7)):
            with self.subTest(field=field, kind=kind), self.assertRaises(ValueError):bindings.HandleRoute(field, kind)
        for slots in (254, 255):
            expected = direct.declarations();signature = "(" + "I" * slots + ")I"
            for role in ("wrapper", "envelope", "target"):expected[role]["descriptor"] = signature
            value = document(expected, self.class_sha, kind=6)
            route = bindings.HandleRoute("HANDLE", 6)
            if slots == 254:
                self.verify(value, expected=expected, route=route)
            else:
                with self.assertRaises(ValueError):
                    self.verify(value, expected=expected, route=route)
        route = bindings.HandleRoute("HANDLE", 6)
        with self.assertRaises(ValueError):self.verify(self.value, route=route)

    def test_actual_bridge_keeps_explicit_profile_and_requested_handle(self):
        result = direct.JavaActionBindingsTests.compile(self, profile=PROFILE, route=self.route)
        self.assertEqual(result, self.value)
        record = json.loads((self.root / "bindings/compiler-inputs.json").read_text())
        self.assertEqual(record["profile"], PROFILE)
        self.assertEqual(record["expected_handle"], {"field_name": "HANDLE", "reference_kind": 5})
        self.assertEqual(record["argv"][7], PROFILE)
        self.assertEqual(record["bindings_sha256"], hashlib.sha256((self.root / "bindings/bindings.json").read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
