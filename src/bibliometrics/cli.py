from __future__ import annotations

import argparse
from typing import Optional, Sequence

from .application.workflow import AIWorkflow
from .logging_config import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="文献计量数据整合工作流",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 基本使用
  python3 run_ai_workflow.py --data-dir "/path/to/data"

  # 筛选中文文献
  python3 run_ai_workflow.py --data-dir "/path/to/data" --language Chinese

  # 禁用所有 AI 步骤（跳过 WOS 风格标准化与机构补全）
  python3 run_ai_workflow.py --data-dir "/path/to/data" --no-ai

  # 禁用机构清洗
  python3 run_ai_workflow.py --data-dir "/path/to/data" --no-cleaning

  # 过滤指定年份范围（如 2015-2024）
  python3 run_ai_workflow.py --data-dir "/path/to/data" --year-range 2015-2024

  # 使用自定义清洗规则
  python3 run_ai_workflow.py --data-dir "/path/to/data" --cleaning-config config/my_rules.json

  # 完整示例
  python3 run_ai_workflow.py \
      --data-dir "/path/to/data/My_Research_Project" \
      --language English \
      --log-level INFO

输入要求:
  数据目录必须包含:
  - wos.txt
  - scopus.csv

常见输出文件:
  - scopus_converted_to_wos.txt
  - scopus_enriched.txt（启用 AI 时）
  - merged_deduplicated.txt
  - english_only.txt 或其他语言筛选结果
  - Final_Version.txt（启用机构清洗时）
  - *_analysis_report.txt
  - ai_workflow_report.txt
        """,
    )

    parser.add_argument("--data-dir", required=True, help="数据目录（包含wos.txt和scopus.csv）")
    parser.add_argument("--language", default="English", help="目标语言（默认: English）")
    parser.add_argument("--no-ai", action="store_true", help="禁用所有AI步骤（WOS标准化 + 机构补全）")
    parser.add_argument("--no-cleaning", action="store_true", help="禁用机构清洗（默认启用）")
    parser.add_argument(
        "--cleaning-config",
        default="config/institution_cleaning_rules_ultimate.json",
        help="机构清洗规则配置文件（默认: 终极版规则）",
    )
    parser.add_argument("--year-range", help="年份范围过滤（格式: YYYY-YYYY，如2015-2024）")
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="日志级别",
    )
    return parser


def run_from_args(args: argparse.Namespace) -> int:
    configure_logging(args.log_level)
    workflow = AIWorkflow(
        data_dir=args.data_dir,
        language=args.language,
        enable_ai=not args.no_ai,
        enable_cleaning=not args.no_cleaning,
        cleaning_config=args.cleaning_config,
        year_range=args.year_range,
    )
    return 0 if workflow.run() else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return run_from_args(args)
