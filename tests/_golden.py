"""Golden-file 回归基线的共享逻辑。

被 ``tests/test_golden_output.py``（校验）与 ``scripts/update_golden.py``（更新）复用。

基线由两部分构成：

- **WOS 风格数据产物**：记录整份文件的 sha256，外加"字段指纹"——记录条数以及每个
  WOS 字段标签在多少条记录中出现。哈希能发现任何改动，字段指纹则直接指出改动落在
  哪里（少了几条记录、哪个字段整体消失），这正是历史上两类静默数据丢失 bug 的形态。
- **报告类产物**：报告正文里含有数据目录路径和运行耗时，先规范化再取哈希。
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Dict, List, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from bibliometrics.utils.wos_text import split_wos_records  # noqa: E402

EXAMPLE_DIR = PROJECT_ROOT / "Example"
GOLDEN_FILE = Path(__file__).resolve().parent / "golden" / "expected.json"

#: 基线绑定的输入文件——输入变了，基线自然失效
INPUT_FILES = ("wos.txt", "scopus.csv")

#: WOS 风格数据产物：哈希 + 字段指纹
WOS_ARTIFACTS = (
    "scopus_converted_to_wos.txt",
    "scopus_enriched.txt",
    "merged_deduplicated.txt",
    "english_only.txt",
    "Final_Version.txt",
)

#: 报告类产物：规范化后取哈希
REPORT_ARTIFACTS = (
    "merged_deduplicated_report.txt",
    "english_only_filter_report.txt",
    "Final_Version_cleaning_report.txt",
    "Final_Version_analysis_report.txt",
    "ai_workflow_report.txt",
)

#: WOS 纯文本的字段行：两位标签后接空格或行尾（续行以三个空格缩进，不匹配）
_FIELD_TAG_PATTERN = re.compile(r"^([A-Z][A-Z0-9])(?: |$)")

#: 报告里的运行耗时随机器而变，规范化掉
_ELAPSED_PATTERN = re.compile(r"^(总耗时: )[0-9.]+(秒)$", re.MULTILINE)

DATA_DIR_PLACEHOLDER = "<DATA_DIR>"
ELAPSED_PLACEHOLDER = "<ELAPSED>"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize_report(text: str, data_dir: Path) -> str:
    """抹掉报告中随运行环境变化的内容（数据目录路径、总耗时）。"""
    normalized = text.replace(str(data_dir), DATA_DIR_PLACEHOLDER)
    return _ELAPSED_PATTERN.sub(rf"\1{ELAPSED_PLACEHOLDER}\2", normalized)


def field_fingerprint(text: str) -> Dict[str, object]:
    """统计 WOS 纯文本的记录条数与各字段的出现记录数。"""
    records = split_wos_records(text)
    field_counts: Dict[str, int] = {}

    for record in records:
        seen = set()
        for line in record.splitlines():
            match = _FIELD_TAG_PATTERN.match(line)
            if match:
                seen.add(match.group(1))
        for tag in seen:
            field_counts[tag] = field_counts.get(tag, 0) + 1

    return {
        "records": len(records),
        "fields": dict(sorted(field_counts.items())),
    }


def run_workflow(data_dir: Path) -> None:
    """在 ``data_dir`` 上跑一遍 ``--no-ai`` 全流程（不出图，输出静默）。"""
    from bibliometrics.application.workflow import AIWorkflow

    workflow = AIWorkflow(
        data_dir=str(data_dir),
        language="English",
        enable_ai=False,
        enable_cleaning=True,
        year_range=None,
        enable_plot=False,
    )
    with redirect_stdout(StringIO()):
        succeeded = workflow.run()

    if not succeeded:
        raise RuntimeError(f"工作流在 {data_dir} 上执行失败")


def prepare_data_dir(dest: Path) -> Path:
    """把 Example 的输入文件复制到 ``dest``，返回该目录。"""
    dest.mkdir(parents=True, exist_ok=True)
    for name in INPUT_FILES:
        shutil.copy2(EXAMPLE_DIR / name, dest / name)
    return dest


def missing_inputs() -> List[str]:
    return [name for name in INPUT_FILES if not (EXAMPLE_DIR / name).exists()]


def snapshot(data_dir: Path) -> Dict[str, object]:
    """把一次运行的产物汇总成可比对的快照。"""
    outputs: Dict[str, object] = {}

    for name in WOS_ARTIFACTS:
        path = data_dir / name
        if not path.exists():
            outputs[name] = {"missing": True}
            continue
        text = path.read_text(encoding="utf-8")
        entry = {"sha256": sha256_file(path)}
        entry.update(field_fingerprint(text))
        outputs[name] = entry

    for name in REPORT_ARTIFACTS:
        path = data_dir / name
        if not path.exists():
            outputs[name] = {"missing": True}
            continue
        normalized = normalize_report(path.read_text(encoding="utf-8"), data_dir)
        outputs[name] = {
            "sha256_normalized": sha256_text(normalized),
            "lines": len(normalized.splitlines()),
        }

    return {
        "inputs": {name: sha256_file(EXAMPLE_DIR / name) for name in INPUT_FILES},
        "outputs": outputs,
    }


def build_snapshot_in_tempdir(tmp_dir: Path) -> Dict[str, object]:
    """在临时目录跑一遍流程并返回快照。"""
    data_dir = prepare_data_dir(tmp_dir / "data")
    run_workflow(data_dir)
    return snapshot(data_dir)


def load_expected() -> Mapping[str, object]:
    return json.loads(GOLDEN_FILE.read_text(encoding="utf-8"))


def save_expected(payload: Mapping[str, object]) -> None:
    GOLDEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_FILE.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def describe_field_diff(expected: Mapping[str, int], actual: Mapping[str, int]) -> List[str]:
    """列出字段计数的差异，便于一眼看出哪个字段丢了。"""
    lines = []
    for tag in sorted(set(expected) | set(actual)):
        before = expected.get(tag, 0)
        after = actual.get(tag, 0)
        if before != after:
            lines.append(f"    {tag}: {before} -> {after}")
    return lines
