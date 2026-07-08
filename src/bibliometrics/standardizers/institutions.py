#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
机构名称清洗和标准化工具
========================

解决VOSviewer机构共现分析中的数据质量问题：
1. 清除无效/噪音数据（., hosp, inst, ltd等）
2. 统一名称变体和缩写（chinese acad sci → chinese academy of sciences）
3. 合并父机构与子机构（fudan univ shanghai canc ctr → fudan univ）
4. 移除独立的二级机构/部门（dept med oncol等）
5. 标准化中英文混杂问题

作者：Meng Linghan
开发工具：Claude Code
日期：2025-11-11
版本：v1.0

运行方式:
    python3 clean_institutions.py input.txt output.txt
    python3 clean_institutions.py chinese_only.txt chinese_only_cleaned.txt
"""

import re
import json
import os
import sys
import logging
from typing import Dict, List
from collections import Counter

from ..utils.paths import resolve_project_path

logger = logging.getLogger(__name__)


class InstitutionCleaner:
    """机构名称清洗器"""

    def __init__(self, config_file: str = "config/institution_cleaning_rules_ultimate.json"):
        self.config_file = str(resolve_project_path(config_file))
        self.rules = self._load_rules()

        # 统计信息
        self.stats = {
            'total_records': 0,
            'total_institutions_before': 0,
            'total_institutions_after': 0,
            'removed_noise': 0,
            'standardized': 0,
            'merged_parent_child': 0,
            'removed_departments': 0,
            'unique_before': 0,
            'unique_after': 0
        }

        # 记录清洗详情
        self.cleaning_log = {
            'noise_removed': Counter(),
            'standardized': Counter(),
            'merged': Counter(),
            'departments_removed': Counter()
        }

    def _load_rules(self) -> Dict:
        """加载清洗规则"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, encoding='utf-8') as f:
                    rules = json.load(f)
                    logger.info(f"✓ 加载清洗规则: {self.config_file}")
                    logger.info(f"  - 噪音模式: {len(rules.get('noise_patterns', []))}")
                    logger.info(f"  - 标准化规则: {len(rules.get('standardization_rules', {}))}")
                    logger.info(f"  - 父子机构映射: {len(rules.get('parent_child_mapping', {}))}")
                    logger.info(f"  - 合并规则: {len(rules.get('merge_rules', {}))}")
                    return rules
            except Exception as e:
                logger.warning(f"加载规则失败: {e}，使用默认规则")

        # 默认规则
        return {
            'noise_patterns': [r'^\.$', r'^hosp$', r'^inst$', r'^ltd\.?$'],
            'standardization_rules': {},
            'parent_child_mapping': {},
            'department_patterns': [r'^dept ', r'^fac ', r'^sch '],
            'merge_rules': {}
        }

    def is_noise(self, institution: str) -> bool:
        """判断是否为噪音数据"""
        inst_lower = institution.lower().strip()

        # 检查噪音模式
        for pattern in self.rules.get('noise_patterns', []):
            if re.match(pattern, inst_lower):
                return True

        # 太短的机构名（少于3个字符）
        if len(inst_lower) < 3:
            return True

        # 纯数字或纯符号
        if re.match(r'^[\d\s\.\-,;]+$', inst_lower):
            return True

        # ⚠️ 关键修复：过滤人名格式
        # 人名格式: "Lastname, F" 或 "Lastname, FM" (姓 + 逗号 + 1-2个大写字母)
        if re.match(r'^[A-Z][a-z]+,\s*[A-Z]{1,2}$', institution.strip()):
            return True

        # 人名格式: "Lastname F" 或 "Lastname FM" (姓 + 空格 + 1-2个大写字母)
        if re.match(r'^[A-Z][a-z]+\s+[A-Z]{1,2}$', institution.strip()):
            return True

        return False

    def is_department(self, institution: str) -> bool:
        """判断是否为独立的部门/二级机构"""
        inst_lower = institution.lower().strip()

        # 检查部门模式
        for pattern in self.rules.get('department_patterns', []):
            if re.match(pattern, inst_lower):
                # 如果没有包含大学/医院等主机构名称，则认为是独立部门
                if not any(keyword in inst_lower for keyword in ['univ', 'hosp', 'inst', 'acad', 'coll']):
                    return True

        return False

    def standardize_name(self, institution: str) -> str:
        """标准化机构名称"""
        inst_lower = institution.lower().strip()

        # 应用标准化规则
        standardization_rules = self.rules.get('standardization_rules', {})
        if inst_lower in standardization_rules:
            standardized = standardization_rules[inst_lower]
            if standardized != inst_lower:
                self.cleaning_log['standardized'][f"{institution} → {standardized}"] += 1
            return standardized

        # 应用合并规则
        merge_rules = self.rules.get('merge_rules', {})
        if inst_lower in merge_rules:
            merged = merge_rules[inst_lower]
            if merged != inst_lower:
                self.cleaning_log['standardized'][f"{institution} → {merged}"] += 1
            return merged

        return institution

    def merge_parent_child(self, institution: str) -> str:
        """合并父机构与子机构"""
        inst_lower = institution.lower().strip()

        # 应用父子机构映射
        parent_child_mapping = self.rules.get('parent_child_mapping', {})
        if inst_lower in parent_child_mapping:
            parent = parent_child_mapping[inst_lower]
            if parent == "REMOVE":
                return None  # 标记为删除
            if parent != inst_lower:
                self.cleaning_log['merged'][f"{institution} → {parent}"] += 1
            return parent

        return institution

    def remove_company_suffix(self, institution: str) -> str:
        """移除公司后缀（AG, Inc, LLC等）。

        配置项 company_suffixes_to_remove 是小写正则（如 ' inc\\.?$'、' sa$'），
        必须按正则匹配：前导空格是词边界，直接 endswith 字面匹配会把
        'Univ Pisa' 误截成 'Univ Pi'（' sa$' 被剥成 'sa'）。
        """
        for suffix_pattern in self.rules.get('company_suffixes_to_remove', []):
            if not suffix_pattern:
                continue
            match = re.search(suffix_pattern, institution, flags=re.IGNORECASE)
            if match:
                return institution[:match.start()].strip()

        return institution

    def clean_institution(self, institution: str) -> str:
        """清洗单个机构名称"""
        if not institution or not institution.strip():
            return None

        # 1. 去除首尾空格
        inst = institution.strip()

        # 2. 检查是否为噪音
        if self.is_noise(inst):
            self.stats['removed_noise'] += 1
            self.cleaning_log['noise_removed'][inst] += 1
            return None

        # 3. 检查是否为独立部门
        if self.is_department(inst):
            self.stats['removed_departments'] += 1
            self.cleaning_log['departments_removed'][inst] += 1
            return None

        # 4. 移除公司后缀
        inst = self.remove_company_suffix(inst)

        # 5. 标准化名称
        inst = self.standardize_name(inst)
        if inst:
            self.stats['standardized'] += 1

        # 6. 合并父子机构
        inst = self.merge_parent_child(inst)
        if inst is None:
            self.stats['merged_parent_child'] += 1
            return None

        return inst

    def find_parent_institution(self, institution: str, all_institutions: List[str]) -> str:
        """在同一记录的机构列表中查找父机构"""
        inst_lower = institution.lower()

        # 检查是否有其他机构包含当前机构（可能是父机构）
        for other_inst in all_institutions:
            other_lower = other_inst.lower()
            if other_lower == inst_lower:
                continue

            # 如果当前机构名包含在另一个机构中，且另一个机构更短
            # 说明另一个机构可能是父机构
            # 例如：Harvard University 包含在 Harvard Medical School 中
            # 但 Harvard University 更短，所以是父机构
            if inst_lower in other_lower and len(inst_lower) < len(other_lower):
                # 检查是否是真正的父子关系（不是偶然包含）
                # 例如：Harvard University 和 Harvard Medical School 是父子
                # 但 University 和 Harvard University 不是
                if len(other_lower) - len(inst_lower) > 5:  # 至少相差5个字符
                    return institution  # 当前机构是父机构，保留

        return institution

    def smart_merge_institutions(self, institutions: List[str]) -> List[str]:
        """智能合并机构列表中的父子关系"""
        if not institutions:
            return []

        # 1. 先清洗每个机构
        cleaned = []
        for inst in institutions:
            cleaned_inst = self.clean_institution(inst)
            if cleaned_inst:
                cleaned.append(cleaned_inst)

        if not cleaned:
            return []

        # 2. 查找父子关系并合并
        to_remove = set()

        for inst in cleaned:
            inst_lower = inst.lower()

            # 检查是否有父机构存在
            for other_inst in cleaned:
                other_lower = other_inst.lower()

                if inst_lower == other_lower:
                    continue

                # 如果other包含inst，且other更长，说明inst可能是父机构
                # 例如：inst="Harvard University", other="Harvard Medical School"
                if inst_lower in other_lower and len(other_lower) > len(inst_lower) + 5:
                    # inst是父机构，保留inst，移除other
                    to_remove.add(other_lower)
                    self.cleaning_log['merged'][f"{other_inst} → {inst}"] += 1

        # 3. 移除子机构，保留父机构
        result = []
        for inst in cleaned:
            if inst.lower() not in to_remove:
                result.append(inst)

        return result

    def clean_c3_field(self, c3_field: str) -> str:
        """清洗C3字段（机构列表）- 重点是合并和去重"""
        if not c3_field:
            return ""

        # 分割机构
        institutions = [inst.strip() for inst in c3_field.split(';') if inst.strip()]
        self.stats['total_institutions_before'] += len(institutions)

        # 智能合并（包含父子关系处理）
        merged_institutions = self.smart_merge_institutions(institutions)

        # 去重（保持顺序，不区分大小写）
        seen = set()
        unique_institutions = []
        for inst in merged_institutions:
            inst_lower = inst.lower()
            if inst_lower not in seen:
                seen.add(inst_lower)
                unique_institutions.append(inst)

        self.stats['total_institutions_after'] += len(unique_institutions)

        # 重新组合
        return '; '.join(unique_institutions) if unique_institutions else ""

    def parse_wos_file(self, input_file: str) -> List[Dict]:
        """解析WOS文件"""
        logger.info(f"开始解析文件: {input_file}")

        with open(input_file, encoding='utf-8-sig') as f:
            content = f.read()

        # 提取文件头
        header_match = re.match(r'(FN .*?\nVR .*?\n)', content, re.DOTALL)
        self.file_header = header_match.group(1) if header_match else "FN Clarivate Analytics Web of Science\nVR 1.0\n"

        records = []
        current_record = {}
        current_field = None
        current_value = []
        record_raw_lines = []

        for line in content.split('\n'):
            # 跳过文件头
            if line.startswith('FN ') or line.startswith('VR '):
                continue

            # 记录结束
            if line.strip() == 'ER':
                if current_field:
                    current_record[current_field] = '\n'.join(current_value)

                if current_record:
                    records.append({
                        'fields': current_record,
                        'raw_lines': record_raw_lines
                    })

                current_record = {}
                current_field = None
                current_value = []
                record_raw_lines = []
                continue

            # 文件结束
            if line.strip() == 'EF':
                break

            # 空行
            if not line.strip():
                if current_field:
                    record_raw_lines.append(line)
                continue

            # 新字段（以两个字母开头 + 空格）
            if len(line) >= 3 and line[2] == ' ' and line[:2].isupper():
                # 保存上一个字段
                if current_field:
                    current_record[current_field] = '\n'.join(current_value)

                # 开始新字段
                current_field = line[:2]
                current_value = [line[3:]]
                record_raw_lines.append(line)

            # 续行（以3个空格开头）
            elif line.startswith('   ') and current_field:
                current_value.append(line[3:])
                record_raw_lines.append(line)

            else:
                # 其他情况，添加到当前字段
                if current_field:
                    current_value.append(line)
                    record_raw_lines.append(line)

        self.stats['total_records'] = len(records)
        logger.info(f"解析完成，共 {len(records)} 条记录")

        return records

    def clean_records(self, records: List[Dict]) -> List[Dict]:
        """清洗所有记录"""
        logger.info("开始清洗机构名称...")

        cleaned_records = []
        unique_institutions_before = set()
        unique_institutions_after = set()

        for i, record in enumerate(records, 1):
            if i % 100 == 0:
                logger.info(f"进度: {i}/{len(records)}")

            fields = record['fields']

            # 清洗C3字段
            if 'C3' in fields:
                original_c3 = fields['C3']

                # 统计清洗前的唯一机构
                for inst in original_c3.split(';'):
                    inst = inst.strip().lower()
                    if inst:
                        unique_institutions_before.add(inst)

                # 清洗
                cleaned_c3 = self.clean_c3_field(original_c3)
                fields['C3'] = cleaned_c3

                # 统计清洗后的唯一机构
                for inst in cleaned_c3.split(';'):
                    inst = inst.strip().lower()
                    if inst:
                        unique_institutions_after.add(inst)

            cleaned_records.append(record)

        self.stats['unique_before'] = len(unique_institutions_before)
        self.stats['unique_after'] = len(unique_institutions_after)

        logger.info("清洗完成！")
        return cleaned_records

    def write_wos_file(self, records: List[Dict], output_file: str):
        """写入WOS文件"""
        logger.info(f"开始写入文件: {output_file}")

        with open(output_file, 'w', encoding='utf-8-sig') as f:
            # 写入文件头
            f.write(self.file_header)
            f.write('\n')

            # 写入每条记录
            for record in records:
                fields = record['fields']

                # 按照WOS标准顺序写入字段
                field_order = ['PT', 'AU', 'AF', 'TI', 'SO', 'LA', 'DT', 'DE', 'ID',
                              'AB', 'C1', 'C3', 'RP', 'EM', 'RI', 'OI', 'FU', 'FX',
                              'CR', 'NR', 'TC', 'Z9', 'U1', 'U2', 'PU', 'PI', 'PA',
                              'SN', 'EI', 'BN', 'J9', 'JI', 'PD', 'PY', 'VL', 'IS',
                              'SI', 'PN', 'SU', 'BP', 'EP', 'AR', 'DI', 'D2', 'PG',
                              'WC', 'SC', 'GA', 'UT', 'PM', 'OA', 'HC', 'HP', 'DA']

                # 写入已知顺序的字段
                for field_name in field_order:
                    if field_name in fields:
                        value = fields[field_name]
                        lines = value.split('\n')
                        f.write(f"{field_name} {lines[0]}\n")
                        for line in lines[1:]:
                            f.write(f"   {line}\n")

                # 写入其他字段
                for field_name, value in fields.items():
                    if field_name not in field_order:
                        lines = value.split('\n')
                        f.write(f"{field_name} {lines[0]}\n")
                        for line in lines[1:]:
                            f.write(f"   {line}\n")

                # 记录结束标记
                f.write("ER\n\n")

            # 文件结束标记
            f.write("EF\n")

        logger.info(f"文件写入完成: {output_file}")

    def generate_report(self, output_file: str):
        """生成清洗报告"""
        report_file = output_file.replace('.txt', '_cleaning_report.txt')

        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write("机构名称清洗报告 / Institution Cleaning Report\n")
            f.write("=" * 80 + "\n\n")

            f.write(f"输入文件: {self.input_file}\n")
            f.write(f"输出文件: {output_file}\n\n")

            f.write("-" * 80 + "\n")
            f.write("清洗统计:\n")
            f.write("-" * 80 + "\n")
            f.write(f"总记录数:                {self.stats['total_records']}\n")
            f.write(f"清洗前机构总数:          {self.stats['total_institutions_before']}\n")
            f.write(f"清洗后机构总数:          {self.stats['total_institutions_after']}\n")
            f.write(f"清洗前唯一机构数:        {self.stats['unique_before']}\n")
            f.write(f"清洗后唯一机构数:        {self.stats['unique_after']}\n")
            reduction_pct = (
                (1 - self.stats['unique_after'] / self.stats['unique_before']) * 100
                if self.stats['unique_before'] else 0.0
            )
            f.write(f"减少比例:                {reduction_pct:.1f}%\n\n")

            f.write(f"移除噪音数据:            {self.stats['removed_noise']}\n")
            f.write(f"标准化名称:              {self.stats['standardized']}\n")
            f.write(f"合并父子机构:            {self.stats['merged_parent_child']}\n")
            f.write(f"移除独立部门:            {self.stats['removed_departments']}\n\n")

            # 详细清洗日志
            if self.cleaning_log['noise_removed']:
                f.write("-" * 80 + "\n")
                f.write("移除的噪音数据（Top 20）:\n")
                f.write("-" * 80 + "\n")
                for item, count in self.cleaning_log['noise_removed'].most_common(20):
                    f.write(f"  {item:50s}: {count:>4} 次\n")
                f.write("\n")

            if self.cleaning_log['standardized']:
                f.write("-" * 80 + "\n")
                f.write("标准化的名称（Top 30）:\n")
                f.write("-" * 80 + "\n")
                for item, count in self.cleaning_log['standardized'].most_common(30):
                    f.write(f"  {item}\n")
                    f.write(f"    出现次数: {count}\n")
                f.write("\n")

            if self.cleaning_log['merged']:
                f.write("-" * 80 + "\n")
                f.write("合并的父子机构（Top 30）:\n")
                f.write("-" * 80 + "\n")
                for item, count in self.cleaning_log['merged'].most_common(30):
                    f.write(f"  {item}\n")
                    f.write(f"    出现次数: {count}\n")
                f.write("\n")

            if self.cleaning_log['departments_removed']:
                f.write("-" * 80 + "\n")
                f.write("移除的独立部门（Top 20）:\n")
                f.write("-" * 80 + "\n")
                for item, count in self.cleaning_log['departments_removed'].most_common(20):
                    f.write(f"  {item:50s}: {count:>4} 次\n")
                f.write("\n")

            f.write("=" * 80 + "\n")
            f.write("清洗完成！\n")
            f.write("=" * 80 + "\n")

        logger.info(f"\n清洗报告已保存: {report_file}")

    def print_summary(self):
        """打印清洗摘要"""
        logger.info("")
        logger.info("=" * 80)
        logger.info("清洗摘要")
        logger.info("=" * 80)
        logger.info(f"总记录数:                {self.stats['total_records']}")
        logger.info(f"清洗前机构总数:          {self.stats['total_institutions_before']}")
        logger.info(f"清洗后机构总数:          {self.stats['total_institutions_after']}")
        logger.info(f"清洗前唯一机构数:        {self.stats['unique_before']}")
        logger.info(f"清洗后唯一机构数:        {self.stats['unique_after']}")
        reduction_pct = (
            (1 - self.stats['unique_after'] / self.stats['unique_before']) * 100
            if self.stats['unique_before'] else 0.0
        )
        logger.info(f"减少比例:                {reduction_pct:.1f}%")
        logger.info("")
        logger.info(f"移除噪音数据:            {self.stats['removed_noise']}")
        logger.info(f"标准化名称:              {self.stats['standardized']}")
        logger.info(f"合并父子机构:            {self.stats['merged_parent_child']}")
        logger.info(f"移除独立部门:            {self.stats['removed_departments']}")
        logger.info("=" * 80)

    def run(self, input_file: str, output_file: str):
        """运行清洗流程"""
        self.input_file = input_file

        logger.info("")
        logger.info("=" * 80)
        logger.info("机构名称清洗工具")
        logger.info("=" * 80)
        logger.info("")

        # 1. 解析文件
        records = self.parse_wos_file(input_file)

        # 2. 清洗记录
        cleaned_records = self.clean_records(records)

        # 3. 写入文件
        self.write_wos_file(cleaned_records, output_file)

        # 4. 生成报告
        self.generate_report(output_file)

        # 5. 打印摘要
        self.print_summary()

        logger.info("")
        logger.info("=" * 80)
        logger.info("✓ 清洗完成！")
        logger.info("=" * 80)
        logger.info(f"输出文件: {output_file}")
        logger.info(f"清洗报告: {output_file.replace('.txt', '_cleaning_report.txt')}")
        logger.info("")


