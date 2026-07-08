#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
机构信息补全器 v2.0（优化版）

新特性：
1. 数据库缓存（优先查询数据库，没有才调用AI）
2. 重试机制（API失败自动重试）
3. 批量处理优化（定期保存数据库）
4. 增加max_tokens到5000
5. 详细的统计报告

作者：Meng Linghan
开发工具：Claude Code
日期：2025-11-10
版本：v2.0
"""

import re
import os
import logging
from typing import Dict, List, Optional, Tuple
from ..gemini_config import GeminiConfig
from ..utils.wos_text import split_wos_records
from .gemini import GeminiEnricherV2

logger = logging.getLogger(__name__)


class InstitutionEnricherV2:
    """机构信息补全器v2.0（优化版）"""

    def __init__(self, gemini_config: GeminiConfig, db_path: str = 'config/institution_ai_cache.json'):
        """
        初始化补全器

        Args:
            gemini_config: Gemini API配置
            db_path: 数据库路径
        """
        self.gemini = GeminiEnricherV2(gemini_config, db_path)
        self.stats = {
            'total_processed': 0,
            'enriched': 0,
            'failed': 0,
            'db_hits': 0,
            'ai_calls': 0
        }

        logger.info("✓ 机构信息补全器v2.0已初始化")

    def enrich_c1_field(self, scopus_c1_text: str, authors: List[str]) -> Tuple[str, Dict]:
        """
        补全整个C1字段（批量处理）

        Args:
            scopus_c1_text: Scopus的C1字段文本
            authors: 作者列表

        Returns:
            (补全后的C1文本, 统计信息)
        """
        lines = [line.strip() for line in scopus_c1_text.split('\n') if line.strip()]

        # 第一步：解析所有行，收集需要补全的机构
        parsed_lines = []
        institutions_to_enrich = []

        # 无效机构关键词（过滤掉公司、Ltd等）——按整词匹配，
        # 子串匹配会把 Cornell/Colorado/Columbia 等误伤为公司（'Co' in 'Cornell'）
        company_word_re = re.compile(r'\b(ltd|inc|co|llc|corp)\b\.?', re.IGNORECASE)

        for line in lines:
            parsed = self._parse_scopus_c1_line(line)
            parsed_lines.append((line, parsed))

            if parsed:
                # 过滤无效机构
                inst_name = parsed['institution']
                if company_word_re.search(inst_name):
                    continue  # 跳过公司名称

                inst_tuple = (inst_name, parsed['city'], parsed['country'])
                institutions_to_enrich.append(inst_tuple)

        # 第二步：批量补全所有机构（去重）
        unique_institutions = list(set(institutions_to_enrich))
        enrichment_results = self.gemini.enrich_institutions_batch(unique_institutions)

        # 第三步：应用补全结果
        enriched_lines = []
        line_stats = []

        for line, parsed in parsed_lines:
            if not parsed:
                enriched_lines.append(line)
                line_stats.append({'status': 'parse_failed', 'original': line})
                continue

            # 获取补全结果
            inst_tuple = (parsed['institution'], parsed['city'], parsed['country'])
            enriched = enrichment_results.get(inst_tuple)

            if enriched and enriched['confidence'] > 0.7:
                # 补全成功，重新构建C1行
                new_line = self._build_wos_c1_line(parsed['authors'], enriched)
                enriched_lines.append(new_line)
                line_stats.append({
                    'status': 'enriched',
                    'original': line,
                    'enriched': new_line,
                    'confidence': enriched['confidence']
                })
                self.stats['enriched'] += 1
            else:
                # 补全失败，保持原样
                enriched_lines.append(line)
                line_stats.append({'status': 'failed', 'original': line})
                self.stats['failed'] += 1

            self.stats['total_processed'] += 1

        enriched_c1 = '\n'.join(enriched_lines)
        return enriched_c1, {'lines': line_stats}

    def _parse_scopus_c1_line(self, c1_line: str) -> Optional[Dict]:
        """解析Scopus的C1行"""
        match = re.match(r'\[(.*?)\]\s+(.*)', c1_line)
        if not match:
            return None

        authors_str = match.group(1)
        address = match.group(2).rstrip('.')

        authors = [a.strip() for a in authors_str.split(';')]
        parts = [p.strip() for p in address.split(',')]

        if len(parts) < 2:
            return None

        country = parts[-1]
        # 两段式地址（"Harvard Univ, USA"）没有城市段，parts[-2] 是机构名本身
        city = parts[-2] if len(parts) >= 3 else None
        institution = parts[0]
        departments = parts[1:-2] if len(parts) > 2 else []

        return {
            'authors': authors,
            'institution': institution,
            'departments': departments,
            'city': city,
            'country': country
        }

    def _build_wos_c1_line(self, authors: List[str], enriched_info: Dict) -> str:
        """构建WOS格式的C1行"""
        authors_str = '; '.join(authors)
        address_parts = [enriched_info['institution_full_name']]

        if enriched_info.get('departments'):
            address_parts.extend(enriched_info['departments'])

        # 构建地理信息部分
        # ⚠️ 关键修复：国家必须始终是最后一个逗号后的独立部分
        # 这样 merge_deduplicate.py 才能正确提取国家名称
        if enriched_info.get('city'):
            address_parts.append(enriched_info['city'])

        # 如果有州代码和邮编，分别添加（不合并）
        if enriched_info.get('state'):
            address_parts.append(enriched_info['state'])
        if enriched_info.get('zip_code'):
            address_parts.append(enriched_info['zip_code'])

        # 国家必须是最后一个独立部分
        if enriched_info.get('country'):
            address_parts.append(enriched_info['country'])

        address_str = ', '.join(address_parts)
        c1_line = f"[{authors_str}] {address_str}."

        return c1_line

    def enrich_file(self, input_file: str, output_file: str, save_interval: int = 5) -> Dict:
        """
        补全整个WOS文件的C1字段

        Args:
            input_file: 输入文件路径
            output_file: 输出文件路径
            save_interval: 每处理多少条记录保存一次数据库

        Returns:
            统计信息
        """
        logger.info(f"开始补全文件: {input_file}")

        # 读取文件
        with open(input_file, encoding='utf-8-sig') as f:
            content = f.read()

        # 解析记录
        records = self._parse_wos_file(content)
        logger.info(f"解析了 {len(records)} 条记录")

        # 补全每条记录的C1字段
        enriched_records = []
        for i, record in enumerate(records, 1):
            logger.info(f"处理记录 {i}/{len(records)}")

            if 'C1' in record and 'AU' in record:
                authors = [a.strip() for a in record['AU'].split('\n') if a.strip()]
                enriched_c1, line_stats = self.enrich_c1_field(record['C1'], authors)
                record['C1'] = enriched_c1

            enriched_records.append(record)

            # 定期保存数据库
            if i % save_interval == 0:
                self.gemini.db.save_database()
                logger.info(f"✓ 已保存数据库（进度: {i}/{len(records)}）")

        # 最后保存一次数据库
        self.gemini.db.save_database()

        # 写入文件
        self._write_wos_file(enriched_records, output_file)

        logger.info(f"补全完成，已保存到: {output_file}")

        return self.get_statistics()

    def _parse_wos_file(self, content: str) -> List[Dict[str, str]]:
        """解析WOS文件"""
        records = []
        record_blocks = split_wos_records(content)

        for block in record_blocks:
            block = 'PT ' + block
            record = self._parse_record(block)
            if record:
                records.append(record)

        return records

    def _parse_record(self, block: str) -> Dict[str, str]:
        """解析单条记录"""
        record = {}
        lines = block.split('\n')

        current_field = None
        current_value = []

        for line in lines:
            if line.strip() == 'ER':
                if current_field:
                    record[current_field] = '\n'.join(current_value)
                break

            if len(line) >= 3 and line[:2].isupper() and line[2] == ' ':
                if current_field:
                    record[current_field] = '\n'.join(current_value)
                current_field = line[:2]
                current_value = [line[3:]]
            elif line.startswith('   ') and current_field:
                current_value.append(line[3:])

        return record

    def _write_wos_file(self, records: List[Dict], output_file: str):
        """写入WOS文件"""
        with open(output_file, 'w', encoding='utf-8-sig') as f:
            f.write('FN Clarivate Analytics Web of Science\n')
            f.write('VR 1.0\n')

            for record in records:
                f.write('\nPT J\n')

                field_order = ['AU', 'AF', 'TI', 'SO', 'LA', 'DT', 'DE', 'ID', 'AB',
                              'C1', 'C3', 'RP', 'CR', 'NR', 'TC', 'Z9', 'U1', 'U2',
                              'PU', 'SN', 'J9', 'JI', 'PY', 'VL', 'IS', 'AR', 'DI',
                              'WE', 'UT', 'PM', 'DA']

                for field in field_order:
                    if field in record:
                        value = record[field]
                        lines = value.split('\n')
                        f.write(f'{field} {lines[0]}\n')
                        for line in lines[1:]:
                            f.write(f'   {line}\n')

                f.write('ER\n')

            f.write('\nEF\n')

    def get_statistics(self) -> Dict:
        """获取统计信息"""
        gemini_stats = self.gemini.get_statistics()

        total = self.stats['total_processed']
        enrichment_rate = self.stats['enriched'] / total * 100 if total > 0 else 0

        return {
            'processing': {
                'total_processed': total,
                'enriched': self.stats['enriched'],
                'failed': self.stats['failed'],
                'enrichment_rate': f"{enrichment_rate:.1f}%"
            },
            'database': gemini_stats['database'],
            'session': gemini_stats['session']
        }

    def print_statistics(self):
        """打印统计信息"""
        stats = self.get_statistics()

        print("\n" + "=" * 80)
        print("机构信息补全统计报告")
        print("=" * 80)
        print()
        print("【处理统计】")
        print(f"  总处理数: {stats['processing']['total_processed']}")
        print(f"  补全成功: {stats['processing']['enriched']}")
        print(f"  补全失败: {stats['processing']['failed']}")
        print(f"  补全率: {stats['processing']['enrichment_rate']}")
        print()
        print("【数据库统计】")
        print(f"  数据库总机构数: {stats['database']['total_institutions']}")
        print(f"  历史AI调用总数: {stats['database']['total_ai_calls_ever']}")
        print()
        print("【本次会话】")
        print(f"  数据库命中: {stats['session']['db_hits']}")
        print(f"  数据库未命中: {stats['session']['db_misses']}")
        print(f"  命中率: {stats['database']['hit_rate']}")
        print(f"  AI调用次数: {stats['session']['ai_calls']}")
        print()
        print("💡 提示:")
        if stats['session']['ai_calls'] > 0:
            print(f"  - 本次新增 {stats['session']['ai_calls']} 个机构到数据库")
            print("  - 下次运行这些机构将直接从数据库读取，无需调用AI")
        if stats['session']['db_hits'] > 0:
            print(f"  - 本次从数据库直接获取了 {stats['session']['db_hits']} 个机构信息")
            print(f"  - 节省了 {stats['session']['db_hits']} 次AI调用！")
        print("=" * 80)


def main():
    """命令行工具"""
    import argparse

    parser = argparse.ArgumentParser(
        description='使用Gemini AI补全机构信息 v2.0（优化版）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
新特性:
  - 数据库缓存：优先查询数据库，没有才调用AI
  - 重试机制：API失败自动重试3次
  - 批量优化：定期保存数据库
  - 增加token：max_tokens增加到5000

示例:
  # 补全单个文件
  python3 institution_enricher_v2.py --input scopus_converted.txt --output enriched.txt

  # 使用自定义API配置
  python3 institution_enricher_v2.py --input scopus_converted.txt --output enriched.txt \\
      --api-key YOUR_KEY --api-url YOUR_URL --model gemini-2.5-flash-lite
        """
    )

    parser.add_argument('--input', '-i', required=True, help='输入WOS文件')
    parser.add_argument('--output', '-o', required=True, help='输出WOS文件')
    parser.add_argument('--api-key', help='Gemini API密钥')
    parser.add_argument('--api-url', help='Gemini API地址')
    parser.add_argument('--model', help='Gemini模型名称')
    parser.add_argument('--db-path', default='config/institution_ai_cache.json',
                       help='数据库路径（默认: config/institution_ai_cache.json）')
    parser.add_argument('--save-interval', type=int, default=5,
                       help='每处理多少条记录保存一次数据库（默认: 5）')
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                       default='INFO', help='日志级别')

    args = parser.parse_args()

    # 设置日志级别
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    # 创建Gemini配置
    if args.api_key:
        config = GeminiConfig.from_params(
            api_key=args.api_key,
            api_url=args.api_url or 'https://generativelanguage.googleapis.com/v1beta',
            model=args.model or 'gemini-2.5-flash-lite'
        )
    else:
        # 使用默认配置
        config = GeminiConfig.from_params(
            api_key=os.getenv('GEMINI_API_KEY', 'YOUR_API_KEY'),
            api_url=os.getenv('GEMINI_API_URL', 'https://generativelanguage.googleapis.com/v1beta'),
            model='gemini-2.5-flash-lite'
        )

    if not config.validate():
        print("✗ Gemini API配置无效")
        return

    print("\n" + "=" * 80)
    print("机构信息补全器 v2.0（优化版）")
    print("=" * 80)
    print(f"输入文件: {args.input}")
    print(f"输出文件: {args.output}")
    print(f"数据库: {args.db_path}")
    print(f"API模型: {config.model}")
    print(f"Max tokens: {config.max_tokens}")
    print(f"重试次数: {config.max_retries}")
    print("=" * 80)
    print()

    # 创建补全器
    enricher = InstitutionEnricherV2(config, args.db_path)

    # 补全文件
    enricher.enrich_file(args.input, args.output, args.save_interval)

    # 打印统计
    enricher.print_statistics()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    main()
