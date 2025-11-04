#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
完整文献处理工作流
==================

自动完成：Scopus转换 → 合并去重 → 语言筛选 → 生成统计报告

作者：Meng Linghan
开发工具：Claude Code
日期：2025-11-04
版本：v2.1

运行方式:
    python3 run_complete_workflow.py --data-dir /path/to/data
    python3 run_complete_workflow.py --data-dir "/Users/xxx/文献计量学/Nano_NSCLC_Immune"
"""

import os
import sys
import re
import logging
import argparse
import subprocess
from datetime import datetime
from collections import Counter
from typing import Dict, List, Tuple

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class WorkflowStats:
    """工作流统计数据"""

    def __init__(self):
        self.wos_original = {'total': 0, 'Article': 0, 'Review': 0, 'other': 0}
        self.scopus_original = {'total': 0, 'Article': 0, 'Review': 0, 'other': 0}
        self.merged = {'total': 0, 'Article': 0, 'Review': 0, 'other': 0, 'duplicates': 0}
        self.english_filtered = {'total': 0, 'Article': 0, 'Review': 0, 'other': 0}
        self.language_dist = Counter()


class CompleteWorkflow:
    """完整的文献处理工作流"""

    def __init__(self, data_dir: str, target_language: str = "English"):
        self.data_dir = os.path.abspath(data_dir)
        self.target_language = target_language
        self.stats = WorkflowStats()

        # 工具脚本路径（与本脚本同目录）
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.converter_script = os.path.join(self.script_dir, "scopus_to_wos_converter.py")
        self.merge_script = os.path.join(self.script_dir, "merge_deduplicate.py")
        self.filter_script = os.path.join(self.script_dir, "filter_language.py")

        # 输入文件路径
        self.wos_file = os.path.join(data_dir, "wos.txt")
        self.scopus_file = os.path.join(data_dir, "scopus.csv")

        # 输出文件路径
        self.scopus_converted = os.path.join(data_dir, "scopus_converted_to_wos.txt")
        self.merged_file = os.path.join(data_dir, "merged_deduplicated.txt")
        self.english_file = os.path.join(data_dir, "english_only.txt")
        self.final_report = os.path.join(data_dir, "workflow_complete_report.txt")

    def check_files(self) -> bool:
        """检查必要的文件是否存在"""
        logger.info("="*60)
        logger.info("步骤 0/5: 检查文件")
        logger.info("="*60)

        if not os.path.exists(self.wos_file):
            logger.error(f"WOS文件不存在: {self.wos_file}")
            return False

        if not os.path.exists(self.scopus_file):
            logger.error(f"Scopus文件不存在: {self.scopus_file}")
            return False

        logger.info(f"✓ WOS文件: {self.wos_file}")
        logger.info(f"✓ Scopus文件: {self.scopus_file}")

        # 检查工具脚本
        for script, name in [
            (self.converter_script, "转换脚本"),
            (self.merge_script, "合并脚本"),
            (self.filter_script, "筛选脚本")
        ]:
            if not os.path.exists(script):
                logger.error(f"{name}不存在: {script}")
                return False

        logger.info("✓ 所有工具脚本就绪")
        return True

    def count_document_types(self, file_path: str) -> Dict[str, int]:
        """
        统计WOS文件中的文献类型

        Returns:
            {'total': int, 'Article': int, 'Review': int, 'other': int}
        """
        stats = {'total': 0, 'Article': 0, 'Review': 0, 'other': 0}

        with open(file_path, 'r', encoding='utf-8-sig') as f:
            current_doc_type = None

            for line in f:
                # 检测文献类型字段（DT）
                if line.startswith('DT '):
                    current_doc_type = line[3:].strip()

                # 记录结束
                elif line.strip() == 'ER':
                    stats['total'] += 1

                    if current_doc_type:
                        if 'Article' in current_doc_type:
                            stats['Article'] += 1
                        elif 'Review' in current_doc_type:
                            stats['Review'] += 1
                        else:
                            stats['other'] += 1

                    current_doc_type = None

        return stats

    def extract_language_distribution(self, file_path: str) -> Counter:
        """提取语言分布"""
        languages = Counter()

        with open(file_path, 'r', encoding='utf-8-sig') as f:
            for line in f:
                if line.startswith('LA '):
                    lang = line[3:].strip()
                    languages[lang] += 1

        return languages

    def step1_analyze_wos_original(self):
        """步骤1: 分析WOS原始数据"""
        logger.info("")
        logger.info("="*60)
        logger.info("步骤 1/5: 分析WOS原始数据")
        logger.info("="*60)

        self.stats.wos_original = self.count_document_types(self.wos_file)

        logger.info(f"总文献数: {self.stats.wos_original['total']}")
        logger.info(f"  - Article: {self.stats.wos_original['Article']}")
        logger.info(f"  - Review: {self.stats.wos_original['Review']}")
        logger.info(f"  - 其他: {self.stats.wos_original['other']}")

    def step2_convert_scopus(self):
        """步骤2: 转换Scopus到WOS格式"""
        logger.info("")
        logger.info("="*60)
        logger.info("步骤 2/5: 转换Scopus到WOS格式")
        logger.info("="*60)

        cmd = [
            "python3", self.converter_script,
            self.scopus_file,
            self.scopus_converted,
            "--log-level", "WARNING"
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            logger.error(f"Scopus转换失败:\n{result.stderr}")
            return False

        # 分析转换后的Scopus数据
        self.stats.scopus_original = self.count_document_types(self.scopus_converted)

        logger.info(f"✓ Scopus转换完成")
        logger.info(f"总文献数: {self.stats.scopus_original['total']}")
        logger.info(f"  - Article: {self.stats.scopus_original['Article']}")
        logger.info(f"  - Review: {self.stats.scopus_original['Review']}")
        logger.info(f"  - 其他: {self.stats.scopus_original['other']}")

        return True

    def step3_merge_and_deduplicate(self):
        """步骤3: 合并并去重"""
        logger.info("")
        logger.info("="*60)
        logger.info("步骤 3/5: 合并WOS和Scopus数据并去重")
        logger.info("="*60)

        cmd = [
            "python3", self.merge_script,
            self.wos_file,
            self.scopus_converted,
            self.merged_file,
            "--log-level", "WARNING"
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            logger.error(f"合并去重失败:\n{result.stderr}")
            return False

        # 分析合并后的数据
        self.stats.merged = self.count_document_types(self.merged_file)

        # 计算去重数量
        original_total = self.stats.wos_original['total'] + self.stats.scopus_original['total']
        self.stats.merged['duplicates'] = original_total - self.stats.merged['total']

        logger.info(f"✓ 合并去重完成")
        logger.info(f"原始总数: {original_total} (WOS: {self.stats.wos_original['total']}, Scopus: {self.stats.scopus_original['total']})")
        logger.info(f"去除重复: {self.stats.merged['duplicates']}")
        logger.info(f"合并后总数: {self.stats.merged['total']}")
        logger.info(f"  - Article: {self.stats.merged['Article']}")
        logger.info(f"  - Review: {self.stats.merged['Review']}")
        logger.info(f"  - 其他: {self.stats.merged['other']}")

        return True

    def step4_filter_language(self):
        """步骤4: 筛选英文文献"""
        logger.info("")
        logger.info("="*60)
        logger.info(f"步骤 4/5: 筛选{self.target_language}文献")
        logger.info("="*60)

        # 先提取语言分布
        self.stats.language_dist = self.extract_language_distribution(self.merged_file)

        cmd = [
            "python3", self.filter_script,
            self.merged_file,
            self.english_file,
            "--language", self.target_language,
            "--log-level", "WARNING"
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            logger.error(f"语言筛选失败:\n{result.stderr}")
            return False

        # 分析筛选后的数据
        self.stats.english_filtered = self.count_document_types(self.english_file)

        filtered_count = self.stats.merged['total'] - self.stats.english_filtered['total']

        logger.info(f"✓ 语言筛选完成")
        logger.info(f"筛选前: {self.stats.merged['total']}")
        logger.info(f"过滤掉: {filtered_count}")
        logger.info(f"筛选后: {self.stats.english_filtered['total']}")
        logger.info(f"  - Article: {self.stats.english_filtered['Article']}")
        logger.info(f"  - Review: {self.stats.english_filtered['Review']}")
        logger.info(f"  - 其他: {self.stats.english_filtered['other']}")

        return True

    def step5_generate_report(self):
        """步骤5: 生成综合报告"""
        logger.info("")
        logger.info("="*60)
        logger.info("步骤 5/5: 生成综合统计报告")
        logger.info("="*60)

        report_lines = []
        report_lines.append("="*80)
        report_lines.append("文献处理完整工作流统计报告")
        report_lines.append("Literature Processing Workflow - Complete Report")
        report_lines.append("="*80)
        report_lines.append("")
        report_lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append(f"数据目录: {self.data_dir}")
        report_lines.append(f"目标语言: {self.target_language}")
        report_lines.append("")

        # 1. WOS原始数据
        report_lines.append("-"*80)
        report_lines.append("1. WOS原始数据统计")
        report_lines.append("-"*80)
        report_lines.append(f"数据来源: {os.path.basename(self.wos_file)}")
        report_lines.append(f"总文献数: {self.stats.wos_original['total']:>6}")
        report_lines.append(f"  - Article (研究论文):  {self.stats.wos_original['Article']:>6} ({self._percent(self.stats.wos_original['Article'], self.stats.wos_original['total'])})")
        report_lines.append(f"  - Review (综述):       {self.stats.wos_original['Review']:>6} ({self._percent(self.stats.wos_original['Review'], self.stats.wos_original['total'])})")
        report_lines.append(f"  - 其他类型:            {self.stats.wos_original['other']:>6} ({self._percent(self.stats.wos_original['other'], self.stats.wos_original['total'])})")
        report_lines.append("")

        # 2. Scopus原始数据
        report_lines.append("-"*80)
        report_lines.append("2. Scopus原始数据统计")
        report_lines.append("-"*80)
        report_lines.append(f"数据来源: {os.path.basename(self.scopus_file)}")
        report_lines.append(f"总文献数: {self.stats.scopus_original['total']:>6}")
        report_lines.append(f"  - Article (研究论文):  {self.stats.scopus_original['Article']:>6} ({self._percent(self.stats.scopus_original['Article'], self.stats.scopus_original['total'])})")
        report_lines.append(f"  - Review (综述):       {self.stats.scopus_original['Review']:>6} ({self._percent(self.stats.scopus_original['Review'], self.stats.scopus_original['total'])})")
        report_lines.append(f"  - 其他类型:            {self.stats.scopus_original['other']:>6} ({self._percent(self.stats.scopus_original['other'], self.stats.scopus_original['total'])})")
        report_lines.append("")

        # 3. 合并去重结果
        report_lines.append("-"*80)
        report_lines.append("3. 合并去重结果")
        report_lines.append("-"*80)
        original_total = self.stats.wos_original['total'] + self.stats.scopus_original['total']
        report_lines.append(f"合并前总数: {original_total:>6} (WOS: {self.stats.wos_original['total']}, Scopus: {self.stats.scopus_original['total']})")
        report_lines.append(f"识别重复:   {self.stats.merged['duplicates']:>6} ({self._percent(self.stats.merged['duplicates'], original_total)})")
        report_lines.append(f"合并后总数: {self.stats.merged['total']:>6}")
        report_lines.append(f"  - Article (研究论文):  {self.stats.merged['Article']:>6} ({self._percent(self.stats.merged['Article'], self.stats.merged['total'])})")
        report_lines.append(f"  - Review (综述):       {self.stats.merged['Review']:>6} ({self._percent(self.stats.merged['Review'], self.stats.merged['total'])})")
        report_lines.append(f"  - 其他类型:            {self.stats.merged['other']:>6} ({self._percent(self.stats.merged['other'], self.stats.merged['total'])})")
        report_lines.append("")

        # 4. 语言分布
        report_lines.append("-"*80)
        report_lines.append("4. 语言分布统计（合并后）")
        report_lines.append("-"*80)
        for lang, count in self.stats.language_dist.most_common():
            marker = " ✓" if lang == self.target_language else ""
            report_lines.append(f"  {lang:20s}: {count:>6} ({self._percent(count, self.stats.merged['total'])}){marker}")
        report_lines.append("")

        # 5. 语言筛选结果
        report_lines.append("-"*80)
        report_lines.append(f"5. {self.target_language}文献筛选结果")
        report_lines.append("-"*80)
        filtered_out = self.stats.merged['total'] - self.stats.english_filtered['total']
        report_lines.append(f"筛选前总数: {self.stats.merged['total']:>6}")
        report_lines.append(f"过滤文献数: {filtered_out:>6} ({self._percent(filtered_out, self.stats.merged['total'])})")
        report_lines.append(f"筛选后总数: {self.stats.english_filtered['total']:>6} ({self._percent(self.stats.english_filtered['total'], self.stats.merged['total'])})")
        report_lines.append(f"  - Article (研究论文):  {self.stats.english_filtered['Article']:>6} ({self._percent(self.stats.english_filtered['Article'], self.stats.english_filtered['total'])})")
        report_lines.append(f"  - Review (综述):       {self.stats.english_filtered['Review']:>6} ({self._percent(self.stats.english_filtered['Review'], self.stats.english_filtered['total'])})")
        report_lines.append(f"  - 其他类型:            {self.stats.english_filtered['other']:>6} ({self._percent(self.stats.english_filtered['other'], self.stats.english_filtered['total'])})")
        report_lines.append("")

        # 6. 数据流总结
        report_lines.append("-"*80)
        report_lines.append("6. 数据处理流程总结")
        report_lines.append("-"*80)
        report_lines.append(f"WOS原始数据:           {self.stats.wos_original['total']:>6} 篇")
        report_lines.append(f"Scopus原始数据:        {self.stats.scopus_original['total']:>6} 篇")
        report_lines.append(f"      ↓ 合并")
        report_lines.append(f"合并前总数:            {original_total:>6} 篇")
        report_lines.append(f"      ↓ 去重（去除 {self.stats.merged['duplicates']} 篇）")
        report_lines.append(f"合并后总数:            {self.stats.merged['total']:>6} 篇")
        report_lines.append(f"      ↓ 语言筛选（过滤 {filtered_out} 篇）")
        report_lines.append(f"最终{self.target_language}文献:      {self.stats.english_filtered['total']:>6} 篇")
        report_lines.append("")

        # 7. 输出文件
        report_lines.append("-"*80)
        report_lines.append("7. 生成的文件")
        report_lines.append("-"*80)
        report_lines.append(f"✓ {os.path.basename(self.scopus_converted)}")
        report_lines.append(f"   Scopus转换为WOS格式的中间文件")
        report_lines.append("")
        report_lines.append(f"✓ {os.path.basename(self.merged_file)}")
        report_lines.append(f"   WOS和Scopus合并去重后的完整文献集")
        report_lines.append(f"   包含 {self.stats.merged['total']} 篇文献")
        report_lines.append("")
        report_lines.append(f"✓ {os.path.basename(self.english_file)}")
        report_lines.append(f"   仅{self.target_language}文献的最终数据集（推荐用于分析）")
        report_lines.append(f"   包含 {self.stats.english_filtered['total']} 篇文献")
        report_lines.append("")
        report_lines.append(f"✓ {os.path.basename(self.final_report)}")
        report_lines.append(f"   本综合统计报告")
        report_lines.append("")

        # 8. 论文写作参考
        report_lines.append("-"*80)
        report_lines.append("8. 论文写作参考（Methods部分建议描述）")
        report_lines.append("-"*80)
        report_lines.append("")
        report_lines.append("数据来源与检索策略:")
        report_lines.append(f"  本研究从Web of Science (WOS)和Scopus两大数据库检索文献。")
        report_lines.append(f"  WOS检索得到{self.stats.wos_original['total']}篇文献，Scopus检索得到{self.stats.scopus_original['total']}篇文献。")
        report_lines.append("")
        report_lines.append("数据整合与去重:")
        report_lines.append(f"  将两个数据库的文献进行整合，通过DOI和标题匹配识别重复文献。")
        report_lines.append(f"  共识别{self.stats.merged['duplicates']}篇重复文献，去重后获得{self.stats.merged['total']}篇独立文献。")
        report_lines.append("")
        report_lines.append("纳入排除标准:")
        report_lines.append(f"  仅纳入{self.target_language}语言文献，排除其他语言文献{filtered_out}篇。")
        report_lines.append(f"  最终纳入{self.stats.english_filtered['total']}篇{self.target_language}文献进行分析，")
        report_lines.append(f"  其中研究论文(Article){self.stats.english_filtered['Article']}篇，")
        report_lines.append(f"  综述(Review){self.stats.english_filtered['Review']}篇。")
        report_lines.append("")

        report_lines.append("="*80)
        report_lines.append("报告结束 / End of Report")
        report_lines.append("="*80)

        # 保存报告
        report_text = '\n'.join(report_lines)
        with open(self.final_report, 'w', encoding='utf-8') as f:
            f.write(report_text)

        # 同时打印到控制台
        print("\n" + report_text)

        logger.info(f"✓ 综合报告已生成: {self.final_report}")

    def _percent(self, count: int, total: int) -> str:
        """计算百分比字符串"""
        if total == 0:
            return "  0.0%"
        return f"{count/total*100:5.1f}%"

    def run(self):
        """执行完整工作流"""
        logger.info("")
        logger.info("="*60)
        logger.info("文献处理完整工作流")
        logger.info("="*60)
        logger.info(f"数据目录: {self.data_dir}")
        logger.info(f"目标语言: {self.target_language}")
        logger.info("")

        try:
            # 检查文件
            if not self.check_files():
                return False

            # 步骤1: 分析WOS原始数据
            self.step1_analyze_wos_original()

            # 步骤2: 转换Scopus
            if not self.step2_convert_scopus():
                return False

            # 步骤3: 合并去重
            if not self.step3_merge_and_deduplicate():
                return False

            # 步骤4: 语言筛选
            if not self.step4_filter_language():
                return False

            # 步骤5: 生成报告
            self.step5_generate_report()

            logger.info("")
            logger.info("="*60)
            logger.info("✓ 完整工作流执行成功！")
            logger.info("="*60)
            logger.info("")
            logger.info("生成的文件:")
            logger.info(f"  1. {self.merged_file}")
            logger.info(f"     合并去重后的完整数据集 ({self.stats.merged['total']} 篇)")
            logger.info("")
            logger.info(f"  2. {self.english_file}")
            logger.info(f"     仅{self.target_language}文献 ({self.stats.english_filtered['total']} 篇) - 推荐用于分析")
            logger.info("")
            logger.info(f"  3. {self.final_report}")
            logger.info(f"     综合统计报告 - 供论文写作参考")
            logger.info("")

            return True

        except Exception as e:
            logger.error(f"工作流执行失败: {e}")
            logger.exception("详细错误:")
            return False


def main():
    parser = argparse.ArgumentParser(
        description='完整的文献处理工作流：转换 → 合并 → 筛选 → 统计',
        epilog='示例: python3 run_complete_workflow.py --data-dir "/Users/xxx/文献计量学/Nano_NSCLC_Immune"',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument('--data-dir', '-d',
                       required=True,
                       help='数据目录路径（包含wos.txt和scopus.csv）')
    parser.add_argument('--language', '-l',
                       default='English',
                       help='目标语言 (默认: English)')
    parser.add_argument('--log-level',
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                       default='INFO',
                       help='日志级别 (默认: INFO)')

    args = parser.parse_args()

    # 设置日志级别
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    # 执行工作流
    workflow = CompleteWorkflow(args.data_dir, args.language)
    success = workflow.run()

    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
