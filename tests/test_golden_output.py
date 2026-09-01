"""Golden-file 回归：锁定 ``Example`` 数据集在 ``--no-ai`` 下的完整输出。

这一层的作用是把"输出零回归"从人工 md5 比对变成自动断言。任何改动只要让最终数据
产物或统计报告发生变化，都会在这里失败；字段计数的差异会被逐条列出，直接指向问题
所在的字段。

若改动确实是预期的，用 ``python3 scripts/update_golden.py`` 重建基线，并在提交里说清
楚输出为什么变。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _golden  # noqa: E402


UPDATE_HINT = "如果这是预期改动，运行 python3 scripts/update_golden.py 重建基线。"


class GoldenOutputTests(unittest.TestCase):
    """在临时目录跑一遍完整流程，与 tests/golden/expected.json 比对。"""

    expected: dict
    actual: dict

    @classmethod
    def setUpClass(cls) -> None:
        missing = _golden.missing_inputs()
        if missing:
            raise unittest.SkipTest(f"缺少示例输入文件: {', '.join(missing)}")
        if not _golden.GOLDEN_FILE.exists():
            raise unittest.SkipTest(
                f"基线文件不存在: {_golden.GOLDEN_FILE}（先运行 scripts/update_golden.py）"
            )

        cls.expected = dict(_golden.load_expected())

        cls._tmp = tempfile.TemporaryDirectory(prefix="bibliometrics-golden-")
        cls.actual = _golden.build_snapshot_in_tempdir(Path(cls._tmp.name))

    @classmethod
    def tearDownClass(cls) -> None:
        tmp = getattr(cls, "_tmp", None)
        if tmp is not None:
            tmp.cleanup()

    def test_inputs_match_baseline(self) -> None:
        """基线是针对特定输入建立的——输入变了，下面的产物断言就没有意义。"""
        for name, expected_hash in self.expected["inputs"].items():
            with self.subTest(input=name):
                self.assertEqual(
                    self.actual["inputs"].get(name),
                    expected_hash,
                    f"示例输入 {name} 已改变，基线需要重建。{UPDATE_HINT}",
                )

    def test_wos_artifacts_unchanged(self) -> None:
        """WOS 风格数据产物：记录数、字段覆盖与逐字节内容都不得变化。"""
        for name in _golden.WOS_ARTIFACTS:
            expected = self.expected["outputs"][name]
            actual = self.actual["outputs"][name]

            with self.subTest(artifact=name):
                self.assertNotIn("missing", actual, f"产物缺失: {name}")

                self.assertEqual(
                    actual["records"],
                    expected["records"],
                    f"{name} 记录数变化: {expected['records']} -> {actual['records']}。{UPDATE_HINT}",
                )

                field_diff = _golden.describe_field_diff(expected["fields"], actual["fields"])
                self.assertEqual(
                    [],
                    field_diff,
                    f"{name} 字段计数变化:\n" + "\n".join(field_diff) + f"\n  {UPDATE_HINT}",
                )

                self.assertEqual(
                    actual["sha256"],
                    expected["sha256"],
                    f"{name} 内容已变化（记录数与字段计数相同，差异在字段取值内部）。{UPDATE_HINT}",
                )

    def test_reports_unchanged(self) -> None:
        """统计报告：规范化掉路径与耗时后，内容不得变化。"""
        for name in _golden.REPORT_ARTIFACTS:
            expected = self.expected["outputs"][name]
            actual = self.actual["outputs"][name]

            with self.subTest(artifact=name):
                self.assertNotIn("missing", actual, f"报告缺失: {name}")
                self.assertEqual(
                    actual["sha256_normalized"],
                    expected["sha256_normalized"],
                    f"{name} 内容已变化（行数 {expected['lines']} -> {actual['lines']}）。{UPDATE_HINT}",
                )

    def test_no_artifact_left_unchecked(self) -> None:
        """基线里的产物清单必须和代码里的清单一致，避免新增产物悄悄脱离校验。"""
        self.assertEqual(
            sorted(self.expected["outputs"]),
            sorted(_golden.WOS_ARTIFACTS + _golden.REPORT_ARTIFACTS),
            f"基线产物清单与 _golden.py 中的清单不一致。{UPDATE_HINT}",
        )


if __name__ == "__main__":
    unittest.main()
