#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WOS格式标准化器（批量并发版）

支持大规模批量并发调用AI，显著提升处理速度：
1. 批量处理作者名、国家名、期刊名
2. 并发API调用（使用线程池）
3. 智能去重（避免重复调用）
4. 数据库缓存

作者：Meng Linghan
开发工具：Claude Code
日期：2025-11-11
版本：v2.0 (批量并发版)
"""

import re
import json
import time
import logging
import requests
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from ..gemini_config import GeminiConfig
from ..utils.paths import resolve_project_path

logger = logging.getLogger(__name__)


class WOSStandardDatabase:
    """WOS标准格式数据库"""

    def __init__(self, db_path: str = 'config/wos_standard_cache.json'):
        self.db_path = resolve_project_path(db_path)
        self.db = self._load_database()

    def _load_database(self) -> Dict:
        if self.db_path.exists():
            try:
                with open(self.db_path, encoding='utf-8') as f:
                    db = json.load(f)
                    logger.info(f"✓ 加载WOS标准数据库: {len(db.get('authors', {}))} 作者, {len(db.get('countries', {}))} 国家, {len(db.get('journals', {}))} 期刊")
                    return db
            except Exception as e:
                logger.warning(f"加载数据库失败: {e}")

        return {
            'metadata': {
                'version': '2.0',
                'created': time.strftime('%Y-%m-%d %H:%M:%S'),
                'last_updated': time.strftime('%Y-%m-%d %H:%M:%S')
            },
            'authors': {},      # 作者名标准化
            'countries': {},    # 国家名WOS标准
            'journals': {},     # 期刊名WOS缩写
            'institutions': {}  # 机构名WOS标准
        }

    def save_database(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db['metadata']['last_updated'] = time.strftime('%Y-%m-%d %H:%M:%S')

        with open(self.db_path, 'w', encoding='utf-8') as f:
            json.dump(self.db, f, ensure_ascii=False, indent=2)

        logger.info("✓ WOS标准数据库已保存")

    def get_author(self, author_name: str) -> Optional[str]:
        """获取作者WOS标准名称"""
        key = self._normalize_key(author_name)
        return self.db['authors'].get(key)

    def add_author(self, original: str, wos_standard: str):
        """添加作者标准化映射"""
        key = self._normalize_key(original)
        self.db['authors'][key] = wos_standard

    def add_authors_batch(self, mappings: Dict[str, str]):
        """批量添加作者标准化映射"""
        for original, wos_standard in mappings.items():
            self.add_author(original, wos_standard)

    def get_country(self, country_name: str) -> Optional[str]:
        """获取国家WOS标准名称"""
        key = self._normalize_key(country_name)
        return self.db['countries'].get(key)

    def add_country(self, original: str, wos_standard: str):
        """添加国家标准化映射"""
        key = self._normalize_key(original)
        self.db['countries'][key] = wos_standard

    def add_countries_batch(self, mappings: Dict[str, str]):
        """批量添加国家标准化映射"""
        for original, wos_standard in mappings.items():
            self.add_country(original, wos_standard)

    def get_journal(self, journal_name: str) -> Optional[str]:
        """获取期刊WOS标准缩写"""
        key = self._normalize_key(journal_name)
        return self.db['journals'].get(key)

    def add_journal(self, original: str, wos_abbrev: str):
        """添加期刊缩写映射"""
        key = self._normalize_key(original)
        self.db['journals'][key] = wos_abbrev

    def add_journals_batch(self, mappings: Dict[str, str]):
        """批量添加期刊缩写映射"""
        for original, wos_abbrev in mappings.items():
            self.add_journal(original, wos_abbrev)

    def _normalize_key(self, text: str) -> str:
        """标准化键（小写，去除标点）"""
        key = text.lower().strip()
        key = re.sub(r'[^\w\s-]', '', key)
        key = ' '.join(key.split())
        return key


class WOSStandardizerBatch:
    """WOS格式标准化器（批量并发版）"""

    def __init__(self, config: GeminiConfig, db_path: str = 'config/wos_standard_cache.json',
                 max_workers: int = 5, batch_size: int = 20):
        self.config = config
        self.db = WOSStandardDatabase(db_path)
        self.max_workers = max_workers  # 并发线程数（降低到5，避免429错误）
        self.batch_size = batch_size    # 每批处理数量（降低到20）
        self.request_delay = 1.5  # 每次请求间隔（秒）
        self.stats = {
            'author_hits': 0,
            'author_misses': 0,
            'country_hits': 0,
            'country_misses': 0,
            'journal_hits': 0,
            'journal_misses': 0,
            'api_calls': 0
        }

    def standardize_authors_batch(self, author_names: List[str]) -> Dict[str, str]:
        """批量标准化作者名"""
        # 去重
        unique_authors = list(set(author_names))

        # 检查数据库，分离已缓存和未缓存的
        cached = {}
        to_process = []

        for author in unique_authors:
            cached_result = self.db.get_author(author)
            if cached_result:
                cached[author] = cached_result
                self.stats['author_hits'] += 1
            else:
                to_process.append(author)
                self.stats['author_misses'] += 1

        logger.info(f"作者标准化: 缓存命中 {len(cached)}, 需要AI处理 {len(to_process)}")

        # 批量调用AI处理未缓存的
        if to_process:
            ai_results = self._batch_ai_standardize_authors(to_process)
            # 保存到数据库
            self.db.add_authors_batch(ai_results)
            cached.update(ai_results)

        return cached

    def standardize_countries_batch(self, country_names: List[str]) -> Dict[str, str]:
        """批量标准化国家名"""
        # 去重
        unique_countries = list(set(country_names))

        # 检查数据库
        cached = {}
        to_process = []

        for country in unique_countries:
            cached_result = self.db.get_country(country)
            if cached_result:
                cached[country] = cached_result
                self.stats['country_hits'] += 1
            else:
                to_process.append(country)
                self.stats['country_misses'] += 1

        logger.info(f"国家标准化: 缓存命中 {len(cached)}, 需要AI处理 {len(to_process)}")

        # 批量调用AI
        if to_process:
            ai_results = self._batch_ai_standardize_countries(to_process)
            self.db.add_countries_batch(ai_results)
            cached.update(ai_results)

        return cached

    def standardize_journals_batch(self, journal_names: List[str]) -> Dict[str, str]:
        """批量标准化期刊名"""
        # 去重
        unique_journals = list(set(journal_names))

        # 检查数据库
        cached = {}
        to_process = []

        for journal in unique_journals:
            cached_result = self.db.get_journal(journal)
            if cached_result:
                cached[journal] = cached_result
                self.stats['journal_hits'] += 1
            else:
                to_process.append(journal)
                self.stats['journal_misses'] += 1

        logger.info(f"期刊标准化: 缓存命中 {len(cached)}, 需要AI处理 {len(to_process)}")

        # 批量调用AI
        if to_process:
            ai_results = self._batch_ai_standardize_journals(to_process)
            self.db.add_journals_batch(ai_results)
            cached.update(ai_results)

        return cached

    def _batch_ai_standardize_authors(self, authors: List[str]) -> Dict[str, str]:
        """批量AI标准化作者名（并发）"""
        results = {}

        # 分批处理
        for i in range(0, len(authors), self.batch_size):
            batch = authors[i:i + self.batch_size]
            logger.info(f"处理作者批次 {i//self.batch_size + 1}/{(len(authors)-1)//self.batch_size + 1} ({len(batch)} 个)")

            # 并发调用AI
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                future_to_author = {
                    executor.submit(self._ai_standardize_author_single, author): author
                    for author in batch
                }

                for future in as_completed(future_to_author):
                    author = future_to_author[future]
                    try:
                        wos_name = future.result()
                        if wos_name:
                            results[author] = wos_name
                        else:
                            results[author] = author  # 失败时保持原样
                    except Exception as e:
                        logger.error(f"处理作者 {author} 失败: {e}")
                        results[author] = author

        return results

    def _batch_ai_standardize_countries(self, countries: List[str]) -> Dict[str, str]:
        """批量AI标准化国家名（每次请求20个）"""
        results = {}
        batch_request_size = 20  # 每次API请求处理20个

        for i in range(0, len(countries), batch_request_size):
            batch = countries[i:i + batch_request_size]
            logger.info(f"处理国家批次 {i//batch_request_size + 1}/{(len(countries)-1)//batch_request_size + 1} ({len(batch)} 个)")

            # 一次API请求处理20个国家
            batch_results = self._ai_standardize_countries_batch_request(batch)

            # 合并结果，失败的保持原样
            for country in batch:
                if country in batch_results and batch_results[country]:
                    results[country] = batch_results[country]
                else:
                    results[country] = country

            # 批次间延迟，避免429错误
            if i + batch_request_size < len(countries):
                time.sleep(2.0)

        return results

    def _batch_ai_standardize_journals(self, journals: List[str]) -> Dict[str, str]:
        """批量AI标准化期刊名（每次请求20个）"""
        results = {}
        batch_request_size = 20  # 每次API请求处理20个

        for i in range(0, len(journals), batch_request_size):
            batch = journals[i:i + batch_request_size]
            logger.info(f"处理期刊批次 {i//batch_request_size + 1}/{(len(journals)-1)//batch_request_size + 1} ({len(batch)} 个)")

            # 一次API请求处理20个期刊
            batch_results = self._ai_standardize_journals_batch_request(batch)

            # 合并结果，失败的保持原样
            for journal in batch:
                if journal in batch_results and batch_results[journal]:
                    results[journal] = batch_results[journal]
                else:
                    results[journal] = journal

            # 批次间延迟，避免429错误
            if i + batch_request_size < len(journals):
                time.sleep(2.0)

        return results

    def _ai_standardize_author_single(self, author_name: str) -> Optional[str]:
        """AI标准化单个作者名"""
        prompt = f"""You are an expert in Web of Science (WOS) author name formatting.

