#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文献语言筛选工具
================

筛选WOS格式文件中指定语言的文献记录

作者：Meng Linghan
开发工具：Claude Code
日期：2025-11-04
版本：v2.1

运行方式:
    python3 filter_language.py input.txt output.txt --language English
    python3 filter_language.py merged_deduplicated.txt english_only.txt
"""

import re
import os
import sys
import logging
from typing import List, Dict, Tuple
from collections import Counter

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class LanguageFilter:
    """WOS格式文件语言筛选器"""

    def __init__(self, input_file: str, output_file: str, target_language: str = "English"):
        self.input_file = input_file
        self.output_file = output_file
        self.target_language = target_language

        # 统计数据
        self.stats = {
            'total_records': 0,
            'filtered_records': 0,
            'no_language_field': 0,
            'language_distribution': Counter()
        }

    def parse_wos_file(self) -> List[Dict]:
        """
        解析WOS格式文件，保留完整的原始文本

        Returns:
            List[Dict]: 每个记录包含 {'fields': dict, 'raw_text': str}
        """
        logger.info(f"开始解析文件: {self.input_file}")

        with open(self.input_file, 'r', encoding='utf-8-sig') as f:
            content = f.read()

        # 提取文件头
        header_match = re.match(r'(FN .*?\nVR .*?\n)', content, re.DOTALL)
        self.file_header = header_match.group(1) if header_match else "FN Clarivate Analytics Web of Science\nVR 1.0\n"

        records = []
        current_record = {}
        current_field = None
        current_value = []
        record_lines = []  # 保存当前记录的原始行

        for line in content.split('\n'):
            # 跳过文件头
            if line.startswith('FN ') or line.startswith('VR '):
                continue

            # 记录结束
            if line.strip() == 'ER':
                if current_field:
                    current_record[current_field] = '\n'.join(current_value)

                if current_record:
                    # 保存完整的原始文本
                    record_lines.append('ER')
                    records.append({
                        'fields': current_record,
                        'raw_text': '\n'.join(record_lines)
                    })

                current_record = {}
                current_field = None
                current_value = []
                record_lines = []
                continue

            # 文件结束
            if line.strip() == 'EF':
                break

            # 新字段
            field_match = re.match(r'^([A-Z][A-Z0-9])\s+(.*)$', line)
            if field_match:
                if current_field:
                    current_record[current_field] = '\n'.join(current_value)

                current_field = field_match.group(1)
                current_value = [field_match.group(2)]
                record_lines.append(line)

            # 续行
            elif line.startswith('   ') and current_field:
                current_value.append(line.strip())
                record_lines.append(line)

        logger.info(f"解析完成，共 {len(records)} 条记录")
        return records

    def filter_records(self, records: List[Dict]) -> List[Dict]:
        """
        筛选指定语言的记录

        Args:
            records: 记录列表

        Returns:
            List[Dict]: 筛选后的记录列表
        """
        logger.info(f"开始筛选语言: {self.target_language}")

        filtered = []
        self.stats['total_records'] = len(records)

        for record in records:
            fields = record['fields']

            # 统计语言分布
            if 'LA' in fields:
                language = fields['LA'].strip()
                self.stats['language_distribution'][language] += 1

                # 筛选目标语言
                if language.lower() == self.target_language.lower():
                    filtered.append(record)
                    self.stats['filtered_records'] += 1
            else:
                # 没有语言字段的记录
                self.stats['no_language_field'] += 1

        logger.info(f"筛选完成，保留 {len(filtered)} 条记录")
        return filtered

    def write_filtered_file(self, records: List[Dict]):
        """
        写入筛选后的WOS格式文件

        Args:
            records: 筛选后的记录列表
        """
        logger.info(f"开始写入文件: {self.output_file}")

        with open(self.output_file, 'w', encoding='utf-8-sig') as f:
            # 写入文件头
            f.write(self.file_header)
            f.write('\n')

            # 写入每条记录的原始文本
            for record in records:
                f.write(record['raw_text'])
                f.write('\n\n')

            # 写入文件尾
            f.write('EF\n')

        logger.info(f"文件写入完成")

    def generate_report(self) -> str:
        """
        生成筛选报告

        Returns:
            str: 报告文本
        """
        report = []
        report.append("=" * 60)
        report.append("语言筛选报告 / Language Filter Report")
        report.append("=" * 60)
        report.append("")
        report.append(f"输入文件: {self.input_file}")
        report.append(f"输出文件: {self.output_file}")
        report.append(f"目标语言: {self.target_language}")
        report.append("")
        report.append("-" * 60)
        report.append("筛选结果:")
        report.append("-" * 60)
        report.append(f"总记录数:           {self.stats['total_records']:>6}")
        report.append(f"筛选后记录数:       {self.stats['filtered_records']:>6}")
        report.append(f"无语言字段记录:     {self.stats['no_language_field']:>6}")

        if self.stats['total_records'] > 0:
            percentage = (self.stats['filtered_records'] / self.stats['total_records']) * 100
            report.append(f"保留比例:           {percentage:>5.1f}%")

        report.append("")
        report.append("-" * 60)
        report.append("语言分布:")
        report.append("-" * 60)

        for language, count in self.stats['language_distribution'].most_common():
            percentage = (count / self.stats['total_records']) * 100 if self.stats['total_records'] > 0 else 0
            marker = " ✓" if language.lower() == self.target_language.lower() else ""
            report.append(f"  {language:20s}: {count:>5} ({percentage:5.1f}%){marker}")

        report.append("")
        report.append("=" * 60)

        return '\n'.join(report)

    def save_report(self):
        """保存报告到文件"""
        report_file = self.output_file.replace('.txt', '_filter_report.txt')
        report_text = self.generate_report()

        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report_text)

        logger.info(f"筛选报告已保存: {report_file}")
        return report_file

    def run(self):
        """执行筛选流程"""
        logger.info("="*60)
        logger.info("文献语言筛选工具")
        logger.info("="*60)
        logger.info("")

        # 检查输入文件
        if not os.path.exists(self.input_file):
            logger.error(f"输入文件不存在: {self.input_file}")
            return False

        try:
            # 1. 解析文件
            records = self.parse_wos_file()

            if not records:
                logger.warning("未找到任何记录")
                return False

            # 2. 筛选记录
            filtered_records = self.filter_records(records)

            if not filtered_records:
                logger.warning(f"未找到任何 {self.target_language} 语言的记录")
                return False

            # 3. 写入文件
            self.write_filtered_file(filtered_records)

            # 4. 生成报告
            report_file = self.save_report()

            # 5. 打印报告到控制台
            print("\n" + self.generate_report())

            logger.info("")
            logger.info("="*60)
            logger.info("筛选完成!")
            logger.info("="*60)
            logger.info(f"输出文件: {self.output_file}")
            logger.info(f"筛选报告: {report_file}")

            return True

        except Exception as e:
            logger.error(f"筛选过程中出现错误: {e}")
            logger.exception("详细错误:")
            return False


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='文献语言筛选工具 - 筛选指定语言的文献记录',
        epilog='示例: python3 filter_language.py merged_deduplicated.txt english_only.txt --language English',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument('input_file',
                       help='输入的WOS格式文件路径')
    parser.add_argument('output_file',
                       help='输出的筛选后文件路径')
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

    # 执行筛选
    filter_tool = LanguageFilter(args.input_file, args.output_file, args.language)
    success = filter_tool.run()

    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
