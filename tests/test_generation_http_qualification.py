"""Http qualification uses the shared evidence identity cases."""
import unittest

import effect_qualification_cases as shared
import qualify_http


class HttpQualificationTests(shared.EffectQualificationCases, unittest.TestCase):
    qualification = qualify_http.qualification


if __name__ == "__main__":
    unittest.main()
