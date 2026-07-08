from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from bibliometrics.utils.wos_text import split_wos_records
from bibliometrics.pipeline.merge import RecordMatcher, _safe_int
from bibliometrics.standardizers.institutions import InstitutionCleaner


RAW_EXPORT = (
    "FN Clarivate Analytics Web of Science\n"
    "VR 1.0\n"
    "PT J\nTI First record\nER\n"
    "\n"
    "PT J\nTI Second record\nER\n"
    "EF"
)

TOOL_OUTPUT = (
    "FN Clarivate Analytics Web of Science\n"
    "VR 1.0\n"
    "\n"
    "PT J\nTI First record\nER\n"
    "\n"
    "PT J\nTI Second record\nER\n"
    "\nEF"
)


class SplitWosRecordsTests(unittest.TestCase):
    def test_raw_export_keeps_first_record(self) -> None:
        """WOS 原始导出 header 后无空行——旧 split('\\n\\nPT ') 会丢首条。"""
        records = split_wos_records(RAW_EXPORT)
        self.assertEqual(len(records), 2)
        self.assertIn("First record", records[0])

    def test_tool_output_unchanged(self) -> None:
        records = split_wos_records(TOOL_OUTPUT)
        self.assertEqual(len(records), 2)
        self.assertIn("First record", records[0])

    def test_headerless_content(self) -> None:
        records = split_wos_records("PT J\nTI Only record\nER\n\nEF")
        self.assertEqual(len(records), 1)
        self.assertIn("Only record", records[0])


class SafeIntTests(unittest.TestCase):
    def test_dirty_tc_values(self) -> None:
        self.assertEqual(_safe_int("12"), 12)
        self.assertEqual(_safe_int(" 12 "), 12)
        self.assertEqual(_safe_int("N/A"), 0)
        self.assertEqual(_safe_int(""), 0)
        self.assertEqual(_safe_int(None), 0)


class RecordMatcherTests(unittest.TestCase):
    def test_doi_match(self) -> None:
        r1 = {"DI": "10.1000/x", "TI": "A", "PY": "2020", "AU": "Smith, J"}
        r2 = {"DI": "10.1000/X", "TI": "B", "PY": "2021", "AU": "Doe, J"}
        self.assertTrue(RecordMatcher.is_duplicate(r1, r2))

    def test_title_year_author_match(self) -> None:
        r1 = {"TI": "A Long Enough Title About Dermatology", "PY": "2020", "AU": "Smith, J"}
        r2 = {"TI": "A long enough title about dermatology", "PY": "2020", "AU": "smith, j"}
        self.assertTrue(RecordMatcher.is_duplicate(r1, r2))

    def test_year_mismatch_not_duplicate(self) -> None:
        r1 = {"TI": "A Long Enough Title About Dermatology", "PY": "2020", "AU": "Smith, J"}
        r2 = {"TI": "A Long Enough Title About Dermatology", "PY": "2021", "AU": "Smith, J"}
        self.assertFalse(RecordMatcher.is_duplicate(r1, r2))

    def test_precomputed_keys_agree_with_is_duplicate(self) -> None:
        r1 = {"TI": "Some Title That Is Long Enough Here", "PY": "2020", "AU": "Smith, J"}
        r2 = {"TI": "Some Title That Is Long Enough Here Extended", "PY": "2020", "AU": "Smith, J"}
        k1 = RecordMatcher.precompute_match_keys(r1)
        k2 = RecordMatcher.precompute_match_keys(r2)
        self.assertEqual(
            RecordMatcher.match_keys_duplicate(k1, k2),
            RecordMatcher.is_duplicate(r1, r2),
        )


class CompanySuffixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cleaner = InstitutionCleaner.__new__(InstitutionCleaner)
        self.cleaner.rules = {
            "company_suffixes_to_remove": [" ag$", " inc\\.?$", " ltd\\.?$", " sa$", " co\\.$"]
        }

    def test_regex_suffix_removed(self) -> None:
        self.assertEqual(
            self.cleaner.remove_company_suffix("Systems Trichology London Ltd"),
            "Systems Trichology London",
        )
        self.assertEqual(self.cleaner.remove_company_suffix("Acme Inc."), "Acme")

    def test_word_boundary_protects_names(self) -> None:
        """' sa$' 不得把 'Univ Pisa' 截成 'Univ Pi'（旧实现的破坏性 bug）。"""
        self.assertEqual(self.cleaner.remove_company_suffix("Univ Pisa"), "Univ Pisa")
        self.assertEqual(self.cleaner.remove_company_suffix("Cornell University"), "Cornell University")


if __name__ == "__main__":
    unittest.main()
