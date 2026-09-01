from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from bibliometrics import __version__
from bibliometrics.application.models import WorkflowOptions, WorkflowPaths
from bibliometrics.cli import build_parser
from bibliometrics.pipeline.workflow import AIWorkflow


class WorkflowModelTests(unittest.TestCase):
    def test_parse_year_range(self) -> None:
        options = WorkflowOptions(data_dir="Example", year_range="2015-2024")
        self.assertEqual(options.parse_year_range(), (2015, 2024))

    def test_build_paths(self) -> None:
        paths = WorkflowPaths.for_data_dir("Example", "English")
        self.assertEqual(paths.wos_file.name, "wos.txt")
        self.assertEqual(paths.filtered_file.name, "english_only.txt")


class CliTests(unittest.TestCase):
    def test_parser_defaults(self) -> None:
        args = build_parser().parse_args(["--data-dir", "Example"])
        self.assertEqual(args.language, "English")
        self.assertFalse(args.no_ai)
        self.assertFalse(args.no_cleaning)


class CompatibilityTests(unittest.TestCase):
    def test_pipeline_workflow_reexport(self) -> None:
        workflow = AIWorkflow(data_dir="Example", enable_ai=False, enable_plot=False)
        self.assertEqual(workflow.language, "English")

    def test_version_matches_pyproject(self) -> None:
        """`__version__` 与 pyproject.toml 必须同步——发版时最容易漏改其中一处。"""
        pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        declared = re.search(r'^version = "([^"]+)"', pyproject, re.M)
        self.assertIsNotNone(declared, "pyproject.toml 中未找到 version 字段")
        self.assertEqual(__version__, declared.group(1))


if __name__ == "__main__":
    unittest.main()