Task: Standardize this author name to WOS format.

Input: {author_name}

WOS Author Name Rules:
1. Remove ALL accent marks and diacritics
   - é → e, ñ → n, ö → o, ü → u, etc.
2. Keep format: Lastname, Initials
3. No spaces between initials
4. Keep hyphens in compound lastnames
5. Capitalize properly

Examples:
- "Pénault-Llorca, Frédérique M." → "Penault-Llorca, FM"
- "Remón, Javier" → "Remon, J"
- "Özgüroĝlu, Mustafa" → "Ozguroglu, M"
- "Abu Akar, Firas" → "Abu Akar, F"

Output ONLY the standardized name, no explanation:"""

        try:
            response = self._call_gemini_api(prompt)
            if response:
                wos_name = response.strip().strip('"\'')
                return wos_name
        except Exception as e:
            logger.error(f"AI标准化作者失败 {author_name}: {e}")

        return None

    def _ai_standardize_countries_batch_request(self, countries: List[str]) -> Dict[str, str]:
        """批量AI标准化国家名（一次请求处理多个）"""
        if not countries:
            return {}

        countries_list = '\n'.join([f"{i+1}. {c}" for i, c in enumerate(countries)])

        prompt = f"""You are an expert in Web of Science (WOS) country name formatting.

