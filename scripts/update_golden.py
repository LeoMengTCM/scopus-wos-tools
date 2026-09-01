#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重建 golden-file 回归基线（tests/golden/expected.json）。

在临时目录上跑一遍 ``Example`` 的 ``--no-ai`` 全流程，把产物指纹写入基线文件。
运行前会先和现有基线比对并打印差异——**改动是否符合预期，需要你自己确认**，
确认无误再用 ``--yes`` 写入。
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "tests"))

import _golden  # noqa: E402


def summarize_changes(expected: dict, actual: dict) -> list[str]:
    """列出新旧基线之间的差异。"""
    lines: list[str] = []

    for name, old_hash in expected.get("inputs", {}).items():
        new_hash = actual["inputs"].get(name)
        if old_hash != new_hash:
            lines.append(f"  输入 {name}: {old_hash[:12]} -> {new_hash[:12]}")

    old_outputs = expected.get("outputs", {})
    for name, new_entry in actual["outputs"].items():
        old_entry = old_outputs.get(name)
        if old_entry is None:
            lines.append(f"  新增产物 {name}")
            continue

        if "records" in new_entry:
            if old_entry.get("records") != new_entry["records"]:
                lines.append(
                    f"  {name} 记录数: {old_entry.get('records')} -> {new_entry['records']}"
                )
            field_diff = _golden.describe_field_diff(
                old_entry.get("fields", {}), new_entry["fields"]
            )
            if field_diff:
                lines.append(f"  {name} 字段计数:")
                lines.extend(field_diff)
            if old_entry.get("sha256") != new_entry["sha256"]:
                lines.append(f"  {name} 内容哈希已变化")
        else:
            if old_entry.get("sha256_normalized") != new_entry.get("sha256_normalized"):
                lines.append(
                    f"  {name} 报告已变化（行数 {old_entry.get('lines')} -> {new_entry.get('lines')}）"
                )

    for name in old_outputs:
        if name not in actual["outputs"]:
            lines.append(f"  产物已移除 {name}")

    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="重建 golden 回归基线")
    parser.add_argument("--yes", action="store_true", help="确认差异符合预期，直接写入基线")
    args = parser.parse_args(argv)

    missing = _golden.missing_inputs()
    if missing:
        print(f"✗ 缺少示例输入文件: {', '.join(missing)}", file=sys.stderr)
        return 1

    print("正在临时目录上运行 Example --no-ai 全流程 ...")
    with tempfile.TemporaryDirectory(prefix="bibliometrics-golden-") as tmp:
        actual = _golden.build_snapshot_in_tempdir(Path(tmp))

    if _golden.GOLDEN_FILE.exists():
        expected = dict(_golden.load_expected())
        changes = summarize_changes(expected, actual)
        if not changes:
            print("✓ 与现有基线一致，无需更新。")
            return 0

        print("\n与现有基线的差异:")
        print("\n".join(changes))

        if not args.yes:
            print(
                "\n以上差异未写入。确认这些变化符合预期后，重新运行并加上 --yes。",
                file=sys.stderr,
            )
            return 1
    else:
        print(f"未找到现有基线，将新建: {_golden.GOLDEN_FILE}")

    _golden.save_expected(actual)
    print(f"\n✓ 基线已写入: {_golden.GOLDEN_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
