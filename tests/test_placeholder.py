"""Placeholder until real factory tests land.

Org CI: ``unittest discover -s tests`` (see antiphoria/.github qg-python-test).
"""

from __future__ import annotations

import unittest


class TestPlaceholder(unittest.TestCase):
    def test_repo_bootstrapped(self) -> None:
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
