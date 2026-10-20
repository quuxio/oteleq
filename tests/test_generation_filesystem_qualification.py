"""Filesystem qualification uses the shared evidence identity cases."""
import unittest

import effect_qualification_cases as shared
import qualify_filesystem


class FilesystemQualificationTests(shared.EffectQualificationCases, unittest.TestCase):
    qualification = qualify_filesystem.qualification


if __name__ == "__main__":
    unittest.main()
