from __future__ import annotations

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

    def test_version_exposed(self) -> None:
        self.assertEqual(__version__, "5.1.0")


if __name__ == "__main__":
    unittest.main()
