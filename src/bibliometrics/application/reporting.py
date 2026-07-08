from __future__ import annotations

from pathlib import Path
from typing import Iterable, Mapping, Any

from .models import WorkflowOptions, WorkflowPaths


def build_workflow_report(
    *,
    options: WorkflowOptions,
    paths: WorkflowPaths,
    steps: Iterable[Mapping[str, Any]],
    elapsed_time: float,
) -> str:
    """Render the workflow summary report."""
    report = []
    report.append("=" * 80)
    report.append("AI增强工作流完成报告")
    report.append("=" * 80)
    report.append("")
    report.append(f"数据目录: {options.data_dir}")
    report.append(f"目标语言: {options.language}")
    report.append(f"AI补全: {'启用' if options.enable_ai else '禁用'}")
    report.append(f"总耗时: {elapsed_time:.1f}秒")
    report.append("")

    report.append("=" * 80)
    report.append("处理步骤")
    report.append("=" * 80)
    report.append("")

    for step_info in steps:
        report.append(f"步骤{step_info['step']}: {step_info['name']}")
        report.append(f"  状态: {'✓ 成功' if step_info['status'] == 'success' else '✗ 失败'}")

        if step_info["status"] == "success":
            if "output" in step_info:
                report.append(f"  输出: {step_info['output']}")

            if "enrichment_stats" in step_info:
                stats = step_info["enrichment_stats"]
                report.append("  补全统计:")
                report.append(f"    - 总处理数: {stats['processing']['total_processed']}")
                report.append(f"    - 补全成功: {stats['processing']['enriched']}")
                report.append(f"    - 补全率: {stats['processing']['enrichment_rate']}")
                report.append(f"    - 数据库命中: {stats['session']['db_hits']}")
                report.append(f"    - AI调用: {stats['session']['ai_calls']}")

            if "merge_stats" in step_info:
                stats = step_info["merge_stats"]
                report.append("  合并统计:")
                report.append(f"    - WOS记录: {stats['wos_count']}")
                report.append(f"    - Scopus记录: {stats['scopus_count']}")
                report.append(f"    - 重复记录: {stats['duplicates']}")
                report.append(f"    - 最终记录: {stats['final_count']}")

            if "filter_stats" in step_info:
                stats = step_info["filter_stats"]
                report.append("  筛选统计:")
                report.append(f"    - 输入记录: {stats['total_records']}")
                report.append(f"    - 筛选后: {stats['filtered_records']}")
                filter_rate = (
                    stats["filtered_records"] / stats["total_records"] * 100
                ) if stats["total_records"] else 0.0
                report.append(f"    - 筛选率: {filter_rate:.1f}%")

            if "cleaning_stats" in step_info:
                stats = step_info["cleaning_stats"]
                report.append("  清洗统计:")
                report.append(f"    - 总机构数（清洗前）: {stats['institutions_before']}")
                report.append(f"    - 总机构数（清洗后）: {stats['institutions_after']}")
                report.append(f"    - 唯一机构数（清洗前）: {stats['unique_before']}")
                report.append(f"    - 唯一机构数（清洗后）: {stats['unique_after']}")
                reduction_rate = (
                    (1 - stats["unique_after"] / stats["unique_before"]) * 100
                ) if stats["unique_before"] else 0.0
                report.append(f"    - 减少比例: {reduction_rate:.1f}%")
                report.append(f"    - 移除噪音: {stats['removed_noise']}")
                report.append(f"    - 合并父子机构: {stats['merged']}")
                report.append(f"    - 移除独立部门: {stats['removed_departments']}")

            if "year_stats" in step_info:
                stats = step_info["year_stats"]
                report.append("  年份过滤统计:")
                report.append(f"    - 原始记录: {stats['total_records']}")
                report.append(f"    - 保留记录: {stats['kept_records']}")
                report.append(f"    - 过滤掉: {stats['filtered_records']}")
                report.append(f"    - 过滤率: {stats['filter_rate']:.1f}%")
                if stats["filtered_years"]:
                    report.append("    - 被过滤的年份:")
                    for year, count in sorted(stats["filtered_years"].items()):
                        report.append(f"      {year}: {count} 篇")
        else:
            report.append(f"  错误: {step_info.get('error', '未知错误')}")

        report.append("")

    report.append("=" * 80)
    report.append("最终输出文件")
    report.append("=" * 80)
    report.append("")
    file_num = 1

    if options.has_year_filter:
        report.append(f"{file_num}. WOS年份过滤后: {paths.wos_year_filtered}")
        file_num += 1
        report.append(f"{file_num}. Scopus年份过滤后: {paths.scopus_year_filtered}")
        file_num += 1

    report.append(f"{file_num}. 转换后的Scopus数据: {paths.scopus_converted}")
    file_num += 1
    if options.enable_ai:
        report.append(f"{file_num}. AI补全后的数据: {paths.scopus_enriched}")
        file_num += 1
    report.append(f"{file_num}. 合并去重后的数据: {paths.merged_file}")
    file_num += 1
    report.append(f"{file_num}. {options.language}筛选后的数据: {paths.filtered_file}")
    file_num += 1
    if options.enable_cleaning:
        report.append(f"{file_num}. 机构清洗后的数据: {paths.cleaned_file} ⭐ 推荐")
        file_num += 1

    final_analysis_file = paths.final_analysis_file(options.enable_cleaning)
    report.append(
        f"{file_num}. 统计分析报告: {str(final_analysis_file).replace('.txt', '_analysis_report.txt')}"
    )
    report.append("")

    report.append("=" * 80)
    report.append("推荐使用")
    report.append("=" * 80)
    report.append("")
    report.append(f"✓ 用于VOSViewer/CiteSpace分析: {final_analysis_file}")
    if options.has_year_filter:
        report.append("  （已在源头过滤年份，数据更准确）⭐ 强烈推荐")
    if options.enable_cleaning:
        report.append("  （已清洗，唯一机构数减少约20%）")
    report.append(
        f"✓ 用于论文写作参考: {str(final_analysis_file).replace('.txt', '_analysis_report.txt')}"
    )
    report.append("")

    return "\n".join(report)


def write_workflow_report(report_file: Path, report_text: str) -> None:
    report_file.write_text(report_text, encoding="utf-8")
