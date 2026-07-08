#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gemini AI机构信息增强器 v2.0（优化版）

新特性：
1. 数据库缓存（优先查询数据库，没有才调用AI）
2. 重试机制（API失败自动重试）
3. 批量处理优化
4. 增加max_tokens到5000

作者：Meng Linghan
开发工具：Claude Code
日期：2025-11-10
版本：v2.0
"""

import re
import json
import time
import logging
import requests
from typing import Dict, List, Optional
from ..gemini_config import GeminiConfig
from ..utils.paths import resolve_project_path

logger = logging.getLogger(__name__)


class InstitutionDatabase:
    """机构信息数据库（持久化缓存）"""

    def __init__(self, db_path: str = 'config/institution_ai_cache.json'):
        """
        初始化数据库

        Args:
            db_path: 数据库文件路径
        """
        self.db_path = resolve_project_path(db_path)
        self.db = self._load_database()
        self.stats = {
            'db_hits': 0,
            'db_misses': 0,
            'ai_calls': 0
        }

    def _load_database(self) -> Dict:
        """加载数据库"""
        if self.db_path.exists():
            try:
                with open(self.db_path, encoding='utf-8') as f:
                    db = json.load(f)
                    logger.info(f"✓ 加载了数据库: {len(db.get('institutions', {}))} 个机构")
                    return db
            except Exception as e:
                logger.warning(f"加载数据库失败: {e}，创建新数据库")

        return {
            'metadata': {
                'version': '2.0',
                'created': time.strftime('%Y-%m-%d %H:%M:%S'),
                'last_updated': time.strftime('%Y-%m-%d %H:%M:%S'),
                'total_institutions': 0,
                'total_ai_calls': 0
            },
            'institutions': {}
        }

    def save_database(self):
        """保存数据库"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # 更新元数据
        self.db['metadata']['last_updated'] = time.strftime('%Y-%m-%d %H:%M:%S')
        self.db['metadata']['total_institutions'] = len(self.db['institutions'])

        # 备份旧数据库
        if self.db_path.exists():
            backup_dir = self.db_path.parent / 'ai_cache_backup'
            backup_dir.mkdir(exist_ok=True)
            backup_path = backup_dir / f"cache_{time.strftime('%Y%m%d_%H%M%S')}.json"
            import shutil
            shutil.copy(self.db_path, backup_path)

        # 保存新数据库
        with open(self.db_path, 'w', encoding='utf-8') as f:
            json.dump(self.db, f, ensure_ascii=False, indent=2)

        logger.info(f"✓ 数据库已保存: {self.db_path}")

    def get_institution(self, institution: str, city: str, country: str) -> Optional[Dict]:
        """
        从数据库查询机构信息

        Args:
            institution: 机构名称
            city: 城市
            country: 国家

        Returns:
            机构信息字典，如果不存在返回None
        """
        key = self._make_key(institution, city, country)

        if key in self.db['institutions']:
            self.stats['db_hits'] += 1
            logger.info(f"✓ 数据库命中: {institution}")
            return self.db['institutions'][key]

        self.stats['db_misses'] += 1
        return None

    def add_institution(self, institution: str, city: str, country: str, info: Dict):
        """
        添加机构信息到数据库

        Args:
            institution: 机构名称
            city: 城市
            country: 国家
            info: AI补全的机构信息
        """
        key = self._make_key(institution, city, country)

        # 添加元数据
        info['_metadata'] = {
            'added_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'source': 'gemini_ai',
            'original_query': {
                'institution': institution,
                'city': city,
                'country': country
            }
        }

        self.db['institutions'][key] = info
        self.db['metadata']['total_ai_calls'] += 1
        self.stats['ai_calls'] += 1

        logger.info(f"✓ 已添加到数据库: {institution}")

    def _make_key(self, institution: str, city: str, country: str) -> str:
        """生成数据库键"""
        # 标准化键（小写，去除标点）
        key = f"{institution}|{city}|{country}".lower()
        key = re.sub(r'[^\w\s|]', '', key)
        key = ' '.join(key.split())
        return key

    def get_statistics(self) -> Dict:
        """获取统计信息"""
        total_queries = self.stats['db_hits'] + self.stats['db_misses']
        hit_rate = self.stats['db_hits'] / total_queries * 100 if total_queries > 0 else 0

        return {
            'total_institutions': len(self.db['institutions']),
            'db_hits': self.stats['db_hits'],
            'db_misses': self.stats['db_misses'],
            'hit_rate': f"{hit_rate:.1f}%",
            'ai_calls_this_session': self.stats['ai_calls'],
            'total_ai_calls_ever': self.db['metadata']['total_ai_calls']
        }


