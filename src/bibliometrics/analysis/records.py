#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文献数据统计分析工具
====================

分析WOS格式文件中的机构、国家、作者等分布情况

作者：Meng Linghan
开发工具：Claude Code
日期：2025-11-04

运行方式:
    python3 analyze_records.py merged_deduplicated.txt
"""

import re
import json
import os
import sys
import logging
from collections import Counter, defaultdict
from typing import Dict, List

from ..utils.paths import resolve_project_path

logger = logging.getLogger(__name__)


class RecordAnalyzer:
    """文献记录分析器"""

    def __init__(self, wos_file: str, config_dir: str = "config"):
        self.wos_file = wos_file
        self.config_dir = str(resolve_project_path(config_dir))
        self.records = []

        self.use_human_readable_countries = os.environ.get(
            'BIBLIOMETRICS_ANALYSIS_HUMAN_COUNTRY_NAMES', ''
        ).strip().lower() in {'1', 'true', 'yes'}

        # 仅在显式要求人类可读名称时加载映射；默认保留 WOS 风格国家名
        self.country_mapping = self._load_country_mapping() if self.use_human_readable_countries else {}

        # 统计数据
        self.stats = {
            'total_records': 0,
            'countries': Counter(),
            'institutions': Counter(),
            'years': Counter(),
            'document_types': Counter(),
            'authors': Counter(),
            'country_collaborations': defaultdict(set)
        }

    def _load_country_mapping(self) -> Dict[str, str]:
        """加载国家名称映射"""
        config_file = os.path.join(self.config_dir, "country_mapping.json")

        if os.path.exists(config_file):
            try:
                with open(config_file, encoding='utf-8') as f:
                    data = json.load(f)
                    logger.info(f"加载了国家映射配置: {len(data.get('country_mapping', {}))} 个映射规则")
                    return data.get('country_mapping', {})
            except Exception as e:
                logger.warning(f"加载国家映射失败: {e}")

        return {}

    def normalize_country(self, country: str) -> str:
        """标准化国家名称"""
        country = re.sub(r'\s+', ' ', country.strip().rstrip('.'))

        # 处理州/邮编前缀混入国家字段的情况，例如:
        # - CA 94115 USA
        # - 100191 Peoples R China
        prefixed_match = re.match(r'^(?:[A-Z]{2}\s+)?\d{4,6}(?:-\d{4})?\s+(.+)$', country)
        if prefixed_match and not re.search(r'\d', prefixed_match.group(1)):
            country = prefixed_match.group(1).strip()

        # 处理美国州/邮编+USA格式，默认仍保持 WOS 风格的 USA
        if re.match(r'^(?:[A-Z]{2}(?:\s+\d{5})?|\d{5})\s+USA$', country):
            return 'United States' if self.use_human_readable_countries else 'USA'

        if not self.use_human_readable_countries:
            return country

        # 查找映射表
        if country in self.country_mapping:
            return self.country_mapping[country]

        return country

    def parse_wos_file(self) -> List[Dict]:
        """解��WOS文件"""
        records = []
        current_record = {}
        current_field = None
        current_value = []

        logger.info(f"开始解析文件: {self.wos_file}")

        with open(self.wos_file, encoding='utf-8-sig') as f:
            for line in f:
                # 跳过文件头
                if line.startswith('FN ') or line.startswith('VR '):
                    continue

                # 记录结束
                if line.strip() == 'ER':
                    if current_field:
                        current_record[current_field] = '\n'.join(current_value)
                    if current_record:
                        records.append(current_record)
                    current_record = {}
                    current_field = None
                    current_value = []
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

                # 续行
                elif line.startswith('   ') and current_field:
                    current_value.append(line.strip())

        logger.info(f"解析完成，共 {len(records)} 条记录")
        return records

    def extract_countries_from_c1(self, c1_field: str) -> List[str]:
        """从C1字段提取国家"""
        countries = []

        # C1格式: [Authors] Institution, City, Country.
        # 分号分隔多个机构
        for affiliation in c1_field.split('\n'):
            # 提取最后一个逗号后的内容（通常是国家）
            parts = affiliation.split(',')
            if len(parts) >= 2:
                country_raw = parts[-1].strip().rstrip('.')
                country = self.normalize_country(country_raw)
                if country:
                    countries.append(country)

        return countries

    def extract_institutions_from_c3(self, c3_field: str) -> List[str]:
        """从C3字段提取机构"""
        institutions = []

        # C3格式: Institution1; Institution2; ...
        # 注意：C3字段可能包含continuation lines（用\n分隔），需要先替换为空格
        c3_normalized = c3_field.replace('\n', ' ')

        for inst in c3_normalized.split(';'):
            inst = inst.strip()
            if inst:
                institutions.append(inst)

        return institutions

    def analyze(self):
        """执行分析"""
        logger.info("="*60)
        logger.info("开始分析文献数据")
        logger.info("="*60)

        # 解析文件
        self.records = self.parse_wos_file()
        self.stats['total_records'] = len(self.records)

        # 分析每条记录
        for record in self.records:
            # 国家分布
            if 'C1' in record:
                countries = self.extract_countries_from_c1(record['C1'])
                for country in countries:
                    self.stats['countries'][country] += 1

                # 国际合作分析（一篇文章涉及多个国家）
                if len(set(countries)) > 1:
                    unique_countries = sorted(set(countries))
                    for i, c1 in enumerate(unique_countries):
                        for c2 in unique_countries[i+1:]:
                            self.stats['country_collaborations'][c1].add(c2)
                            self.stats['country_collaborations'][c2].add(c1)

            # 机构分布
            if 'C3' in record:
                institutions = self.extract_institutions_from_c3(record['C3'])
                for inst in institutions:
                    self.stats['institutions'][inst] += 1

            # 年份分布
            if 'PY' in record:
                self.stats['years'][record['PY']] += 1

            # 文献类型
            if 'DT' in record:
                self.stats['document_types'][record['DT']] += 1

            # 作者统计（第一作者）
            if 'AU' in record:
                first_author = record['AU'].split('\n')[0]
                self.stats['authors'][first_author] += 1

        # 打印报告
        self.print_report()

    def print_report(self):
        """打印分析报告"""
        logger.info("")
        logger.info("="*60)
        logger.info("文献数据分析报告")
        logger.info("="*60)
        logger.info(f"总记录数: {self.stats['total_records']}")
        logger.info("")

        # 年份分布
        logger.info("-"*60)
        logger.info("年份分布（Top 10）:")
        logger.info("-"*60)
        for year, count in self.stats['years'].most_common(10):
            logger.info(f"  {year}: {count:>4} 篇")
        logger.info("")

        # 国家分布
        logger.info("-"*60)
        logger.info("国家分布（Top 20）:")
        logger.info("-"*60)
        total_countries = sum(self.stats['countries'].values())
        for country, count in self.stats['countries'].most_common(20):
            percentage = (count / total_countries * 100) if total_countries > 0 else 0
            logger.info(f"  {country:30s}: {count:>4} ({percentage:5.1f}%)")
        logger.info("")

        # 机构分布
        logger.info("-"*60)
        logger.info("高产机构（Top 20）:")
        logger.info("-"*60)
        for inst, count in self.stats['institutions'].most_common(20):
            logger.info(f"  {inst:50s}: {count:>3} 篇")
        logger.info("")

        # 文献类型
        logger.info("-"*60)
        logger.info("文献类型分布:")
        logger.info("-"*60)
        for doc_type, count in self.stats['document_types'].most_common():
            logger.info(f"  {doc_type:30s}: {count:>4}")
        logger.info("")

        # 国际合作
        logger.info("-"*60)
        logger.info("国际合作情况（Top 10国家）:")
        logger.info("-"*60)
        collab_counts = {country: len(partners) for country, partners in self.stats['country_collaborations'].items()}
        for country, count in sorted(collab_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
            partners = ', '.join(list(self.stats['country_collaborations'][country])[:5])
            logger.info(f"  {country}: 与{count}个国家合作")
            logger.info(f"    主要合作: {partners}")
        logger.info("")

        logger.info("="*60)
        logger.info("分析完成!")
        logger.info("="*60)

        # 保存详细报告
        self.save_detailed_report()

    def save_detailed_report(self):
        """保存详细报告到文件"""
        report_file = self.wos_file.replace('.txt', '_analysis_report.txt')

        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("="*60 + "\n")
            f.write("文献数据详细分析报告\n")
            f.write("="*60 + "\n\n")

            f.write(f"总记录数: {self.stats['total_records']}\n\n")

            # 年份分布
            f.write("-"*60 + "\n")
            f.write("年份分布:\n")
            f.write("-"*60 + "\n")
            for year, count in sorted(self.stats['years'].items()):
                f.write(f"{year}: {count}\n")
            f.write("\n")

            # 国家分布（完整列表）
            f.write("-"*60 + "\n")
            f.write("国家分布（完整列表）:\n")
            f.write("-"*60 + "\n")
            total_countries = sum(self.stats['countries'].values())
            for country, count in self.stats['countries'].most_common():
                percentage = (count / total_countries * 100) if total_countries > 0 else 0
                f.write(f"{country:40s}: {count:>4} ({percentage:5.1f}%)\n")
            f.write("\n")

            # 机构分布（完整列表）
            f.write("-"*60 + "\n")
            f.write("机构分布（Top 50）:\n")
            f.write("-"*60 + "\n")
            for inst, count in self.stats['institutions'].most_common(50):
                f.write(f"{inst:60s}: {count:>3}\n")
            f.write("\n")

            # 高产作者
            f.write("-"*60 + "\n")
            f.write("高产作者（Top 30）:\n")
            f.write("-"*60 + "\n")
            for author, count in self.stats['authors'].most_common(30):
                f.write(f"{author:40s}: {count:>3}\n")
            f.write("\n")

        logger.info(f"\n详细报告已保存: {report_file}")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='文献数据统计分析工具',
        epilog='示例: python3 analyze_records.py merged_deduplicated.txt'
    )
    parser.add_argument('wos_file', help='WOS格式文件路径')
    parser.add_argument('--config-dir', default='config', help='配置文件目录')
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                       default='INFO', help='日志级别')

    args = parser.parse_args()

    # 设置日志级别
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    if not os.path.exists(args.wos_file):
        logger.error(f"文件不存在: {args.wos_file}")
        return 1

    try:
        analyzer = RecordAnalyzer(args.wos_file, args.config_dir)
        analyzer.analyze()
        return 0
    except Exception as e:
        logger.error(f"分析失败: {e}")
        logger.exception("详细错误:")
        return 1


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    sys.exit(main())