Task: Convert these country names to WOS standard format.

Input countries:
{countries_list}

WOS Country Name Standards:
- USA (not United States, not US)
- Peoples R China (for mainland China, not China, not PRC)
- England (not UK, for England specifically)
- Scotland (not UK, for Scotland specifically)
- Wales (not UK, for Wales specifically)
- North Ireland (not UK, for Northern Ireland)
- Turkiye (not Turkey, updated 2022)
- South Korea (not Korea)
- North Korea (not Korea)
- Taiwan (not China Taiwan)
- Hong Kong (not China Hong Kong)

Other countries: Use standard English name
- France, Germany, Italy, Spain, Japan, etc.

Output format (one per line, number and result only):
1. WOS_NAME_1
2. WOS_NAME_2
...

Output ONLY the numbered list, no explanation:"""

        try:
            response = self._call_gemini_api(prompt)
            if response:
                results = {}
                lines = response.strip().split('\n')
                for i, line in enumerate(lines):
                    if i < len(countries):
                        # 提取结果（去除序号）
                        wos_name = line.split('.', 1)[-1].strip().strip('"\'')
                        results[countries[i]] = wos_name
                return results
        except Exception as e:
            logger.error(f"批量AI标准化国家失败: {e}")

        return {}

    def _ai_standardize_journal_single(self, journal_name: str) -> Optional[str]:
        """AI标准化单个期刊名"""
        prompt = f"""You are an expert in Web of Science (WOS) journal abbreviations.

Task: Convert this journal name to WOS standard abbreviation.

Input: {journal_name}

WOS Journal Abbreviation Rules:
1. Common abbreviations:
   - Journal → J
   - American → AM
   - International → INT
   - Science → SCI
   - Medicine → MED
   - Research → RES
   - Review/Reviews → REV
   - Society → SOC
   - Technology → TECHNOL
   - Clinical → CLIN

2. Keep important words capitalized
3. Remove articles (the, a, an)
4. Use standard WOS format

Examples:
- "Nature" → "NATURE"
- "Journal of Clinical Oncology" → "J CLIN ONCOL"
- "The Lancet Oncology" → "LANCET ONCOL"
- "American Journal of Respiratory and Critical Care Medicine" → "AM J RESP CRIT CARE"