class GeminiEnricherV2:
    """Gemini AI增强器 v2.0（优化版）"""

    def __init__(self, config: GeminiConfig, db_path: str = 'config/institution_ai_cache.json'):
        """
        初始化增强器

        Args:
            config: Gemini配置
            db_path: 数据库路径
        """
        self.config = config
        self.api_key = config.api_key
        self.api_url = config.api_url
        self.model = config.model
        self.db = InstitutionDatabase(db_path)

        if not config.is_enabled():
            raise ValueError("Gemini API未启用，请检查配置")

        logger.info("✓ Gemini增强器v2.0已初始化")
        logger.info(f"  - 模型: {self.model}")
        logger.info(f"  - Max tokens: {config.max_tokens}")
        logger.info(f"  - 重试次数: {config.max_retries}")
        logger.info(f"  - 数据库: {len(self.db.db['institutions'])} 个机构")

    def enrich_institutions_batch(self, institutions: List[tuple]) -> Dict[tuple, Optional[Dict]]:
        """
        批量补全机构信息（每次请求10个）

        Args:
            institutions: [(institution_name, city, country), ...]

        Returns:
            {(institution_name, city, country): result_dict, ...}
        """
        results = {}
        to_enrich = []

        # 先检查数据库
        for inst_tuple in institutions:
            institution_name, city, country = inst_tuple
            cached = self.db.get_institution(institution_name, city, country)
            if cached:
                results[inst_tuple] = cached
            else:
                to_enrich.append(inst_tuple)

        if not to_enrich:
            return results

        # 批量调用AI（每次10个）
        batch_size = 10
        for i in range(0, len(to_enrich), batch_size):
            batch = to_enrich[i:i + batch_size]
            logger.info(f"⚡ 批量AI补全: {len(batch)} 个机构 (批次 {i//batch_size + 1}/{(len(to_enrich)-1)//batch_size + 1})")

            batch_results = self._call_ai_batch(batch)

            # 保存到数据库
            for inst_tuple, result in batch_results.items():
                institution_name, city, country = inst_tuple
                if result:
                    self.db.add_institution(institution_name, city, country, result)
                    logger.info(f"✓ {institution_name} (置信度: {result.get('confidence', 0):.2f})")
                results[inst_tuple] = result

            # 批次间延迟，避免429错误
            if i + batch_size < len(to_enrich):
                logger.info("⏸️  批次间延迟2秒...")
                time.sleep(2.0)

        return results

    def enrich_institution(
        self,
        institution_name: str,
        city: str,
        country: str,
        existing_info: Optional[Dict] = None
    ) -> Optional[Dict]:
        """
        补全机构信息（优先查询数据库）

        Args:
            institution_name: 机构名称
            city: 城市
            country: 国家
            existing_info: 已有的信息（可选）

        Returns:
            补全后的机构信息字典，如果失败返回None
        """
        # 步骤1: 优先查询数据库
        cached = self.db.get_institution(institution_name, city, country)
        if cached:
            return cached

        # 步骤2: 数据库没有，调用AI
        logger.info(f"⚡ 调用AI补全: {institution_name}, {city}, {country}")

        result = self._call_ai_with_retry(institution_name, city, country, existing_info)

        # 步骤3: 保存到数据库
        if result:
            self.db.add_institution(institution_name, city, country, result)
            logger.info(f"✓ AI补全成功: {institution_name} (置信度: {result.get('confidence', 0):.2f})")
        else:
            logger.warning(f"✗ AI补全失败: {institution_name}")

        return result

    def _call_ai_with_retry(
        self,
        institution_name: str,
        city: str,
        country: str,
        existing_info: Optional[Dict] = None
    ) -> Optional[Dict]:
        """
        调用AI（简化版，重试逻辑在 _call_gemini_api 中）

        Args:
            institution_name: 机构名称
            city: 城市
            country: 国家
            existing_info: 已有的信息

        Returns:
            AI补全结果
        """
        try:
            # 构建提示词
            prompt = self._build_prompt(institution_name, city, country, existing_info)

            # 调用API（内置重试逻辑：5秒×5次 + 2分钟×7次）
            response = self._call_gemini_api(prompt)

            if response:
                # 解析响应
                result = self._parse_response(response)
                if result:
                    return result
                else:
                    logger.error(f"✗ 解析响应失败: {institution_name}")
            else:
                logger.error(f"✗ API调用失败（所有重试均失败）: {institution_name}")

        except Exception as e:
            logger.error(f"✗ 调用AI时出错: {e}")

        return None

    def _build_prompt(
        self,
        institution_name: str,
        city: str,
        country: str,
        existing_info: Optional[Dict] = None
    ) -> str:
        """构建Gemini API的提示词"""

        prompt = f"""You are an expert in academic institutions and geographic information worldwide.

Task: Complete the missing information for this institution to match Web of Science (WOS) format.

Input:
- Institution: {institution_name}
- City: {city}
- Country: {country}"""

        if existing_info:
            prompt += f"\n- Existing departments: {', '.join(existing_info.get('departments', []))}"

        prompt += """

Please provide the following information in JSON format:
1. **institution_full_name**: Full standardized name (use WOS-style abbreviations)
   - Examples: "Univ" not "University", "Inst" not "Institute", "Ctr" not "Center"
   - Examples: "Med" not "Medical", "Hosp" not "Hospital", "Canc" not "Cancer"

2. **departments**: List of common departments (use WOS-style abbreviations)
   - For cancer institutes: ["Oncol & Hematol"] or ["Med Oncol"]
   - For universities: ["Sch Med", "Dept Pathol"]
   - Keep it concise, 1-3 departments maximum

3. **city**: City name (standardized)

4. **state**: State/Province code or name
   - For USA: 2-letter state code (FL, CA, NY, NC, etc.)
   - For China: Province name in English (Hunan, Guangdong, etc.)
   - For other countries: Province/State name if applicable, otherwise null

5. **zip_code**: ZIP/Postal code (if known)
   - For USA: 5-digit ZIP code
   - For China: 6-digit postal code
   - For other countries: postal code if known
   - If unknown, use null

6. **country**: Country name (standardized to WOS format)
   - USA (not United States)
   - Peoples R China (not China, for mainland China)
   - England (not UK, for England specifically)
   - Turkiye (not Turkey)

7. **confidence**: Confidence score (0.0-1.0)
   - 0.9-1.0: Very confident (well-known institution)
   - 0.7-0.9: Confident (can infer from context)
   - 0.5-0.7: Moderate (some uncertainty)
   - Below 0.5: Low confidence (mostly guessing)

Important guidelines:
- Use WOS-style abbreviations consistently
- For US institutions, always try to provide state code and ZIP code
- For Chinese institutions, provide province and 6-digit postal code
- If you're not sure about ZIP code, set it to null rather than guessing
- Be conservative with confidence scores

Output format (JSON only, no explanation):
{{
    "institution_full_name": "...",
    "departments": ["...", "..."],
    "city": "...",
    "state": "...",
    "zip_code": "...",
    "country": "...",
    "confidence": 0.95
}}

Examples:

Example 1 (US Cancer Institute):
Input: "AdventHealth Cancer Inst", "Orlando", "USA"
Output:
{{
    "institution_full_name": "AdventHlth Canc Inst",
    "departments": ["Oncol & Hematol"],
    "city": "Orlando",
    "state": "FL",
    "zip_code": "32804",
    "country": "USA",
    "confidence": 0.95
}}

Example 2 (Chinese University):
Input: "Hunan University of Chinese Medicine", "Changsha", "China"
Output:
{{
    "institution_full_name": "Hunan Univ Chinese Med",
    "departments": ["Sch Integrated Chinese & Western Med"],
    "city": "Changsha",
    "state": "Hunan",
    "zip_code": "410208",
    "country": "Peoples R China",
    "confidence": 0.90
}}

Example 3 (French University):
Input: "University of Clermont Auvergne", "Clermont-Ferrand", "France"
Output:
{{
    "institution_full_name": "Univ Clermont Auvergne",
    "departments": ["Ctr Jean Perrin", "Dept Pathol"],
    "city": "Clermont Ferrand",
    "state": null,
    "zip_code": "63000",
    "country": "France",
    "confidence": 0.88
}}

Now process the input above and return ONLY the JSON output:"""

        return prompt

    def _call_gemini_api(self, prompt: str) -> Optional[str]:
        """
        调用Gemini API（改进的重试逻辑）

        重试策略：
        - 前5次：每次间隔5秒（快速重试）
        - 后7次：每次间隔2分钟（慢速重试，针对429限流）
        - 总共最多12次重试
        """
        # ✅ 速率限制：在API调用前延迟（避免429错误）
        time.sleep(1.5)

        url = f"{self.api_url}/models/{self.model}:generateContent"

        headers = {
            'Content-Type': 'application/json',
        }

        data = {
            'contents': [{
                'parts': [{
                    'text': prompt
                }]
            }],
            'generationConfig': {
                'temperature': self.config.temperature,
                'maxOutputTokens': self.config.max_tokens,
            }
        }

        max_retries = 12  # 总共最多重试12次
        retry_count = 0

        while retry_count <= max_retries:
            try:
                response = requests.post(
                    url,
                    headers=headers,
                    params={'key': self.api_key},
                    json=data,
                    timeout=self.config.timeout
                )

                if response.status_code == 200:
                    result = response.json()

                    # 检查响应结构（parts 可能为空列表或缺 text，如 MAX_TOKENS/安全拦截）
                    candidates = result.get('candidates') or []
                    if candidates:
                        parts = (candidates[0].get('content') or {}).get('parts') or []
                        if parts and 'text' in parts[0]:
                            return parts[0]['text']
                        logger.error(f"响应格式错误: {result}")
                        return None
                    else:
                        logger.error(f"响应中没有candidates: {result}")
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
                    logger.error(f"Gemini API错误: {response.status_code} - {response.text[:200]}")

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
                    logger.warning(f"⚠️ 调用Gemini API失败: {e}，等待{wait_time}秒后重试... (尝试 {retry_count}/{max_retries}，快速重试阶段)")
                else:
                    wait_time = 120
                    logger.warning(f"⚠️ 调用Gemini API失败: {e}，等待{wait_time}秒（2分钟）后重试... (尝试 {retry_count}/{max_retries}，慢速重试阶段)")

                time.sleep(wait_time)
                continue

        # 不应该到达这里
        logger.error("✗ API调用失败，已达最大重试次数")
        return None

    def _parse_response(self, response: str) -> Optional[Dict]:
        """解析Gemini API的响应"""

        try:
            # 提取JSON部分（可能包含在markdown代码块中）
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # 尝试直接提取JSON
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    logger.warning(f"无法从响应中提取JSON: {response[:200]}...")
                    return None

            # 解析JSON
            data = json.loads(json_str)

            # 验证必需字段
            required_fields = ['institution_full_name', 'city', 'country', 'confidence']
            for field in required_fields:
                if field not in data:
                    logger.warning(f"响应缺少必需字段: {field}")
                    return None

            # 标准化数据
            result = {
                'institution_full_name': data['institution_full_name'],
                'departments': data.get('departments', []),
                'city': data['city'],
                'state': data.get('state'),
                'zip_code': data.get('zip_code'),
                'country': data['country'],
                'confidence': float(data['confidence'])
            }

            return result

        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}")
            logger.debug(f"原始响应: {response}")
            return None
        except Exception as e:
            logger.error(f"解析Gemini响应失败: {e}")
            return None

    def _call_ai_batch(self, institutions: List[tuple]) -> Dict[tuple, Optional[Dict]]:
        """批量调用AI（一次请求处理10个机构）"""
        import json
        results = {}

        # 构建批量prompt
        inst_list = []
        for i, (inst_name, city, country) in enumerate(institutions, 1):
            inst_list.append(f"{i}. Institution: {inst_name}, City: {city}, Country: {country}")

        institutions_text = '\n'.join(inst_list)

        prompt = f"""You are an expert in academic institutions and geographic information worldwide.

Task: Complete the missing information for these {len(institutions)} institutions to match Web of Science (WOS) format.

Institutions:
{institutions_text}

For each institution, provide JSON with:
- institution_full_name (WOS abbreviations: Univ, Inst, Med, Hosp, Canc, Ctr)
- departments (1-3 max, WOS abbreviations: Oncol, Dept, Sch)
- city, state (US: 2-letter code; China: province name), zip_code, country (WOS format)
- confidence (0.0-1.0)

Output format (JSON array, one object per institution):
[
  {{"id": 1, "institution_full_name": "...", "departments": ["..."], "city": "...", "state": "...", "zip_code": "...", "country": "...", "confidence": 0.95}},
  {{"id": 2, ...}}
]

Output ONLY the JSON array, no explanation:"""

        try:
            response = self._call_gemini_api(prompt)
            if not response:
                logger.error("API返回空响应")
                for inst_tuple in institutions:
                    results[inst_tuple] = None
                return results

            # 清理响应（移除markdown代码块标记）
            response = response.strip()
            if response.startswith('```'):
                lines = response.split('\n')
                response = '\n'.join(lines[1:-1]) if len(lines) > 2 else response
            response = response.strip()

            # 解析JSON数组
            data = json.loads(response)

            for item in data:
                idx = item.get('id', 0) - 1
                if 0 <= idx < len(institutions):
                    inst_tuple = institutions[idx]
                    results[inst_tuple] = {
                        'institution_full_name': item.get('institution_full_name', ''),
                        'departments': item.get('departments', []),
                        'city': item.get('city', ''),
                        'state': item.get('state'),
                        'zip_code': item.get('zip_code'),
                        'country': item.get('country', ''),
                        'confidence': item.get('confidence', 0.5)
                    }
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}")
            logger.error(f"原始响应: {response[:500] if response else 'None'}")
            # 失败时返回空结果
            for inst_tuple in institutions:
                results[inst_tuple] = None
        except Exception as e:
            logger.error(f"批量AI调用失败: {e}")
            for inst_tuple in institutions:
                results[inst_tuple] = None

        return results

    def batch_enrich(self, institutions: List[Dict], save_interval: int = 10) -> List[Dict]:
        """
        批量补全机构信息（优化版）

        Args:
            institutions: 机构信息列表
            save_interval: 每处理多少个机构保存一次数据库

        Returns:
            补全后的机构信息列表
        """
        results = []
        total = len(institutions)

        logger.info(f"开始批量补全 {total} 个机构...")

        for i, inst in enumerate(institutions, 1):
            logger.info(f"进度: {i}/{total} ({i/total*100:.1f}%)")

            result = self.enrich_institution(
                inst['institution'],
                inst['city'],
                inst['country'],
                inst.get('existing_info')
            )

            if result:
                results.append(result)

            # 定期保存数据库
            if i % save_interval == 0:
                self.db.save_database()
                logger.info(f"✓ 已保存数据库（进度: {i}/{total}）")

        # 最后保存一次
        self.db.save_database()

        logger.info(f"批量补全完成: 成功 {len(results)}/{total} ({len(results)/total*100:.1f}%)")

        return results

    def get_statistics(self) -> Dict:
        """获取统计信息"""
        db_stats = self.db.get_statistics()
        return {
            'database': db_stats,
            'session': {
                'ai_calls': db_stats['ai_calls_this_session'],
                'db_hits': db_stats['db_hits'],
                'db_misses': db_stats['db_misses']
            }
        }

    def print_statistics(self):
        """打印统计信息"""
        stats = self.get_statistics()

        print("\n" + "=" * 80)
        print("Gemini AI增强器统计")
        print("=" * 80)
        print("【数据库统计】")
        print(f"  总机构数: {stats['database']['total_institutions']}")
        print(f"  历史AI调用: {stats['database']['total_ai_calls_ever']}")
        print()
        print("【本次会话】")
        print(f"  数据库命中: {stats['session']['db_hits']}")
        print(f"  数据库未命中: {stats['session']['db_misses']}")
        print(f"  命中率: {stats['database']['hit_rate']}")
        print(f"  AI调用次数: {stats['session']['ai_calls']}")
        print("=" * 80)


def main():
    """测试增强器v2.0"""
    import argparse

    parser = argparse.ArgumentParser(description='测试Gemini机构信息增强器v2.0')
    parser.add_argument('--institution', required=True, help='机构名称')
    parser.add_argument('--city', required=True, help='城市')
    parser.add_argument('--country', required=True, help='国家')

    args = parser.parse_args()

    # 创建配置（API key/URL/model 均取环境变量，默认官方端点）
    config = GeminiConfig()

    # 创建增强器
    enricher = GeminiEnricherV2(config)

    # 测试补全
    print("\n" + "=" * 80)
    print("Gemini机构信息增强器v2.0测试")
    print("=" * 80)
    print(f"机构: {args.institution}")
    print(f"城市: {args.city}")
    print(f"国家: {args.country}")
    print("=" * 80)
    print()

    result = enricher.enrich_institution(args.institution, args.city, args.country)

    if result:
        print("✓ 补全成功！")
        print()
        print("补全结果:")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("✗ 补全失败")

    # 打印统计
    enricher.print_statistics()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    main()
