#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
年份过滤工具
===========

根据年份范围过滤WOS格式文献数据

作者：Meng Linghan
开发工具：Claude Code
日期：2025-11-13

运行方式:
    python3 filter_by_year.py input.txt output.txt --year-range 2015-2024
    python3 filter_by_year.py input.txt output.txt --min-year 2015 --max-year 2024
"""

import re
import argparse
import logging
from collections import Counter
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class YearFilter:
    """年份过滤器"""

    def __init__(self, min_year: Optional[int] = None, max_year: Optional[int] = None):
        """
        初始化年份过滤器

        Args:
            min_year: 最小年份（包含），None表示不限制
            max_year: 最大年份（包含），None表示不限制
        """
        self.min_year = min_year
        self.max_year = max_year

        # 统计信息
        self.stats = {
            'total_records': 0,
            'filtered_records': 0,
            'year_distribution': Counter(),
            'filtered_years': Counter()
        }

    def parse_wos_file(self, input_file: str) -> List[Dict[str, str]]:
        """
        解析WOS文件

        Returns:
            List of records, each record is {'raw_text': str, 'year': str}
        """
        records = []
        current_record = []
        current_year = None
        in_record = False

        logger.info(f"开始解析文件: {input_file}")

        with open(input_file, encoding='utf-8-sig') as f:
            for line in f:
                # 文件头
                if line.startswith('FN ') or line.startswith('VR '):
                    continue

                # 记录开始
                if line.startswith('PT '):
                    in_record = True
                    current_record = [line]
                    current_year = None
                    continue

                # 记录中
                if in_record:
                    current_record.append(line)

                    # 提取年份
                    if line.startswith('PY '):
                        year_match = re.match(r'^PY\s+(\d{4})', line)
                        if year_match:
                            current_year = year_match.group(1)

                    # 记录结束
                    if line.strip() == 'ER':
                        records.append({
                            'raw_text': ''.join(current_record),
                            'year': current_year
                        })
                        self.stats['total_records'] += 1
                        if current_year:
                            self.stats['year_distribution'][current_year] += 1

                        in_record = False
                        current_record = []
                        current_year = None

        logger.info(f"解析完成，共 {len(records)} 条记录")
        return records

    def should_keep_record(self, year: Optional[str]) -> bool:
        """
        判断是否保留该记录

        Args:
            year: 年份字符串，可能为None

        Returns:
            True表示保留，False表示过滤掉
        """
        # 没有年份信息，保留
        if year is None:
            return True

        try:
            year_int = int(year)
        except ValueError:
            # 年份格式不正确，保留
            return True

        # 检查年份范围
        if self.min_year is not None and year_int < self.min_year:
            return False

        if self.max_year is not None and year_int > self.max_year:
            return False

        return True

    def filter_records(self, records: List[Dict[str, str]]) -> List[str]:
        """
        过滤记录

        Args:
            records: 记录列表

        Returns:
            保留的记录文本列表
        """
        filtered_records = []

        for record in records:
            year = record['year']

            if self.should_keep_record(year):
                filtered_records.append(record['raw_text'])
            else:
                self.stats['filtered_records'] += 1
                if year:
                    self.stats['filtered_years'][year] += 1

        logger.info(f"过滤完成，保留 {len(filtered_records)}/{len(records)} 条记录")
        return filtered_records

    def write_filtered_file(self, output_file: str, filtered_records: List[str]):
        """写入过滤后的文件"""
        logger.info(f"写入文件: {output_file}")

        with open(output_file, 'w', encoding='utf-8-sig') as f:
            # 写入文件头
            f.write('FN Clarivate Analytics Web of Science\n')
            f.write('VR 1.0\n')
            f.write('\n')

            # 写入记录
            for record_text in filtered_records:
                f.write(record_text)
                f.write('\n')

            # 写入文件尾
            f.write('EF\n')

        logger.info("写入完成")

    def generate_report(self, report_file: str):
        """生成过滤报告"""
        logger.info(f"生成报告: {report_file}")

        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("="*60 + "\n")
            f.write("年份过滤报告\n")
            f.write("="*60 + "\n\n")

            # 过滤条件
            f.write("过滤条件:\n")
            f.write("-"*60 + "\n")
            if self.min_year is not None:
                f.write(f"最小年份: {self.min_year}\n")
            else:
                f.write("最小年份: 无限制\n")

            if self.max_year is not None:
                f.write(f"最大年份: {self.max_year}\n")
            else:
                f.write("最大年份: 无限制\n")
            f.write("\n")

            # 统计信息
            f.write("过滤统计:\n")
            f.write("-"*60 + "\n")
            f.write(f"原始记录总数: {self.stats['total_records']}\n")
            f.write(f"保留记录数: {self.stats['total_records'] - self.stats['filtered_records']}\n")
            f.write(f"过滤掉记录数: {self.stats['filtered_records']}\n")

            if self.stats['total_records'] > 0:
                filter_rate = self.stats['filtered_records'] / self.stats['total_records'] * 100
                f.write(f"过滤率: {filter_rate:.2f}%\n")
            f.write("\n")

            # 原始年份分布
            f.write("原始年份分布:\n")
            f.write("-"*60 + "\n")
            for year, count in sorted(self.stats['year_distribution'].items()):
                status = "✓ 保留" if self.should_keep_record(year) else "✗ 过滤"
                f.write(f"{year}: {count:>4} 篇 [{status}]\n")
            f.write("\n")

            # 被过滤的年份
            if self.stats['filtered_years']:
                f.write("被过滤的年份分布:\n")
                f.write("-"*60 + "\n")
                for year, count in sorted(self.stats['filtered_years'].items()):
                    f.write(f"{year}: {count:>4} 篇\n")
                f.write("\n")

        logger.info("报告生成完成")

    def filter_file(self, input_file: str, output_file: str, report_file: Optional[str] = None):
        """
        执行完整的过滤流程

        Args:
            input_file: 输入WOS文件
            output_file: 输出WOS文件
            report_file: 报告文件（可选）
        """
        logger.info("="*60)
        logger.info("开始年份过滤")
        logger.info("="*60)

        # 解析文件
        records = self.parse_wos_file(input_file)

        # 过滤记录
        filtered_records = self.filter_records(records)

        # 写入文件
        self.write_filtered_file(output_file, filtered_records)

        # 生成报告
        if report_file:
            self.generate_report(report_file)

        # 打印摘要
        logger.info("="*60)
        logger.info("过滤完成")
        logger.info("="*60)
        logger.info(f"原始记录: {self.stats['total_records']} 篇")
        logger.info(f"保留记录: {self.stats['total_records'] - self.stats['filtered_records']} 篇")
        logger.info(f"过滤掉: {self.stats['filtered_records']} 篇")

        if self.stats['filtered_years']:
            logger.info("\n被过滤的年份:")
            for year, count in sorted(self.stats['filtered_years'].items()):
                logger.info(f"  {year}: {count} 篇")


def parse_year_range(year_range: str) -> Tuple[int, int]:
    """
    解析年份范围字符串

    Args:
        year_range: 格式如 "2015-2024"

    Returns:
        (min_year, max_year)
    """
    match = re.match(r'^(\d{4})-(\d{4})$', year_range)
    if not match:
        raise ValueError(f"年份范围格式错误: {year_range}，应为 YYYY-YYYY 格式（如 2015-2024）")

    min_year = int(match.group(1))
    max_year = int(match.group(2))

    if min_year > max_year:
        raise ValueError(f"最小年份 ({min_year}) 不能大于最大年份 ({max_year})")

    return min_year, max_year


def main():
    parser = argparse.ArgumentParser(
        description='根据年份范围过滤WOS格式文献数据',
        epilog='示例: python3 filter_by_year.py merged.txt filtered.txt --year-range 2015-2024',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument('input_file', help='输入WOS文件路径')
    parser.add_argument('output_file', help='输出WOS文件路径')

    # 年份范围参数（三种方式）
    year_group = parser.add_mutually_exclusive_group(required=True)
    year_group.add_argument(
        '--year-range',
        help='年份范围，格式: YYYY-YYYY（如 2015-2024）'
    )
    year_group.add_argument(
        '--min-year',
        type=int,
        help='最小年份（包含），单独使用或配合 --max-year'
    )

    parser.add_argument(
        '--max-year',
        type=int,
        help='最大年份（包含），需配合 --min-year 或 --year-range'
    )

    parser.add_argument(
        '--report',
        help='生成过滤报告文件路径（可选）'
    )

    parser.add_argument(
        '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        default='INFO',
        help='日志级别（默认: INFO）'
    )

    args = parser.parse_args()

    # 设置日志级别
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    # 解析年份范围
    min_year = None
    max_year = None

    if args.year_range:
        min_year, max_year = parse_year_range(args.year_range)
    elif args.min_year:
        min_year = args.min_year
        max_year = args.max_year
    else:
        parser.error("必须指定 --year-range 或 --min-year")

    # 生成默认报告文件名
    report_file = args.report
    if not report_file:
        output_base = args.output_file.rsplit('.', 1)[0]
        report_file = f"{output_base}_year_filter_report.txt"

    # 执行过滤
    filter_tool = YearFilter(min_year=min_year, max_year=max_year)
    filter_tool.filter_file(args.input_file, args.output_file, report_file)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    main()
