#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增强版Scopus转WOS转换器（批量并发版 v2.0）

只进行机构、期刊、国家的AI标准化，人名使用原有算法处理：
1. 国家名WOS标准化（AI批量并发）
2. 期刊名WOS标准缩写（AI批量并发）
3. 人名处理（使用原有算法，不调用AI）

作者：Meng Linghan
开发工具：Claude Code
日期：2025-11-11
版本：v2.0 (优化版 - 20并发)
"""

import logging
import re
import time
from typing import Dict, List, Optional
from ..standardizers.wos import WOSStandardizerBatch
from .scopus import ScopusToWosConverter
from ..gemini_config import GeminiConfig
from ..utils.wos_text import split_wos_records

logger = logging.getLogger(__name__)


class EnhancedConverterBatchV2:
    """增强版转换器（批量并发版 v2.0 - 只标准化国家和期刊）"""

    def __init__(self, input_file: str, output_file: str, enable_standardization: bool = True,
                 max_workers: int = 5, batch_size: int = 20, reference_wos_file: Optional[str] = None):
        self.input_file = input_file
        self.output_file = output_file
        self.enable_standardization = enable_standardization
        self.reference_wos_file = reference_wos_file

        # 创建基础转换器
        self.converter = ScopusToWosConverter(
            input_file,
            output_file,
            reference_wos_file=reference_wos_file,
        )

        # 创建WOS标准化器（批量并发版，降低并发数避免429错误）
        if enable_standardization:
            # API key/URL/model 均取环境变量，默认官方端点
            config = GeminiConfig()

            if not config.validate():
                raise ValueError("WOS标准化需要有效的 Gemini API 配置，请设置 GEMINI_API_KEY")

            self.standardizer = WOSStandardizerBatch(
                config,
                max_workers=max_workers,
                batch_size=batch_size
            )
        else:
            self.standardizer = None

    def convert(self):
        """执行转换（带WOS标准化）"""
        logger.info("=" * 80)
        logger.info("增强版Scopus转WOS转换器（批量并发版 v2.0）")
        logger.info("=" * 80)
        logger.info(f"输入文件: {self.input_file}")
        logger.info(f"输出文件: {self.output_file}")
        logger.info(f"WOS标准化: {'启用' if self.enable_standardization else '禁用'}")
        if self.enable_standardization:
            logger.info(f"并发线程数: {self.standardizer.max_workers}")
            logger.info(f"批处理大小: {self.standardizer.batch_size}")
            logger.info("标准化范围: 国家名、期刊名（人名使用原有算法）")
        logger.info("=" * 80)
        logger.info("")

        # 步骤1: 基础转换
        logger.info("步骤1: 执行基础格式转换...")
        self.converter.convert()

        if not self.enable_standardization:
            logger.info("✓ 转换完成（未启用WOS标准化）")
            return

        # 步骤2: WOS标准化（批量并发，只处理国家和期刊）
        logger.info("")
        logger.info("步骤2: 执行WOS格式标准化（批量并发 - 国家和期刊）...")
        self._standardize_wos_file_batch()

        # 保存数据库
        self.standardizer.db.save_database()

        # 打印统计
        self._print_statistics()

        logger.info("")
        logger.info("=" * 80)
        logger.info("✓ 增强版转换完成！")
        logger.info("=" * 80)

    def _standardize_wos_file_batch(self):
        """批量标准化WOS文件（只处理国家和期刊）"""
        # 读取转换后的文件
        with open(self.output_file, encoding='utf-8-sig') as f:
            content = f.read()

        # 解析记录
        records = self._parse_wos_file(content)
        logger.info(f"解析了 {len(records)} 条记录")

        # 第一步：收集所有需要标准化的项目（只收集国家和期刊）
        logger.info("收集所有需要标准化的项目...")
        all_countries = []
        all_journals = []

        for record in records:
            # 收集国家
            if 'C1' in record:
                countries = self._extract_countries_from_c1(record['C1'])
                all_countries.extend(countries)

            # 收集期刊
            if 'SO' in record:
                all_journals.append(record['SO'])

        logger.info(f"收集完成: {len(all_countries)} 个国家, {len(all_journals)} 个期刊")

        # 去重！
        unique_countries = list(set(all_countries))
        unique_journals = list(set(all_journals))
        logger.info(f"去重后: {len(unique_countries)} 个唯一国家, {len(unique_journals)} 个唯一期刊")
        logger.info("注意: 人名使用原有算法处理，不调用AI")

        # 第二步：批量标准化（并发）
        logger.info("")
        logger.info("开始批量标准化...")

        # 批量标准化国家
        logger.info("批量标准化国家名...")
        country_mapping = self.standardizer.standardize_countries_batch(unique_countries)

        # 批次间延迟，避免429错误
        if unique_journals:
            logger.info("⏸️  等待3秒后继续...")
            time.sleep(3.0)

        # 批量标准化期刊
        logger.info("批量标准化期刊名...")
        journal_mapping = self.standardizer.standardize_journals_batch(unique_journals)

        logger.info("✓ 批量标准化完成")

        # 第三步：应用标准化结果到记录
        logger.info("")
        logger.info("应用标准化结果到记录...")
        for i, record in enumerate(records, 1):
            if i % 100 == 0:
                logger.info(f"进度: {i}/{len(records)}")

            # 应用国家标准化
            if 'C1' in record:
                record['C1'] = self._apply_country_mapping(record['C1'], country_mapping)

            # 应用期刊标准化
            if 'SO' in record:
                record['SO'] = journal_mapping.get(record['SO'], record['SO'])

        # 写回文件
        self._write_wos_file(records)

        logger.info("✓ WOS标准化完成")

    def _extract_countries_from_c1(self, c1_text: str) -> List[str]:
        """从C1字段提取所有国家名"""
        countries = []
        lines = c1_text.split('\n')

        for line in lines:
            # 提取国家（最后一个逗号后的部分，句号前）
            match = re.search(r',\s*([^,]+)\.$', line)
            if match:
                country = match.group(1).strip()
                countries.append(country)

        return countries

    def _apply_country_mapping(self, c1_text: str, country_mapping: Dict[str, str]) -> str:
        """应用国家名映射到C1字段"""
        lines = c1_text.split('\n')
        standardized_lines = []

        for line in lines:
            # 提取国家（最后一个逗号后的部分，句号前）
            match = re.search(r',\s*([^,]+)\.$', line)
            if match:
                country = match.group(1).strip()
                wos_country = country_mapping.get(country, country)
                line = line.replace(f', {country}.', f', {wos_country}.')

            standardized_lines.append(line)

        return '\n'.join(standardized_lines)

    def _parse_wos_file(self, content: str) -> List[Dict[str, str]]:
        """解析WOS文件"""
        records = []
        record_blocks = split_wos_records(content)

        for block in record_blocks:
            block = 'PT ' + block
            record = {}
            current_field = None
            current_value = []

            for line in block.split('\n'):
                if not line.strip():
                    continue

                # 检查是否是新字段
                if len(line) >= 3 and line[2] == ' ' and line[:2].isupper():
                    # 保存上一个字段
                    if current_field:
                        record[current_field] = '\n'.join(current_value)

                    # 开始新字段
                    current_field = line[:2]
                    current_value = [line[3:]]
                elif line.startswith('   ') and current_field:
                    # 续行
                    current_value.append(line[3:])

            # 保存最后一个字段
            if current_field:
                record[current_field] = '\n'.join(current_value)

            if record:
                records.append(record)

        return records

    def _write_wos_file(self, records: List[Dict[str, str]]):
        """写入WOS文件"""
        with open(self.output_file, 'w', encoding='utf-8-sig') as f:
            # 写入文件头
            f.write('FN Clarivate Analytics Web of Science\n')
            f.write('VR 1.0\n')

            # 写入每条记录
            for record in records:
                f.write('\n')

                # 按WOS标准顺序写入字段
                field_order = ['PT', 'AU', 'AF', 'TI', 'SO', 'LA', 'DT', 'DE', 'ID', 'AB',
                              'C1', 'C3', 'RP', 'EM', 'FU', 'FX', 'CR', 'NR', 'TC', 'Z9',
                              'U1', 'U2', 'PU', 'PI', 'PA', 'SN', 'EI', 'BN', 'J9', 'JI',
                              'PD', 'PY', 'VL', 'IS', 'SI', 'PN', 'SU', 'BP', 'EP', 'AR',
                              'DI', 'D2', 'PG', 'WE', 'WC', 'SC', 'GA', 'UT', 'PM', 'OA',
                              'HC', 'HP', 'DA']

                for field in field_order:
                    if field in record:
                        value = record[field]
                        lines = value.split('\n')

                        # 写入第一行
                        f.write(f'{field} {lines[0]}\n')

                        # 写入续行（3个空格缩进）
                        for line in lines[1:]:
                            f.write(f'   {line}\n')

                f.write('ER\n')

            # 写入文件尾
            f.write('\nEF')

    def _print_statistics(self):
        """打印统计信息"""
        stats = self.standardizer.get_statistics()

        logger.info("")
        logger.info("=" * 80)
        logger.info("WOS标准化统计")
        logger.info("=" * 80)
        logger.info("国家标准化:")
        logger.info(f"  - 缓存命中: {stats['countries']['hits']}")
        logger.info(f"  - AI处理: {stats['countries']['misses']}")
        logger.info(f"  - 命中率: {stats['countries']['hit_rate']}")
        logger.info("")
        logger.info("期刊标准化:")
        logger.info(f"  - 缓存命中: {stats['journals']['hits']}")
        logger.info(f"  - AI处理: {stats['journals']['misses']}")
        logger.info(f"  - 命中率: {stats['journals']['hit_rate']}")
        logger.info("")
        logger.info(f"总API调用次数: {stats['api_calls']}")
        logger.info("")
        logger.info("注意: 人名使用原有算法处理，未调用AI")
        logger.info("=" * 80)


def main():
    """测试转换器"""
    import sys

    if len(sys.argv) < 3:
        print("用法: python3 enhanced_converter_batch_v2.py <input.csv> <output.txt>")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2]

    # 创建转换器（5个并发线程，每批20个，避免429错误）
    converter = EnhancedConverterBatchV2(
        input_file,
        output_file,
        enable_standardization=True,
        max_workers=5,
        batch_size=20
    )

    # 执行转换
    converter.convert()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    main()