Output ONLY the WOS abbreviation in UPPERCASE, no explanation:"""

        try:
            response = self._call_gemini_api(prompt)
            if response:
                wos_abbrev = response.strip().strip('"\'').upper()
                return wos_abbrev
        except Exception as e:
            logger.error(f"AI标准化期刊失败 {journal_name}: {e}")

        return None

    def _ai_standardize_journals_batch_request(self, journals: List[str]) -> Dict[str, str]:
        """批量AI标准化期刊名（一次请求处理多个）"""
        if not journals:
            return {}

        journals_list = '\n'.join([f"{i+1}. {j}" for i, j in enumerate(journals)])

        prompt = f"""You are an expert in Web of Science (WOS) journal abbreviations.

Task: Convert these journal names to WOS standard abbreviations.

Input journals:
{journals_list}

WOS Journal Abbreviation Rules:
- Journal → J, American → AM, International → INT
- Science → SCI, Medicine → MED, Research → RES
- Review/Reviews → REV, Society → SOC, Technology → TECHNOL, Clinical → CLIN

Output format (one per line, number and abbreviation only):
1. ABBREVIATION_1
2. ABBREVIATION_2

Output ONLY the numbered list in UPPERCASE, no explanation:"""

        try:
            response = self._call_gemini_api(prompt)
            if response:
                results = {}
                lines = response.strip().split('\n')
                for i, line in enumerate(lines):
                    if i < len(journals):
                        wos_abbrev = line.split('.', 1)[-1].strip().strip('"\'').upper()
                        results[journals[i]] = wos_abbrev
                return results
        except Exception as e:
            logger.error(f"批量AI标准化期刊失败: {e}")
        return {}

    def _call_gemini_api(self, prompt: str) -> Optional[str]:
        """
        调用Gemini API（改进的重试逻辑）

        重试策略：
        - 前5次：每次间隔5秒（快速重试）
        - 后7次：每次间隔2分钟（慢速重试，针对429限流）
        - 总共最多12次重试
        """
        # ✅ 速率限制：在API调用前延迟（避免429错误）
        time.sleep(self.request_delay)

        self.stats['api_calls'] += 1

        url = f"{self.config.api_url}/models/{self.config.model}:generateContent"

        headers = {'Content-Type': 'application/json'}
        data = {
            'contents': [{'parts': [{'text': prompt}]}],
            'generationConfig': {
                'temperature': 0.1,
                'maxOutputTokens': 500
            }
        }

        max_retries = 12  # 总共最多重试12次
        retry_count = 0

        while retry_count <= max_retries:
            try:
                response = requests.post(
                    url,
                    headers=headers,
                    params={'key': self.config.api_key},
                    json=data,
                    timeout=self.config.timeout
                )

                if response.status_code == 200:
                    result = response.json()
                    candidates = result.get('candidates') or []
                    if candidates:
                        content = candidates[0].get('content') or {}
                        parts = content.get('parts') or []
                        if parts and 'text' in parts[0]:
                            return parts[0]['text'].strip()
                        # MAX_TOKENS / 安全拦截等情况没有文本，重试结果也相同，直接放弃
                        finish_reason = candidates[0].get('finishReason', 'UNKNOWN')
                        logger.error(f"响应无文本内容（finishReason={finish_reason}），跳过重试")
                        return None
                    logger.error("响应格式错误或无candidates")
                    return None

                # API返回错误，需要重试
                retry_count += 1
                if retry_count > max_retries:
                    if response.status_code == 429:
                        logger.error(f"✗ 429错误重试已达上限（{max_retries}次），放弃")
                    else:
                        logger.error(f"✗ API错误重试已达上限（{max_retries}次），放弃")
                    return None

                # 确定等待时间
                if retry_count <= 5:
                    # 前5次：每次间隔5秒
                    wait_time = 5
                    logger.warning(f"⚠️ API错误（{response.status_code}），等待{wait_time}秒后重试... (尝试 {retry_count}/{max_retries}，快速重试阶段)")
                else:
                    # 后7次：每次间隔2分钟（针对429限流）
                    wait_time = 120
                    logger.warning(f"⚠️ API错误（{response.status_code}），等待{wait_time}秒（2分钟）后重试... (尝试 {retry_count}/{max_retries}，慢速重试阶段)")

                if response.status_code != 200:
                    logger.error(f"API错误: {response.status_code} - {response.text[:200]}")

                time.sleep(wait_time)
                logger.info("继续重试...")
                continue

            except requests.exceptions.Timeout:
                retry_count += 1
                if retry_count > max_retries:
                    logger.error(f"✗ 超时错误重试已达上限（{max_retries}次），放弃")
                    return None

                # 确定等待时间
                if retry_count <= 5:
                    wait_time = 5
                    logger.warning(f"⚠️ API调用超时（{self.config.timeout}秒），等待{wait_time}秒后重试... (尝试 {retry_count}/{max_retries}，快速重试阶段)")
                else:
                    wait_time = 120
                    logger.warning(f"⚠️ API调用超时（{self.config.timeout}秒），等待{wait_time}秒（2分钟）后重试... (尝试 {retry_count}/{max_retries}，慢速重试阶段)")

                time.sleep(wait_time)
                continue

            except Exception as e:
                retry_count += 1
                if retry_count > max_retries:
                    logger.error(f"✗ API异常重试已达上限（{max_retries}次），放弃")
                    return None

                # 确定等待时间
                if retry_count <= 5:
                    wait_time = 5
                    logger.warning(f"⚠️ API调用异常: {e}，等待{wait_time}秒后重试... (尝试 {retry_count}/{max_retries}，快速重试阶段)")
                else:
                    wait_time = 120
                    logger.warning(f"⚠️ API调用异常: {e}，等待{wait_time}秒（2分钟）后重试... (尝试 {retry_count}/{max_retries}，慢速重试阶段)")

                time.sleep(wait_time)
                continue

        # 不应该到达这里
        logger.error("✗ API调用失败，已达最大重试次数")
        return None

    def get_statistics(self) -> Dict:
        """获取统计信息"""
        total_author = self.stats['author_hits'] + self.stats['author_misses']
        total_country = self.stats['country_hits'] + self.stats['country_misses']
        total_journal = self.stats['journal_hits'] + self.stats['journal_misses']

        return {
            'authors': {
                'hits': self.stats['author_hits'],
                'misses': self.stats['author_misses'],
                'hit_rate': f"{self.stats['author_hits']/total_author*100:.1f}%" if total_author > 0 else "0%"
            },
            'countries': {
                'hits': self.stats['country_hits'],
                'misses': self.stats['country_misses'],
                'hit_rate': f"{self.stats['country_hits']/total_country*100:.1f}%" if total_country > 0 else "0%"
            },
            'journals': {
                'hits': self.stats['journal_hits'],
                'misses': self.stats['journal_misses'],
                'hit_rate': f"{self.stats['journal_hits']/total_journal*100:.1f}%" if total_journal > 0 else "0%"
            },
            'api_calls': self.stats['api_calls']
        }


def main():
    """测试批量标准化器"""
    # 创建配置（API key/URL/model 均取环境变量，默认官方端点）
    config = GeminiConfig()

    # 创建批量标准化器（5个并发线程，避免429错误）
    standardizer = WOSStandardizerBatch(config, max_workers=5, batch_size=20)

    # 测试数据
    test_authors = [
        "Pénault-Llorca, Frédérique M.",
        "Remón, Javier",
        "Özgüroĝlu, Mustafa",
        "Wang, Z",
        "Li, Y"
    ]

    test_countries = [
        "China",
        "United States",
        "UK",
        "Turkey"
    ]

    test_journals = [
        "Nature",
        "Journal of Clinical Oncology",
        "The Lancet Oncology"
    ]

    print("\n" + "=" * 80)
    print("WOS格式批量标准化器测试")
    print("=" * 80)
    print()

    # 批量处理作者
    print("批量处理作者名...")
    author_results = standardizer.standardize_authors_batch(test_authors)
    for original, standardized in author_results.items():
        print(f"  {original} → {standardized}")
    print()

    # 批量处理国家
    print("批量处理国家名...")
    country_results = standardizer.standardize_countries_batch(test_countries)
    for original, standardized in country_results.items():
        print(f"  {original} → {standardized}")
    print()

    # 批量处理期刊
    print("批量处理期刊名...")
    journal_results = standardizer.standardize_journals_batch(test_journals)
    for original, standardized in journal_results.items():
        print(f"  {original} → {standardized}")
    print()

    # 保存数据库
    standardizer.db.save_database()

    # 显示统计
    stats = standardizer.get_statistics()
    print("统计信息:")
    print(f"  作者: 命中 {stats['authors']['hits']}, 未命中 {stats['authors']['misses']}, 命中率 {stats['authors']['hit_rate']}")
    print(f"  国家: 命中 {stats['countries']['hits']}, 未命中 {stats['countries']['misses']}, 命中率 {stats['countries']['hit_rate']}")
    print(f"  期刊: 命中 {stats['journals']['hits']}, 未命中 {stats['journals']['misses']}, 命中率 {stats['journals']['hit_rate']}")
    print(f"  总API调用: {stats['api_calls']}")
    print()
    print("=" * 80)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    main()