def main():
    """命令行工具"""
    import argparse

    parser = argparse.ArgumentParser(
        description='机构名称清洗和标准化工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 基本使用
  python3 clean_institutions.py input.txt output.txt

  # 清洗已筛选语言的文献
  python3 clean_institutions.py chinese_only.txt chinese_only_cleaned.txt

  # 指定配置文件
  python3 clean_institutions.py input.txt output.txt --config config/my_rules.json

清洗功能:
  1. 移除噪音数据（., hosp, inst, ltd等）
  2. 统一名称变体（chinese acad sci → chinese academy of sciences）
  3. 合并父子机构（fudan univ shanghai canc ctr → fudan univ）
  4. 移除独立部门（dept med oncol等）
  5. 标准化中英文混杂

输出:
  - 清洗后的WOS文件
  - 详细清洗报告（*_cleaning_report.txt）
        """
    )

    parser.add_argument('input_file', help='输入WOS文件路径')
    parser.add_argument('output_file', help='输出WOS文件路径')
    parser.add_argument('--config', default='config/institution_cleaning_rules_ultimate.json',
                       help='清洗规则配置文件（默认: config/institution_cleaning_rules_ultimate.json）')
    parser.add_argument('--log-level', default='INFO',
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                       help='日志级别（默认: INFO）')

    args = parser.parse_args()

    # 设置日志级别
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    # 检查输入文件
    if not os.path.exists(args.input_file):
        logger.error(f"输入文件不存在: {args.input_file}")
        sys.exit(1)

    # 运行清洗
    cleaner = InstitutionCleaner(args.config)
    cleaner.run(args.input_file, args.output_file)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    main()
