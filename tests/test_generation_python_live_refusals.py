"""Retained control mutations are isolated and cover separate obligations."""

import copy
import unittest

import python_live_qualification as oracle
import python_live_refusals


class PythonLiveRefusalTests(unittest.TestCase):
    def test_seven_control_variants_preserve_the_original_and_change_named_facts(self):
        for start in oracle.STARTS:
            record = {'pid': 101, 'steps': [
                {'requested': flags, 'before': {'history': [
                    {'response': {'collection': flags['collection']}}, {},
                    {'response': {'effective_emission_off': not flags['emission']}}]},
                 'after': {'held_ns': 1_000_000_000, 'settled': {'sdk_pid': 102}}}
                for flags in oracle.states(start)]}
            original = copy.deepcopy(record)
            variants = python_live_refusals.variants(record)
            self.assertEqual(record, original)
            self.assertEqual(set(variants), {'missing-step', 'wrong-application-pid', 'wrong-startup-collection',
                'short-disabled-window', 'wrong-live-sdk-pid', 'missing-export-drain-barrier', 'changed-requested-state'})
            self.assertTrue(all(value != record for value in variants.values()))
            self.assertEqual(len(variants['missing-step']['steps']), 4)
            self.assertEqual(variants['wrong-application-pid']['pid'], 102)
            self.assertEqual(variants['wrong-live-sdk-pid']['steps'][0]['after']['settled']['sdk_pid'], 103)
            self.assertEqual(variants['wrong-startup-collection']['steps'][0]['before']['history'][0]['response']['collection'],
                             not record['steps'][0]['requested']['collection'])
            off = next(row for row in variants['short-disabled-window']['steps'] if not all(row['requested'].values()))
            self.assertEqual(off['after']['held_ns'], 0)
