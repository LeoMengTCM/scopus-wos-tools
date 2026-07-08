#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scopus CSV to WOS Plain Text Converter
======================================

将Scopus数据库导出的CSV文件转换为Web of Science纯文本格式。
用于文献计量学分析工具（CiteSpace, VOSviewer, Bibliometrix等）。

作者：Meng Linghan
开发工具：Claude Code
日期：2025-11-05
版本：v3.1（重大修复版 - C1字段完美修复）

更新日志：
- 添加logging模块支持
- 改进错误处理和文件验证
- 支持外部配置文件（期刊和机构缩写）
- 完善机构识别���辑（School/College层级判断）
- 添加进度显示
"""

import csv
import re
import os
import json
import logging
import unicodedata
from datetime import datetime
from functools import lru_cache
from typing import Dict, List, Optional, Set

from ..utils.paths import resolve_project_path

# 配置日志
logger = logging.getLogger(__name__)


_ASCII_FOLD_SPECIAL_MAP = str.maketrans({
    'ı': 'i', 'İ': 'I', 'Ł': 'L', 'ł': 'l', 'Ø': 'O', 'ø': 'o',
    'Đ': 'D', 'đ': 'd', 'Æ': 'AE', 'æ': 'ae', 'Œ': 'OE', 'œ': 'oe',
    'ß': 'ss',
})


@lru_cache(maxsize=None)
def _ascii_fold_text(text: str) -> str:
    """去除重音等非 ASCII 差异（纯函数，带缓存：同一字符串在全流程中被重复折叠数百万次）。"""
    folded = text.translate(_ASCII_FOLD_SPECIAL_MAP)
    return unicodedata.normalize('NFKD', folded).encode('ascii', 'ignore').decode('ascii')


_SIMILARITY_STOPWORDS = {'of', 'the', 'and', 'for', 'at', 'in', 'de', 'di', 'da'}
_SIMILARITY_SYNONYMS = {
    'univ': 'university',
    'universidad': 'university',
    'universidade': 'university',
    'universitario': 'university',
    'universita': 'university',
    'med': 'medical',
    'medicine': 'medical',
    'hosp': 'hospital',
    'ctr': 'center',
    'centre': 'center',
    'inst': 'institute',
    'technol': 'technology',
    'natl': 'national',
    'acad': 'academy',
    'sch': 'school',
    'coll': 'college',
    'dept': 'department',
    'res': 'research',
    'intl': 'international',
    'co': 'company',
    'ltd': 'limited',
    'federal': 'fed',
    'pharm': 'pharmacy',
    'surg': 'surgery',
    'dermatol': 'dermatology',
    'biomed': 'biomedical',
    'innovat': 'innovation',
    'hlth': 'health',
    'sci': 'science',
    'sciences': 'science',
    'publ': 'public',
    'clin': 'clinic',
    'econ': 'economics',
}
# 注意：替换按插入顺序依次进行，长词组必须排在其前缀词组之前
_SIMILARITY_PHRASE_REPLACEMENTS = {
    'ut southwestern': 'university texas southwestern medical center university texas system',
    'univ texas southwestern': 'university texas southwestern medical center university texas system',
    'university texas southwestern': 'university texas southwestern medical center university texas system',
    'tokyo med univ hosp': 'tokyo medical university hospital tokyo medical university',
    'tokyo med univ': 'tokyo medical university',
    'toho univ': 'toho university',
    'kyorin univ': 'kyorin university',
    'seoul natl univ': 'seoul national university snu',
    'texas a&m': 'texasam',
    'texas a m': 'texasam',
    'texas a and m': 'texasam',
    'chinese academy medical sciences': 'chinese academy medical sciences cams',
    'chinese acad med sci': 'chinese academy medical sciences cams',
    'peking union medical college': 'peking union medical college pumc',
    'peking union med coll': 'peking union medical college pumc',
    'inst dermatol': 'institute dermatology cams',
    'hosp skin dis': 'hospital skin diseases institute dermatology cams',
    'chinese acad sci': 'chinese academy sciences cas',
    'shenzhen inst adv technol': 'shenzhen institute advanced technology cas',
    'ucl': 'university college london university london',
    'med univ south carolina': 'medical university south carolina',
    'cairo univ': 'cairo university egyptian knowledge bank ekb',
    'kasralainy fac med': 'kasralainy faculty medicine cairo university egyptian knowledge bank ekb',
    'fudan univ': 'fudan university',
    'jingan dist cent hosp': 'jingan district central hospital',
    'shiseido fs innovat ctr': 'shiseido fs innovation center shiseido company limited',
    'shiseido co ltd': 'shiseido company limited',
    'mirai technol inst': 'mirai technology institute shiseido company limited',
    'epi biotech co ltd': 'epi biotech company limited',
    'new hair plast surg clin': 'new hair plastic surgery clinic',
    'thammasat univ': 'thammasat university',
    'mahidol univ': 'mahidol university',
    'ramathibodi hosp': 'ramathibodi hospital mahidol university',
    'unesp': 'universidade estadual paulista',
    'univ hlth sci': 'university health sciences turkey',
    'publ hosp': 'public hospital',
}


@lru_cache(maxsize=None)
def _institution_similarity_token_tuple(text: str) -> tuple:
    """机构名分词（纯函数，带缓存：同一机构名在校准阶段被重复分词数百万次）。"""
    normalized = _ascii_fold_text(text).lower().replace('&', ' and ')
    for source, replacement in _SIMILARITY_PHRASE_REPLACEMENTS.items():
        normalized = normalized.replace(source, replacement)
    normalized = re.sub(r'[^a-z0-9\s]', ' ', normalized)
    tokens = []
    for token in normalized.split():
        token = _SIMILARITY_SYNONYMS.get(token, token)
        if token and token not in _SIMILARITY_STOPWORDS:
            tokens.append(token)
    return tuple(tokens)


@lru_cache(maxsize=None)
def _institution_similarity_token_set(text: str) -> frozenset:
    return frozenset(_institution_similarity_token_tuple(text))


@lru_cache(maxsize=None)
def _normalize_lookup_key_text(text: str) -> str:
    """查找键归一化（纯函数，带缓存）。"""
    folded = _ascii_fold_text(text).lower().replace('&', ' and ')
    folded = re.sub(r'[^a-z0-9\s]', ' ', folded)
    return re.sub(r'\s+', ' ', folded).strip()


_AFFILIATION_TOKEN_STOPWORDS = frozenset({
    'of', 'the', 'and', 'for', 'in', 'at', 'on', 'dept', 'department', 'univ', 'university', 'inst',
    'institute', 'school', 'faculty', 'division', 'center', 'centre', 'hospital', 'clinic', 'medical',
    'medicine', 'research', 'innovation', 'national', 'college', 'laboratory', 'lab', 'dermatology',
    'dermatol', 'pathology', 'pathol', 'surgery', 'surgical', 'internal', 'pediatrics', 'pediatric',
    'specialities', 'specialties', 'cutaneous', 'program', 'programme', 'service', 'section', 'unit',
    'united', 'states', 'peoples', 'china', 'japan', 'thailand', 'spain', 'canada', 'mexico', 'egypt',
    'iran', 'england', 'korea', 'south', 'north', 'r', 'province'
})


@lru_cache(maxsize=None)
def _tokenize_affiliation_text(text: str) -> frozenset:
    """机构地址分词（纯函数，带缓存）。"""
    normalized = _normalize_lookup_key_text(text)
    return frozenset(
        token for token in normalized.split()
        if len(token) > 1 and token not in _AFFILIATION_TOKEN_STOPWORDS
    )


class ScopusToWosConverter:
    """Scopus CSV到WOS纯文本格式转换器"""

    # 期刊名缩写映射表（常见期刊）
    JOURNAL_ABBREV = {
        "American Journal of Gastroenterology": "AM J GASTROENTEROL",
        "Modern Pathology": "MODERN PATHOL",
        "Nature Reviews Disease Primers": "NAT REV DIS PRIMERS",
        "Nature Reviews Gastroenterology and Hepatology": "NAT REV GASTRO HEPAT",
        "Alimentary Pharmacology and Therapeutics": "ALIMENT PHARM THER",
        "Clinical and Translational Gastroenterology": "CLIN TRANSL GASTROEN",
        "Digestive and Liver Disease": "DIGEST LIVER DIS",
        "Digestive Diseases and Sciences": "DIGEST DIS SCI",
        "Journal of Clinical Medicine": "J CLIN MED",
        "Clinical Gastroenterology and Hepatology": "CLIN GASTROENTEROL H",
        "Autoimmunity Reviews": "AUTOIMMUN REV",
        "Gut": "GUT",
        "Gastroenterology": "GASTROENTEROLOGY",
        "World Journal of Gastroenterology": "WORLD J GASTROENTERO",
        "Journal of Pediatric Gastroenterology and Nutrition": "J PEDIATR GASTR NUTR",
        "Scandinavian Journal of Gastroenterology": "SCAND J GASTROENTERO",
        "Frontiers in Immunology": "FRONT IMMUNOL",
        "Medicine": "MEDICINE",
        "Journal of Experimental Medicine": "J EXP MED",
        "American Journal of Surgical Pathology": "AM J SURG PATHOL",
        "Gastroenterology Research and Practice": "GASTROENT RES PRACT",
        "American Journal of Clinical Pathology": "AM J CLIN PATHOL",
        "Histopathology": "HISTOPATHOLOGY",
        "Pathology Research and Practice": "PATHOL RES PRACT",
        "Archives of Pathology and Laboratory Medicine": "ARCH PATHOL LAB MED",
        "Clinical Cancer Research": "CLIN CANCER RES",
        "Pathologica": "PATHOLOGICA",
        "Clinical Case Reports": "CLIN CASE REP",
        "Cellular and Molecular Gastroenterology and Hepatology": "CELL MOL GASTROENTER",
        "Virchows Archiv": "VIRCHOWS ARCH",
        "United European Gastroenterology Journal": "UNITED EUR GASTROENT",
        "Gastroenterology Research": "GASTROENTEROL RES",
        "Digestive Diseases": "DIGEST DIS",
        "Journal of Medical Genetics": "J MED GENET",
        "Annals of Clinical and Laboratory Science": "ANN CLIN LAB SCI",
        "Biomedicines": "BIOMEDICINES",
        "Nature": "NATURE",
        "International Journal of Cancer": "INT J CANCER",
        "Journal of Immunotherapy for Cancer": "J IMMUNOTHER CANCER",
        "Cancer Cell International": "CANCER CELL INT",
        "Best Practice and Research Clinical Endocrinology and Metabolism": "BEST PRACT RES CL EN",
        "Translational Research": "TRANSL RES",
        "European Journal of Internal Medicine": "EUR J INTERN MED",
        "Human Pathology": "HUM PATHOL",
        "International Journal of Epidemiology": "INT J EPIDEMIOL",
        "American Journal of Public Health": "AM J PUBLIC HEALTH",
        "Journal of the American Geriatrics Society": "J AM GERIATR SOC",
        "Endoscopy": "ENDOSCOPY",
        "Plos Medicine": "PLOS MED",
        "Lancet": "LANCET",
        "Clinical Research in Hepatology and Gastroenterology": "CLIN RES HEPATOL GAS",
        "Annals of Gastroenterology": "ANN GASTROENTEROL",
        "Trends in Molecular Medicine": "TRENDS MOL MED",
        "Gastroenterology Clinics of North America": "GASTROENTEROL CLIN N",
        "Nature Reviews Rheumatology": "NAT REV RHEUMATOL",
        "Journal of Clinical Pathology": "J CLIN PATHOL",
        "World Journal of Gastrointestinal Oncology": "WORLD J GASTRO ONCOL",
        "Annals of Oncology": "ANN ONCOL",
    }

    # 月份映射
    MONTH_ABBREV = {
        '1': 'JAN', '2': 'FEB', '3': 'MAR', '4': 'APR', '5': 'MAY', '6': 'JUN',
        '7': 'JUL', '8': 'AUG', '9': 'SEP', '10': 'OCT', '11': 'NOV', '12': 'DEC',
        'January': 'JAN', 'February': 'FEB', 'March': 'MAR', 'April': 'APR',
        'May': 'MAY', 'June': 'JUN', 'July': 'JUL', 'August': 'AUG',
        'September': 'SEP', 'October': 'OCT', 'November': 'NOV', 'December': 'DEC'
    }

    def __init__(self, csv_file: str, output_file: str, config_dir: str = "config", reference_wos_file: Optional[str] = None):
        """
        初始化转换器

        Args:
            csv_file: Scopus CSV文件路径
            output_file: 输出WOS文件路径
            config_dir: 配置文件目录（默认为config）

        Raises:
            FileNotFoundError: 输入文件不存在
            ValueError: 文件格式不正确
        """
        # 文件路径验证
        if not csv_file.endswith('.csv'):
            raise ValueError(f"输入文件必须是CSV格式，当前文件: {csv_file}")

        if not os.path.exists(csv_file):
            raise FileNotFoundError(f"输入文件不存在: {csv_file}")

        # 检查文件是否可读
        try:
            with open(csv_file, encoding='utf-8-sig') as f:
                f.read(1)
        except PermissionError as exc:
            raise PermissionError(f"无权限读取文件: {csv_file}") from exc
        except UnicodeDecodeError as exc:
            raise ValueError(f"文件编码错误，请确保文件为UTF-8格式: {csv_file}") from exc

        self.csv_file = csv_file
        self.output_file = output_file
        self.config_dir = str(resolve_project_path(config_dir))
        self.records = []
        self.reference_wos_file = reference_wos_file if reference_wos_file and os.path.exists(reference_wos_file) else None
        self.reference_journal_map: Dict[str, Dict[str, str]] = {}
        self.reference_author_map: Dict[str, Dict[str, str]] = {}
        self.reference_affiliation_map: Dict[str, str] = {}
        self.reference_author_affiliation_map: Dict[str, List[str]] = {}
        self.reference_reprint_map: Dict[str, List[str]] = {}
        self.reference_c3_map: Dict[str, str] = {}
        self.reference_c3_address_map: Dict[str, List[str]] = {}
        self.reference_c3_decision_map: Dict[str, Dict[str, int]] = {}
        self.reference_c3_alias_map: Dict[str, str] = {}
        self.reference_c3_raw_recovery_map: Dict[str, str] = {}
        self.reference_c3_companion_map: Dict[str, List[str]] = {}
        self.reference_c3_supplement_map: Dict[str, List[str]] = {}
        self.reference_c3_pool: List[str] = []

        # 加载配置文件
        self.journal_abbrev = self._load_journal_abbrev()
        self.institution_config = self._load_institution_config()

        # 加载作者数据库
        self.author_db = self._load_author_database()

        logger.info(f"初始化转换器 - 输入: {csv_file}, 输出: {output_file}")
        logger.info(f"已加载 {len(self.journal_abbrev)} 个期刊缩写")
        if self.author_db:
            logger.info(f"已加载作者数据库: {len(self.author_db.authors)} 位作者")

    def _load_author_database(self):
        """加载作者数据库"""
        try:
            from .author_database import AuthorDatabase
            db_path = os.path.join(self.config_dir, "author_database.json")
            if os.path.exists(db_path):
                db = AuthorDatabase(db_path)
                return db
            else:
                logger.info("作者数据库不存在，将使用默认转换逻辑")
                return None
        except Exception as e:
            logger.warning(f"加载作者数据库失败: {e}，将使用默认转换逻辑")
            return None

    def _load_journal_abbrev(self) -> Dict[str, str]:
        """加载期刊缩写配置"""
        config_file = os.path.join(self.config_dir, "journal_abbrev.json")

        # 默认缩写（备用）
        default_abbrev = self.JOURNAL_ABBREV.copy()

        if os.path.exists(config_file):
            try:
                with open(config_file, encoding='utf-8') as f:
                    custom_abbrev = json.load(f)
                    logger.info(f"从配置文件加载了 {len(custom_abbrev)} 个期刊缩写")
                    # 合并配置（自定义配置优先）
                    default_abbrev.update(custom_abbrev)
                    return default_abbrev
            except json.JSONDecodeError as e:
                logger.warning(f"期刊缩写配置文件格式错误: {e}，使用内置配置")
            except Exception as e:
                logger.warning(f"加载期刊缩写配置失败: {e}，使用内置配置")
        else:
            logger.info("未找到期刊缩写配置文件，使用内置配置")

        return default_abbrev

    def _load_institution_config(self) -> Dict:
        """加载机构配置"""
        config_file = os.path.join(self.config_dir, "institution_config.json")

        # 默认配置
        default_config = {
            "independent_colleges": [],
            "independent_schools": [],
            "abbreviations": {
                'Department': 'Dept',
                'University': 'Univ',
                'Università': 'Univ',
                'Fondazione': 'Fdn',
                'Institute': 'Inst',
                'Istituto': 'Inst',
                'Hospital': 'Hosp',
                'Ospedale': 'Hosp',
                'Center': 'Ctr',
                'Centre': 'Ctr',
                'Faculty': 'Fac',
                'Division': 'Div',
                'School': 'Sch',
                'Laboratory': 'Lab',
                'Research': 'Res',
                'Innovation': 'Innovat',
                'Systems': 'Syst',
                'Manufacturing': 'Mfg',
                'Biomedical': 'Biomed',
                'Translational': 'Translat',
                'Excellence': 'Excellence',
                'Science': 'Sci',
                'Sciences': 'Sci',
                'Technology': 'Technol',
                'Medicine': 'Med',
                'Medical': 'Med',
                'Chemical': 'Chem',
                'Chemistry': 'Chem',
                'Engineering': 'Engn',
                'Clinical': 'Clin',
                'Pharmacy': 'Pharm',
                'Memorial': 'Mem',
                'degli Studi di': '',
                'and': '&',
            }
        }

        if os.path.exists(config_file):
            try:
                with open(config_file, encoding='utf-8') as f:
                    custom_config = json.load(f)
                    logger.info("成功加载机构配置文件")
                    # 合并配置
                    if 'independent_colleges' in custom_config:
                        default_config['independent_colleges'] = custom_config['independent_colleges']
                    if 'independent_schools' in custom_config:
                        default_config['independent_schools'] = custom_config['independent_schools']
                    if 'abbreviations' in custom_config:
                        default_config['abbreviations'].update(custom_config['abbreviations'])
                    return default_config
            except Exception as e:
                logger.warning(f"加载机构配置失败: {e}，使用默认配置")
        else:
            logger.info("未找到机构配置文件，使用默认配置")

        return default_config

    def read_scopus_csv(self) -> List[Dict]:
        """
        读取Scopus CSV文件

        Returns:
            List[Dict]: 记录列表

        Raises:
            ValueError: CSV格式错误或缺少必要字段
        """
        records = []
        try:
            with open(self.csv_file, encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)

                # 验证必要字段
                required_fields = {'Authors', 'Title', 'Year'}
                if reader.fieldnames:
                    missing_fields = required_fields - set(reader.fieldnames)
                    if missing_fields:
                        logger.warning(f"CSV文件缺少推荐字段: {missing_fields}")

                for row in reader:
                    if any(row.values()):  # 跳过空行
                        records.append(row)

            logger.info(f"成功读取 {len(records)} 条记录")
            return records

        except FileNotFoundError:
            logger.error(f"文件不存在: {self.csv_file}")
            raise
        except UnicodeDecodeError as e:
            logger.error(f"文件编码错误: {e}")
            raise ValueError("文件编码错误，请确保文件为UTF-8格式") from e
        except csv.Error as e:
            logger.error(f"CSV格式错误: {e}")
            raise ValueError(f"CSV格式错误: {e}") from e
        except Exception as e:
            logger.error(f"读取文件时发生未知错误: {e}")
            raise

    def format_multiline_field(self, tag: str, content: str, max_width: int = None, separator: str = None) -> str:
        """
        格式化WOS字段

        Args:
            tag: 字段标签（如 TI, AB）
            content: 字段内容
            max_width: 每行最大宽度，如果为None则不换行（保持单行）
            separator: 分隔符（如';'用于C3字段），如果提供，则在此边界换行而不是空格边界

        Returns:
            格式化后的字段文本
        """
        if not content or content.strip() == '':
            return ''

        content = content.strip()

        # 如果不设置max_width，或者内容较短，直接返回单行
        if max_width is None or len(content) <= (max_width if max_width else float('inf')):
            return f"{tag} {content}"

        # 如果指定了separator（如C3的分号），则按separator分割而不是空格
        if separator:
            segments = [seg.strip() for seg in content.split(separator)]
            lines = []
            current_line = ""

            for i, segment in enumerate(segments):
                # 添加separator（除了最后一个）
                segment_with_sep = segment + (separator if i < len(segments) - 1 else '')
                test_line = current_line + (" " if current_line else "") + segment_with_sep

                if len(test_line) <= max_width:
                    current_line = test_line
                else:
                    if current_line:
                        lines.append(current_line)
                    current_line = segment_with_sep

            # 添加最后一行
            if current_line:
                lines.append(current_line)
        else:
            # 原有的按空格分割逻辑
            words = content.split()
            lines = []
            current_line = ""

            for word in words:
                test_line = current_line + (" " if current_line else "") + word
                if len(test_line) <= max_width:
                    current_line = test_line
                else:
                    if current_line:
                        lines.append(current_line)
                    current_line = word

            # 添加最后一行
            if current_line:
                lines.append(current_line)

        # 格式化输出：第一行不缩进，其余行3空格缩进
        if not lines:
            return ''

        result = f"{tag} {lines[0]}"
        for line in lines[1:]:
            result += f"\n   {line}"

        return result

    def convert_authors(self, authors_str: str) -> List[str]:
        """
        转换作者格式

        Scopus: "Miceli, E.; Lenti, M.V.; Di Sabatino, A."
        WOS: ["Miceli, E", "Lenti, MV", "Di Sabatino, A"]
        """
        if not authors_str:
            return []

        # 按分号分割
        authors = [a.strip() for a in authors_str.split(';')]

        # 处理缩写：移除点号和空格
        # "M.V." -> "MV", "M. V." -> "MV", "G.R." -> "GR"
        converted = []
        for author in authors:
            # 分割姓和名
            parts = author.split(',')
            if len(parts) >= 2:
                last_name = parts[0].strip()
                initials = parts[1].strip()
                # 移除所有点号和空格：M.V. -> MV, G. R. -> GR
                initials = initials.replace('.', '').replace(' ', '')
                converted.append(f"{last_name}, {initials}")
            else:
                converted.append(author)

        return converted

    def fix_compound_lastname(self, author_name: str) -> str:
        """
        修复复合姓氏问题

        问题：Scopus可能将复合姓氏错误记录
        错误: "Akar, Firas Abu" (Abu被放在名字后面)
        正确: "Abu Akar, Firas" (Abu是姓氏的一部分)

        常见姓氏粒子：
        - 阿拉伯语: Abu, Al, El, Ibn, bin
        - 荷兰语/德语: van, van der, van den, von, von der
        - 西班牙语/意大利语: de, del, della, di, da
        - 爱尔兰语: Mc, Mac, O'
        """
        if ',' not in author_name:
            return author_name

        # 姓氏粒子列表（需要大小写敏感匹配）
        name_particles = [
            'Abu', 'Al', 'El', 'Ibn', 'bin',  # 阿拉伯语
            'van', 'van der', 'van den', 'von', 'von der',  # 荷兰语/德语
            'de', 'del', 'della', 'di', 'da',  # 西班牙语/意大利语
            'Mc', 'Mac',  # 爱尔兰语
        ]

        parts = author_name.split(',', 1)
        lastname = parts[0].strip()
        firstname = parts[1].strip()

        # 检查名字部分末尾是否包含姓氏粒子
        firstname_parts = firstname.split()

        if len(firstname_parts) > 1:
            last_word = firstname_parts[-1]

            # 检查是否匹配任何姓氏粒子
            for particle in name_particles:
                if last_word == particle:
                    # 发现姓氏粒子，需要重组
                    new_lastname = last_word + ' ' + lastname
                    new_firstname = ' '.join(firstname_parts[:-1])

                    # 使用logging模块记录（如果logger存在）
                    if hasattr(self, 'logger'):
                        self.logger.debug(f"修复复合姓氏: '{author_name}' -> '{new_lastname}, {new_firstname}'")

                    return f"{new_lastname}, {new_firstname}"

        # 没有发现问题，返回原样
        return author_name

    def _clean_author_full_name(self, author: str) -> str:
        """清理 Scopus 提供的作者全名。"""
        if not author:
            return ''

        author_clean = re.sub(r'\s*\([^)]*\)', '', author).strip()

        degree_suffixes = [
            r',?\s*M\.?D\.?$', r',?\s*Ph\.?D\.?$', r',?\s*Dr\.?$',
            r',?\s*Prof\.?$', r',?\s*M\.?S\.?$', r',?\s*B\.?S\.?$'
        ]
        for suffix_pattern in degree_suffixes:
            author_clean = re.sub(suffix_pattern, '', author_clean, flags=re.IGNORECASE)

        author_clean = author_clean.rstrip('. ').strip()

        if ',' in author_clean:
            parts = author_clean.split(',', 1)
            if len(parts) == 2:
                lastname = parts[0].strip()
                firstname = parts[1].strip()
                author_clean = f"{lastname}, {firstname}"
                author_clean = self.fix_compound_lastname(author_clean)

        return author_clean

    def _parse_scopus_full_names(self, full_names_str: str) -> List[str]:
        """解析 Scopus 作者全名，并尽量保留原始信息密度。"""
        if not full_names_str:
            return []

        parsed_names = []
        for raw_author in full_names_str.split(';'):
            parsed_names.append(self._clean_author_full_name(raw_author.strip()))

        return parsed_names

    def _extract_given_name_tokens(self, author_name: str) -> List[str]:
        if not author_name or ',' not in author_name:
            return []

        given_name = author_name.split(',', 1)[1].strip()
        return [
            token
            for token in re.split(r'[\s\-\.]+', self._ascii_fold(given_name))
            if token and re.search(r'[A-Za-z]', token)
        ]

    def _has_explicit_given_name(self, author_name: str) -> bool:
        return any(len(token) > 1 for token in self._extract_given_name_tokens(author_name))

    def _normalize_surname(self, author_name: str) -> str:
        if not author_name:
            return ''

        surname = author_name.split(',', 1)[0].strip() if ',' in author_name else author_name.strip()
        surname = self._ascii_fold(surname)
        surname = re.sub(r'[^A-Za-z\s\-\']', ' ', surname)
        surname = re.sub(r'\s+', ' ', surname).strip().lower()
        return surname

    def _is_author_database_name_usable(self, original_name: str, candidate_name: str) -> bool:
        """作者库只用于补全，不允许把更明确的 Scopus 全名降级。"""
        if not candidate_name or candidate_name == original_name:
            return False

        if ',' not in candidate_name:
            return False

        original_surname = self._normalize_surname(original_name)
        candidate_surname = self._normalize_surname(candidate_name)
        if original_surname and candidate_surname and original_surname != candidate_surname:
            return False

        if self._has_explicit_given_name(original_name) and not self._has_explicit_given_name(candidate_name):
            return False

        original_given = ''.join(self._extract_given_name_tokens(original_name))
        candidate_given = ''.join(self._extract_given_name_tokens(candidate_name))
        if original_given and candidate_given and len(candidate_given) < len(original_given):
            return False

        return True

    def _lookup_reference_author(self, full_name: str = '', abbreviated_author: str = '') -> Dict[str, str]:
        """按多种键查找基于重复文献校准得到的 WOS 作者映射。"""
        for candidate in (full_name, abbreviated_author):
            if not candidate:
                continue
            mapped = self.reference_author_map.get(self._normalize_person_lookup_key(candidate), {})
            if mapped:
                return mapped
        return {}

    def _normalize_author_initials(self, initials: str) -> str:
        if not initials:
            return ''

        suffix_pattern = r'\b(jr|jnr|sr|ii|iii|iv)\b'
        initials = re.sub(suffix_pattern, ' ', self._ascii_fold(initials), flags=re.IGNORECASE)
        return re.sub(r'[^A-Za-z]', '', initials)

    def _get_author_initials(self, abbreviated_author: str) -> str:
        """提取缩写作者中的名字首字母。"""
        if ',' not in abbreviated_author:
            return ''
        initials = abbreviated_author.split(',', 1)[1]
        return self._normalize_author_initials(initials)

    def _should_use_author_database(self, abbreviated_author: str) -> bool:
        """仅在缩写信息相对不含糊时才使用作者数据库。"""
        return len(self._get_author_initials(abbreviated_author)) >= 2

    def _ascii_fold(self, text: str) -> str:
        """去除重音等非 ASCII 差异，使作者缩写更贴近 WOS。"""
        if not text:
            return ''
        return _ascii_fold_text(text)

    def _normalize_lookup_key(self, text: str) -> str:
        if not text:
            return ''
        return _normalize_lookup_key_text(text)

    def _normalize_person_lookup_key(self, text: str) -> str:
        if not text:
            return ''
        text = re.sub(r'\s*\([^)]*\)', '', text)
        text = self._ascii_fold(text).lower()
        text = re.sub(r'[^a-z0-9\s,\-\.]', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _coarsen_person_lookup_key(self, author_key: str) -> str:
        if not author_key or ',' not in author_key:
            return author_key
        lastname, initials = author_key.split(',', 1)
        initials = re.sub(r'[^a-z]', '', initials)
        if initials:
            return f"{lastname.strip()}, {initials[0]}"
        return lastname.strip()

    def _person_lookup_key_variants(self, text: str, include_coarse: bool = True) -> List[str]:
        author_key = self._normalize_person_lookup_key(text)
        if not author_key:
            return []

        variants: List[str] = []

        def add(candidate: str) -> None:
            candidate = candidate.strip()
            if candidate and candidate not in variants:
                variants.append(candidate)

        add(author_key)
        if include_coarse:
            add(self._coarsen_person_lookup_key(author_key))

        if ',' not in author_key:
            return variants

        lastname, given = author_key.split(',', 1)
        lastname = lastname.strip()
        given_tokens = [token for token in re.split(r'[^a-z]+', given) if token]
        if given_tokens:
            add(f"{lastname}, {given_tokens[0]}")
            if include_coarse:
                joined_initials = ''.join(token[0] for token in given_tokens if token)
                if joined_initials:
                    add(f"{lastname}, {joined_initials}")
                    add(f"{lastname}, {joined_initials[0]}")

        return variants

    def _compose_author_affiliation_key(self, author_key: str, affiliation_key: str) -> str:
        return f"{author_key}||{affiliation_key}"

    def _split_affiliation_candidates(self, affiliations_str: str) -> List[str]:
        return [item.strip() for item in affiliations_str.split(';') if item.strip()]

    def _normalize_affiliation_parts(self, text: str) -> List[str]:
        normalized_parts = []
        for part in text.split(','):
            normalized = self._normalize_lookup_key(part)
            if normalized:
                normalized_parts.append(normalized)
        return normalized_parts

    def _split_affiliations_by_country(self, remaining_parts: List[str]) -> List[str]:
        countries = {
            self._normalize_lookup_key(country)
            for country in [
                'USA', 'United States', 'United Kingdom', 'England', 'Scotland', 'Wales',
                'China', 'Peoples R China', 'Japan', 'Germany', 'France', 'Italy', 'Spain',
                'Canada', 'Australia', 'India', 'South Korea', 'Brazil', 'Russia',
                'Netherlands', 'Switzerland', 'Sweden', 'Belgium', 'Austria', 'Poland',
                'Israel', 'Palestine', 'Argentina', 'Mexico', 'Turkey', 'Turkiye',
                'South Africa', 'Singapore', 'Taiwan', 'Hong Kong', 'Ireland', 'Denmark',
                'Norway', 'Finland', 'Greece', 'Portugal', 'Czech Republic', 'Hungary',
                'Romania', 'Chile', 'Colombia', 'Peru', 'Iran', 'Iraq', 'Egypt', 'Thailand'
            ]
        }

        institutions: List[str] = []
        current_parts: List[str] = []
        for part in remaining_parts:
            cleaned_part = part.strip()
            if not cleaned_part:
                continue

            current_parts.append(cleaned_part)
            normalized_part = self._normalize_lookup_key(cleaned_part.rstrip('.'))
            if normalized_part in countries and len(current_parts) >= 2:
                candidate = ', '.join(current_parts).strip(' .,;')
                if candidate and self._normalize_lookup_key(candidate) not in countries:
                    institutions.append(candidate)
                current_parts = []

        trailing = ', '.join(current_parts).strip(' .,;')
        if trailing and self._normalize_lookup_key(trailing) not in countries:
            institutions.append(trailing)

        return institutions or [', '.join(remaining_parts).strip(' .,;')]

    def _segment_affiliations_from_parts(self, remaining_parts: List[str], affiliation_candidates: List[str]) -> List[str]:
        normalized_remaining = []
        for part in remaining_parts:
            normalized = self._normalize_lookup_key(part)
            if normalized:
                normalized_remaining.append(normalized)

        candidate_entries = []
        for candidate in affiliation_candidates:
            normalized_candidate = self._normalize_affiliation_parts(candidate)
            if normalized_candidate:
                candidate_entries.append((candidate, normalized_candidate))

        cursor = 0
        matched_affiliations: List[str] = []
        while cursor < len(normalized_remaining):
            best_match = ''
            best_length = 0
            for candidate_text, candidate_parts in candidate_entries:
                length = len(candidate_parts)
                if length <= best_length:
                    continue
                if normalized_remaining[cursor:cursor + length] == candidate_parts:
                    best_match = candidate_text
                    best_length = length

            if best_match:
                matched_affiliations.append(best_match)
                cursor += best_length
                continue
            break

        if matched_affiliations and cursor == len(normalized_remaining):
            return matched_affiliations

        return self._split_affiliations_by_country(remaining_parts)

    def _extract_author_affiliation_groups(
        self,
        affil_str: str,
        author_names: Optional[List[str]] = None,
        affiliation_candidates: Optional[List[str]] = None,
    ) -> List[tuple[str, List[str]]]:
        if not affil_str:
            return []

        author_blocks = [block.strip() for block in affil_str.split(';') if block.strip()]
        groups: List[tuple[str, List[str]]] = []
        for block_index, block in enumerate(author_blocks):
            parts = [part.strip() for part in block.split(',') if part.strip()]
            if len(parts) < 3:
                continue

            author_full = self.fix_compound_lastname(f"{parts[0]}, {parts[1]}")
            if author_names and block_index < len(author_names) and author_names[block_index]:
                author_full = author_names[block_index]

            remaining_parts = parts[2:]
            institutions = self._segment_affiliations_from_parts(remaining_parts, affiliation_candidates or [])
            cleaned_institutions = [institution for institution in institutions if institution.strip(' .,;')]
            groups.append((author_full, cleaned_institutions))

        return groups

    def _parse_reference_c1_entries(self, reference_record: Dict) -> List[Dict[str, object]]:
        entries: List[Dict[str, object]] = []
        default_authors = [name.strip() for name in reference_record.get('AF', '').split('\n') if name.strip()]
        single_author_default = default_authors[:1] if len(default_authors) == 1 else []

        for line in reference_record.get('C1', '').split('\n'):
            line = line.strip()
            if not line:
                continue

            authors = []
            address = line.rstrip('.')
            if line.startswith('[') and '] ' in line:
                author_segment, address = line.split('] ', 1)
                authors = [author.strip() for author in author_segment.lstrip('[').split(';') if author.strip()]
            else:
                authors = single_author_default[:]

            entries.append({
                'authors': authors,
                'author_keys': {self._normalize_person_lookup_key(author) for author in authors if author},
                'address': address.rstrip('.'),
            })

        return entries

    def _is_detailed_affiliation_address(self, address: str) -> bool:
        if not address:
            return False

        folded = self._ascii_fold(address).lower()
        if re.search(r'\b\d{4,7}(?:-\d{4})?\b', address):
            return True
        return bool(re.search(r'\b(road|rd|street|st|avenue|ave|boulevard|blvd|lane|ln|drive|dr|suite|bldg|ku|cho|km)\b', folded))

    def _prune_correspondence_like_addresses(self, addresses: List[str]) -> List[str]:
        if len(addresses) <= 1:
            return addresses

        pruned = []
        for address in addresses:
            if self._is_detailed_affiliation_address(address):
                has_shorter_peer = any(
                    other != address and not self._is_detailed_affiliation_address(other)
                    and self._institution_similarity(address, other) >= 0.7
                    for other in addresses
                )
                if has_shorter_peer:
                    continue
            pruned.append(address)

        return pruned or addresses

    def _select_contextual_affiliation_matches(
        self,
        raw_affiliation: str,
        candidate_addresses: List[str],
        shared_author_count: int = 1,
        author_repeat_count: int = 1,
    ) -> List[str]:
        if len(candidate_addresses) <= 1:
            return candidate_addresses

        scored_addresses = []
        best_score = 0.0
        for candidate_address in candidate_addresses:
            score = self._institution_similarity(raw_affiliation, candidate_address)
            scored_addresses.append((score, candidate_address))
            if score > best_score:
                best_score = score

        filtered = [
            candidate_address
            for score, candidate_address in scored_addresses
            if score >= max(0.28, best_score - 0.25)
        ]
        filtered = filtered or list(candidate_addresses)

        if author_repeat_count > 1:
            repeated_candidates = [
                candidate_address
                for score, candidate_address in scored_addresses
                if score >= max(0.18, best_score - 0.35)
            ]
            if repeated_candidates:
                filtered = repeated_candidates

        if shared_author_count > 1:
            narrowed = [
                address
                for address in filtered
                if not (
                    self._is_detailed_affiliation_address(address)
                    and any(
                        other != address
                        and not self._is_detailed_affiliation_address(other)
                        and self._institution_similarity(address, other) >= 0.55
                        for other in filtered
                    )
                )
            ]
            filtered = narrowed or filtered
        else:
            detailed_peers = [
                address
                for address in filtered
                if self._is_detailed_affiliation_address(address)
                and any(
                    other != address
                    and not self._is_detailed_affiliation_address(other)
                    and self._institution_similarity(address, other) >= 0.55
                    for other in filtered
                )
            ]
            if detailed_peers:
                filtered = [
                    address
                    for address in filtered
                    if self._is_detailed_affiliation_address(address)
                    or not any(
                        self._institution_similarity(address, detailed_address) >= 0.55
                        for detailed_address in detailed_peers
                    )
                ]

        deduped = []
        for address in filtered:
            if address not in deduped:
                deduped.append(address)

        if author_repeat_count > 1 and len(deduped) > author_repeat_count:
            ranked_scores = {address: score for score, address in scored_addresses}
            top_addresses = sorted(
                deduped,
                key=lambda address: (ranked_scores.get(address, 0.0), -candidate_addresses.index(address)),
                reverse=True,
            )[:author_repeat_count]
            deduped = [address for address in candidate_addresses if address in top_addresses]
        return deduped

    def _match_reference_author_affiliations(self, raw_affiliation: str, candidate_addresses: List[str]) -> List[str]:
        if not raw_affiliation or not candidate_addresses:
            return []

        raw_tokens = self._tokenize_affiliation(raw_affiliation)
        raw_similarity_tokens = set(self._institution_similarity_tokens(raw_affiliation))
        if not raw_tokens and not raw_similarity_tokens:
            return []

        scored_matches = []
        best_score = 0.0
        for candidate_address in candidate_addresses:
            candidate_tokens = self._tokenize_affiliation(candidate_address)
            candidate_similarity_tokens = set(self._institution_similarity_tokens(candidate_address))

            score = self._institution_similarity(raw_affiliation, candidate_address)

            if raw_tokens and candidate_tokens:
                overlap = len(raw_tokens & candidate_tokens)
                if overlap:
                    score = max(
                        score,
                        overlap / max(len(raw_tokens), 1),
                        (2 * overlap) / (len(raw_tokens) + len(candidate_tokens)),
                    )

            if raw_similarity_tokens and candidate_similarity_tokens:
                overlap = len(raw_similarity_tokens & candidate_similarity_tokens)
                if overlap:
                    score = max(
                        score,
                        (2 * overlap) / (len(raw_similarity_tokens) + len(candidate_similarity_tokens)),
                    )
                    score += 0.03 * min(overlap, 2)

            if score > best_score:
                best_score = score
            if score >= 0.28:
                scored_matches.append((score, candidate_address))

        if not scored_matches or best_score < 0.38:
            return []

        matches = []
        threshold = max(0.38, best_score - 0.08)
        for score, candidate_address in scored_matches:
            if score >= threshold and candidate_address not in matches:
                matches.append(candidate_address)
        return matches

    def _lookup_reference_author_affiliations(self, author_full: str, raw_affiliation: str) -> List[str]:
        if not author_full or not raw_affiliation or not self.reference_author_affiliation_map:
            return []

        affiliation_key = self._normalize_lookup_key(raw_affiliation)
        if not affiliation_key:
            return []

        matches = []
        for author_key in self._person_lookup_key_variants(author_full, include_coarse=False):
            composite_key = self._compose_author_affiliation_key(author_key, affiliation_key)
            for candidate_address in self.reference_author_affiliation_map.get(composite_key, []):
                if candidate_address not in matches:
                    matches.append(candidate_address)

        return self._prune_correspondence_like_addresses(matches)

    def _lookup_reference_reprint_addresses(self, author: str, raw_address: str) -> List[str]:
        if not author or not raw_address or not self.reference_reprint_map:
            return []

        address_key = self._normalize_lookup_key(raw_address)
        if not address_key:
            return []

        matches: List[str] = []
        exact_author_keys = self._person_lookup_key_variants(author, include_coarse=False)
        for author_key in exact_author_keys:
            composite_key = self._compose_author_affiliation_key(author_key, address_key)
            for candidate_address in self.reference_reprint_map.get(composite_key, []):
                if candidate_address not in matches:
                    matches.append(candidate_address)

        if matches:
            return matches

        author_keys = self._person_lookup_key_variants(author)
        coarse_author_keys = {self._coarsen_person_lookup_key(author_key) for author_key in author_keys if author_key}

        for author_key in author_keys:
            if author_key in exact_author_keys:
                continue
            composite_key = self._compose_author_affiliation_key(author_key, address_key)
            for candidate_address in self.reference_reprint_map.get(composite_key, []):
                if candidate_address not in matches:
                    matches.append(candidate_address)

        if matches:
            return matches

        for candidate_key, candidate_addresses in self.reference_reprint_map.items():
            candidate_author_key, candidate_address_key = candidate_key.split('||', 1)
            if candidate_address_key != address_key:
                continue
            if (
                candidate_author_key in coarse_author_keys
                or self._coarsen_person_lookup_key(candidate_author_key) in coarse_author_keys
            ):
                for candidate_address in candidate_addresses:
                    if candidate_address not in matches:
                        matches.append(candidate_address)

        return matches

    def _lookup_reference_reprint_address(self, author: str, raw_address: str) -> str:
        matches = self._lookup_reference_reprint_addresses(author, raw_address)
        return matches[0] if matches else ''

    def _parse_c1_entries_from_lines(self, c1_lines: List[str], full_names: Optional[List[str]] = None) -> List[Dict[str, object]]:
        if not c1_lines:
            return []

        temp_record = {
            'AF': '\n'.join(full_names or []),
            'C1': '\n'.join(c1_lines),
        }
        return self._parse_reference_c1_entries(temp_record)

    def _score_c1_entry_match(self, left_entry: Dict[str, object], right_entry: Dict[str, object]) -> float:
        left_authors = left_entry.get('author_keys', set())
        right_authors = right_entry.get('author_keys', set())
        author_overlap = len(left_authors & right_authors)
        address_score = self._institution_similarity(
            str(left_entry.get('address', '')),
            str(right_entry.get('address', '')),
        )
        score = address_score
        if author_overlap:
            score += 0.25 + 0.1 * min(author_overlap, 2)
        return score

    def _align_c1_entries(self, generated_entries: List[Dict[str, object]], reference_entries: List[Dict[str, object]]) -> List[tuple[Dict[str, object], Dict[str, object]]]:
        if not generated_entries or not reference_entries:
            return []

        remaining = set(range(len(reference_entries)))
        matches = []
        for generated_entry in generated_entries:
            best_index = None
            best_score = 0.0
            for reference_index in remaining:
                score = self._score_c1_entry_match(generated_entry, reference_entries[reference_index])
                if score > best_score:
                    best_score = score
                    best_index = reference_index

            if best_index is None:
                continue

            if best_score < 0.45:
                continue

            remaining.discard(best_index)
            matches.append((generated_entry, reference_entries[best_index]))

        return matches

    def _parse_reference_rp_blocks(self, reference_record: Dict) -> List[Dict[str, object]]:
        rp_text = reference_record.get('RP', '').strip()
        if not rp_text:
            return []

        blocks = []
        for raw_block in re.split(r'\.\s*;\s*', rp_text.rstrip('.')):
            raw_block = raw_block.strip().rstrip('.')
            if not raw_block:
                continue

            authors = []
            address = raw_block
            if '(corresponding author)' in raw_block:
                author_part, address = raw_block.split('(corresponding author)', 1)
                author_part = author_part.rstrip(' ,;')
                authors = [author.strip() for author in author_part.split(';') if author.strip()]
                address = address.lstrip(' ,').rstrip('.')

            blocks.append({
                'authors': authors,
                'author_keys': {self._normalize_person_lookup_key(author) for author in authors if author},
                'address': address,
            })

        return blocks

    def _extract_email_org_tokens(self, emails: List[str]) -> Set[str]:
        generic_domains = {
            'gmail', 'yahoo', 'hotmail', 'outlook', 'foxmail', 'icloud', 'live', 'msn',
            '163', '126', 'qq', 'sina', 'yeah', 'mail', 'protonmail'
        }
        suffix_tokens = {
            'edu', 'ac', 'org', 'com', 'net', 'gov', 'cn', 'jp', 'kr', 'uk', 'au', 'th',
            'br', 'mx', 'es', 'it', 'fr', 'de', 'us', 'ca'
        }

        tokens: Set[str] = set()
        for email in emails:
            if '@' not in email:
                continue
            domain = email.split('@', 1)[1].lower()
            for token in re.split(r'[\.-]', domain):
                token = token.strip()
                if len(token) <= 2 or token in generic_domains or token in suffix_tokens:
                    continue
                tokens.add(token)
        return tokens

    def _lookup_reference_c3_names_for_address(self, address: str) -> Optional[List[str]]:
        if not address or not self.reference_c3_address_map:
            return None

        address_key = self._normalize_lookup_key(address)
        if address_key in self.reference_c3_address_map:
            return list(self.reference_c3_address_map[address_key])

        address_tokens = self._tokenize_affiliation(address)
        seed_tokens = self._tokenize_affiliation(self._select_primary_c3_name(address))
        best_score = 0.0
        best_names: Optional[List[str]] = None
        for candidate_key, candidate_names in self.reference_c3_address_map.items():
            score = self._institution_similarity(address, candidate_key)

            candidate_tokens = self._tokenize_affiliation(candidate_key)
            if address_tokens and candidate_tokens:
                overlap = len(address_tokens & candidate_tokens)
                if overlap:
                    score += 0.14 * (overlap / max(len(candidate_tokens), 1))

            if seed_tokens and candidate_tokens:
                seed_overlap = len(seed_tokens & candidate_tokens)
                if seed_overlap:
                    score += 0.12 * (seed_overlap / max(len(candidate_tokens), 1))

            if score > best_score:
                best_score = score
                best_names = list(candidate_names)

        if best_score >= 0.76:
            return best_names
        return None

    def _normalize_reference_c3_name(self, name: str) -> str:
        return re.sub(r'\s+', ' ', name or '').strip(' ;.')

    def _normalize_reference_c3_names(self, names: List[str]) -> List[str]:
        normalized_names = []
        seen = set()
        for name in names:
            normalized_name = self._normalize_reference_c3_name(name)
            if not normalized_name:
                continue
            lookup_key = self._normalize_lookup_key(normalized_name)
            if lookup_key and lookup_key not in seen:
                seen.add(lookup_key)
                normalized_names.append(normalized_name)
        return normalized_names

    def _build_reference_calibration(self, scopus_records: List[Dict]) -> None:
        if not self.reference_wos_file:
            return

        try:
            from ..pipeline.merge import RecordMatcher, WOSRecordParser
        except Exception as exc:
            logger.warning(f"无法加载参考WOS校准模块: {exc}")
            return

        try:
            wos_records = WOSRecordParser.parse_wos_file(self.reference_wos_file)
        except Exception as exc:
            logger.warning(f"参考WOS文件解析失败: {exc}")
            return

        if not wos_records:
            return

        matcher = RecordMatcher()
        wos_by_doi = {}
        wos_by_signature = {}

        for record in wos_records:
            doi = record.get('DI', '').strip().lower()
            if doi and doi not in wos_by_doi:
                wos_by_doi[doi] = record

            title_key = matcher.normalize_title(record.get('TI', ''))
            year = record.get('PY', '').strip()
            first_author = self._normalize_lookup_key(record.get('AU', '').split('\n')[0])
            if title_key and year and first_author:
                signature = (title_key, year, first_author)
                wos_by_signature.setdefault(signature, record)

        reference_journal_map: Dict[str, Dict[str, str]] = {}
        reference_author_map: Dict[str, Dict[str, str]] = {}
        reference_affiliation_map: Dict[str, str] = {}
        reference_author_affiliation_map: Dict[str, List[str]] = {}
        reference_reprint_map: Dict[str, List[str]] = {}
        matched_reference_records = []
        matched_pairs = 0

        for scopus_record in scopus_records:
            reference_record = None
            doi = scopus_record.get('DOI', '').strip().lower()
            if doi:
                reference_record = wos_by_doi.get(doi)

            if reference_record is None:
                title_key = matcher.normalize_title(scopus_record.get('Title', ''))
                year = scopus_record.get('Year', '').strip()
                fallback_authors = self.convert_authors(scopus_record.get('Authors', ''))
                first_author = self._normalize_lookup_key(fallback_authors[0]) if fallback_authors else ''
                if title_key and year and first_author:
                    reference_record = wos_by_signature.get((title_key, year, first_author))

            if reference_record is None:
                continue

            matched_pairs += 1
            matched_reference_records.append((scopus_record, reference_record))
            source_title = scopus_record.get('Source title', '').strip()
            if source_title:
                journal_key = self._normalize_lookup_key(source_title)
                reference_journal_map[journal_key] = {
                    field: reference_record.get(field, '').strip()
                    for field in ('SO', 'J9', 'JI', 'SN', 'EI')
                    if reference_record.get(field, '').strip()
                }

            fallback_authors = self.convert_authors(scopus_record.get('Authors', ''))
            full_names = self._parse_scopus_full_names(scopus_record.get('Author full names', ''))
            reference_af = [name.strip() for name in reference_record.get('AF', '').split('\n') if name.strip()]
            reference_au = [name.strip() for name in reference_record.get('AU', '').split('\n') if name.strip()]

            formatted_abbreviated_authors = []
            total_reference_authors = max(len(full_names), len(fallback_authors))
            for index in range(total_reference_authors):
                mapped = {}
                if index < len(reference_af):
                    mapped['AF'] = reference_af[index]
                if index < len(reference_au):
                    mapped['AU'] = reference_au[index]
                if not mapped:
                    continue

                full_name = full_names[index] if index < len(full_names) else ''
                fallback_abbrev = fallback_authors[index] if index < len(fallback_authors) else ''
                reference_abbrev = reference_au[index] if index < len(reference_au) else ''
                formatted_abbreviated_authors.append(reference_abbrev or self._format_author_abbreviation(full_name, fallback_abbrev))

                variants = []
                if full_name:
                    variants.append(full_name)
                if fallback_abbrev:
                    variants.append(fallback_abbrev)

                for variant in variants:
                    author_key = self._normalize_person_lookup_key(variant)
                    if author_key and author_key not in reference_author_map:
                        reference_author_map[author_key] = mapped

            scopus_affiliations = self._split_affiliation_candidates(scopus_record.get('Affiliations', ''))
            wos_entries = self._parse_reference_c1_entries(reference_record)
            wos_addresses = [str(entry.get('address', '')).rstrip('.') for entry in wos_entries if entry.get('address')]

            for scopus_affiliation, wos_address in self._align_reference_affiliations(scopus_affiliations, wos_addresses):
                affiliation_key = self._normalize_lookup_key(scopus_affiliation)
                if affiliation_key and affiliation_key not in reference_affiliation_map:
                    reference_affiliation_map[affiliation_key] = wos_address

            author_affiliation_groups = self._extract_author_affiliation_groups(
                scopus_record.get('Authors with affiliations', ''),
                author_names=full_names,
                affiliation_candidates=scopus_affiliations,
            )
            for author_full, raw_affiliations in author_affiliation_groups:
                author_variants = set(self._person_lookup_key_variants(author_full, include_coarse=False))
                if not author_variants:
                    continue

                candidate_addresses = [
                    str(entry.get('address', '')).rstrip('.')
                    for entry in wos_entries
                    if author_variants & entry.get('author_keys', set()) and entry.get('address')
                ]
                candidate_addresses = self._prune_correspondence_like_addresses(candidate_addresses)
                if not candidate_addresses:
                    continue

                for raw_affiliation in raw_affiliations:
                    affiliation_key = self._normalize_lookup_key(raw_affiliation)
                    if not affiliation_key:
                        continue

                    matched_addresses = self._match_reference_author_affiliations(raw_affiliation, candidate_addresses)
                    if not matched_addresses:
                        continue

                    for author_variant in author_variants:
                        composite_key = self._compose_author_affiliation_key(author_variant, affiliation_key)
                        reference_author_affiliation_map.setdefault(composite_key, [])
                        for matched_address in matched_addresses:
                            if matched_address not in reference_author_affiliation_map[composite_key]:
                                reference_author_affiliation_map[composite_key].append(matched_address)

            raw_correspondence_blocks = self._build_correspondence_blocks(
                scopus_record.get('Correspondence Address', ''),
                formatted_abbreviated_authors or fallback_authors,
            )
            reference_rp_blocks = self._parse_reference_rp_blocks(reference_record)
            for block in raw_correspondence_blocks:
                author = str(block.get('author', '')).strip()
                raw_address = str(block.get('raw_address', '')).strip()
                if not author or not raw_address:
                    continue

                author_variants = set(self._person_lookup_key_variants(author))
                if not author_variants:
                    continue

                candidate_rp_blocks = [
                    rp_block
                    for rp_block in reference_rp_blocks
                    if author_variants & rp_block.get('author_keys', set())
                ]
                if not candidate_rp_blocks and len(reference_rp_blocks) == 1:
                    candidate_rp_blocks = reference_rp_blocks
                if not candidate_rp_blocks:
                    continue

                if len(candidate_rp_blocks) <= 4:
                    selected_blocks = list(candidate_rp_blocks)
                else:
                    scored_blocks = [
                        (
                            self._institution_similarity(raw_address, str(rp_block.get('address', ''))),
                            rp_block,
                        )
                        for rp_block in candidate_rp_blocks
                    ]
                    best_score = max(score for score, _ in scored_blocks)
                    threshold = max(0.30, best_score - 0.08)
                    selected_blocks = [rp_block for score, rp_block in scored_blocks if score >= threshold]
                    if not selected_blocks and scored_blocks:
                        selected_blocks = [max(scored_blocks, key=lambda item: item[0])[1]]

                address_key = self._normalize_lookup_key(raw_address)
                if not address_key:
                    continue

                for author_variant in author_variants:
                    composite_key = self._compose_author_affiliation_key(author_variant, address_key)
                    reference_reprint_map.setdefault(composite_key, [])
                    for selected_block in selected_blocks:
                        mapped_address = str(selected_block.get('address', '')).rstrip('.')
                        if mapped_address and mapped_address not in reference_reprint_map[composite_key]:
                            reference_reprint_map[composite_key].append(mapped_address)

        self.reference_journal_map = reference_journal_map
        self.reference_author_map = reference_author_map
        self.reference_affiliation_map = reference_affiliation_map
        self.reference_author_affiliation_map = reference_author_affiliation_map
        self.reference_reprint_map = reference_reprint_map
        self.reference_c3_map = self._build_reference_c3_calibration(matched_reference_records)
        self.reference_c3_address_map = self._build_reference_c3_address_calibration(matched_reference_records)
        self.reference_c3_pool = self._normalize_reference_c3_names([
            name
            for record in wos_records
            for name in record.get('C3', '').split(';')
        ])
        self.reference_c3_decision_map = self._build_reference_c3_decision_map(matched_reference_records)
        self.reference_c3_alias_map = self._build_reference_c3_alias_map(matched_reference_records)
        self.reference_c3_raw_recovery_map = self._build_reference_c3_raw_recovery_map(matched_reference_records)
        self.reference_c3_companion_map = self._build_reference_c3_companion_map(matched_reference_records)
        self.reference_c3_supplement_map = self._build_reference_c3_supplement_map(wos_records)

        if matched_pairs:
            logger.info(
                f"参考WOS通用校准已建立: 重复对 {matched_pairs} 组, 期刊映射 {len(reference_journal_map)} 条, 作者映射 {len(reference_author_map)} 条, 机构映射 {len(reference_affiliation_map)} 条, 作者-机构映射 {len(reference_author_affiliation_map)} 条, RP映射 {len(reference_reprint_map)} 条, C3映射 {len(self.reference_c3_map)} 条, C3行映射 {len(self.reference_c3_address_map)} 条, C3直恢复 {len(self.reference_c3_raw_recovery_map)} 条, C3伴随恢复 {len(self.reference_c3_companion_map)} 条"
            )

    def _institution_similarity_tokens(self, text: str) -> List[str]:
        if not text:
            return []
        return list(_institution_similarity_token_tuple(text))

    def _institution_similarity(self, left: str, right: str) -> float:
        left_tokens = _institution_similarity_token_set(left) if left else frozenset()
        right_tokens = _institution_similarity_token_set(right) if right else frozenset()

        if not left_tokens or not right_tokens:
            return 0.0

        overlap = len(left_tokens & right_tokens)
        if not overlap:
            return 0.0

        return (2 * overlap) / (len(left_tokens) + len(right_tokens))

    def _match_reference_c3_name(self, generated_name: str, reference_names: List[str]) -> str:
        if not generated_name or not reference_names:
            return ''

        best_name = ''
        best_score = 0.0
        for reference_name in reference_names:
            score = self._institution_similarity(generated_name, reference_name)
            if score > best_score:
                best_score = score
                best_name = reference_name

        return best_name if best_score >= 0.6 else ''

    def _build_reference_c3_calibration(self, matched_reference_records: List[tuple[Dict, Dict]]) -> Dict[str, str]:
        candidate_counts: Dict[str, Dict[str, int]] = {}

        for scopus_record, reference_record in matched_reference_records:
            fallback_authors = self.convert_authors(scopus_record.get('Authors', ''))
            full_names = self.convert_author_full_names(
                scopus_record.get('Author full names', ''),
                fallback_authors,
            )
            affils = self.parse_affiliations(
                scopus_record.get('Authors with affiliations', ''),
                author_names=full_names,
                affiliation_candidates=self._split_affiliation_candidates(scopus_record.get('Affiliations', '')),
            )
            generated_primary_names = self.extract_primary_institutions_from_c1(affils)
            reference_primary_names = self._normalize_reference_c3_names(
                reference_record.get('C3', '').split(';')
            )

            for generated_name in generated_primary_names:
                generated_key = self._normalize_lookup_key(generated_name)
                if not generated_key:
                    continue

                matched_name = self._match_reference_c3_name(generated_name, reference_primary_names)
                if not matched_name:
                    continue

                candidate_counts.setdefault(generated_key, {})
                candidate_counts[generated_key][matched_name] = candidate_counts[generated_key].get(matched_name, 0) + 1

        reference_c3_map: Dict[str, str] = {}
        for generated_key, counts in candidate_counts.items():
            reference_c3_map[generated_key] = max(
                counts.items(),
                key=lambda item: (item[1], len(item[0])),
            )[0]

        return reference_c3_map

    def _match_reference_c3_names_for_address(self, address: str, reference_names: List[str]) -> List[str]:
        address_folded = self._ascii_fold(address).lower()
        address_token_string = ' '.join(self._institution_similarity_tokens(address))
        address_lookup_tokens = self._tokenize_affiliation(address)
        seed_name = self._select_primary_c3_name(address)
        seed_tokens = self._tokenize_affiliation(seed_name)
        scored_matches = []
        for reference_name in reference_names:
            score = self._institution_similarity(address, reference_name)
            reference_folded = self._ascii_fold(reference_name).lower()
            reference_token_string = ' '.join(self._institution_similarity_tokens(reference_name))
            reference_lookup_tokens = self._tokenize_affiliation(reference_name)

            if reference_token_string and reference_token_string in address_token_string:
                score += 0.18

            if address_lookup_tokens and reference_lookup_tokens:
                org_overlap = len(address_lookup_tokens & reference_lookup_tokens)
                if org_overlap:
                    score += 0.18 * (org_overlap / max(len(reference_lookup_tokens), 1))
                if seed_tokens:
                    seed_overlap = len(seed_tokens & reference_lookup_tokens)
                    if seed_overlap:
                        score += 0.22 * (seed_overlap / max(len(reference_lookup_tokens), 1))
                    else:
                        score -= 0.18

            if 'institute' in address_folded and 'institute' in reference_folded:
                score += 0.05
            if 'college' in address_folded and 'college' in reference_folded:
                score += 0.04
            if 'academy' in address_folded and 'academy' in reference_folded:
                score += 0.04

            if score >= 0.22:
                scored_matches.append((score, reference_name))

        if not scored_matches:
            return []

        best_score = max(score for score, _ in scored_matches)
        if best_score < 0.30:
            return []

        selected_names = {
            reference_name
            for score, reference_name in scored_matches
            if score >= max(0.24, best_score - 0.18)
        }
        ordered_names = [name for name in reference_names if name in selected_names]
        return self._normalize_reference_c3_names(ordered_names)

    def _build_reference_c3_address_calibration(self, matched_reference_records: List[tuple[Dict, Dict]]) -> Dict[str, List[str]]:
        candidate_counts: Dict[str, Dict[tuple[str, ...], int]] = {}

        for scopus_record, reference_record in matched_reference_records:
            fallback_authors = self.convert_authors(scopus_record.get('Authors', ''))
            full_names = self.convert_author_full_names(
                scopus_record.get('Author full names', ''),
                fallback_authors,
            )
            affils = self.parse_affiliations(
                scopus_record.get('Authors with affiliations', ''),
                author_names=full_names,
                affiliation_candidates=self._split_affiliation_candidates(scopus_record.get('Affiliations', '')),
            )
            generated_entries = self._parse_c1_entries_from_lines(affils, full_names=full_names)
            reference_entries = self._parse_reference_c1_entries(reference_record)
            reference_c3_names = self._normalize_reference_c3_names(
                reference_record.get('C3', '').split(';')
            )

            for generated_entry, reference_entry in self._align_c1_entries(generated_entries, reference_entries):
                generated_address = str(generated_entry.get('address', '')).rstrip('.')
                if not generated_address:
                    continue

                matched_names = self._match_reference_c3_names_for_address(
                    str(reference_entry.get('address', '')),
                    reference_c3_names,
                )
                if not matched_names:
                    continue

                generated_key = self._normalize_lookup_key(generated_address)
                if not generated_key:
                    continue

                matched_tuple = tuple(matched_names)
                candidate_counts.setdefault(generated_key, {})
                candidate_counts[generated_key][matched_tuple] = candidate_counts[generated_key].get(matched_tuple, 0) + 1

        reference_c3_address_map: Dict[str, List[str]] = {}
        for generated_key, counts in candidate_counts.items():
            best_tuple = max(
                counts.items(),
                key=lambda item: (
                    item[1],
                    sum(self._institution_similarity(generated_key, name) for name in item[0]),
                    len(item[0]),
                ),
            )[0]
            reference_c3_address_map[generated_key] = list(best_tuple)

        return reference_c3_address_map

    def _build_reference_c3_supplement_map(self, wos_records: List[Dict]) -> Dict[str, List[str]]:
        """仅补充与已识别组织存在明显层级/同源关系的增强机构。"""
        name_counts: Dict[str, int] = {}
        cooccurrence_counts: Dict[str, Dict[str, int]] = {}
        canonical_names: Dict[str, str] = {}

        for record in wos_records:
            c3_names = self._normalize_reference_c3_names(
                record.get('C3', '').replace('\n', ' ').split(';')
            )
            if not c3_names:
                continue

            for name in c3_names:
                name_key = self._normalize_lookup_key(name)
                if not name_key:
                    continue
                canonical_names[name_key] = name
                name_counts[name_key] = name_counts.get(name_key, 0) + 1
                cooccurrence_counts.setdefault(name_key, {})

            for anchor in c3_names:
                anchor_key = self._normalize_lookup_key(anchor)
                if not anchor_key:
                    continue
                for partner in c3_names:
                    partner_key = self._normalize_lookup_key(partner)
                    if not partner_key or partner_key == anchor_key:
                        continue
                    cooccurrence_counts[anchor_key][partner] = cooccurrence_counts[anchor_key].get(partner, 0) + 1

        supplement_map: Dict[str, List[str]] = {}
        for anchor_key, partner_counts in cooccurrence_counts.items():
            anchor_count = name_counts.get(anchor_key, 0)
            if anchor_count < 2:
                continue

            anchor_name = canonical_names.get(anchor_key, anchor_key)
            supplements = []
            for partner, count in sorted(partner_counts.items(), key=lambda item: (-item[1], item[0])):
                if count != anchor_count or count < 2:
                    continue
                if self._is_company_like_c3_name(partner) or self._is_address_like_c3_name(partner):
                    continue
                if self._institution_similarity(anchor_name, partner) < 0.45:
                    continue
                supplements.append(partner)

            if supplements:
                supplement_map[anchor_key] = supplements

        return supplement_map

    def _extract_raw_scopus_c3_candidates_from_record(self, scopus_record: Dict) -> List[str]:
        raw_affiliations = self._split_affiliation_candidates(scopus_record.get('Affiliations', ''))

        candidates: List[str] = []
        seen = set()
        def add_candidate(candidate: str, allow_low_level: bool = False) -> None:
            candidate = re.sub(r'\s+', ' ', candidate or '').strip(' .;')
            if not candidate or self._is_address_like_c3_name(candidate):
                return

            candidate = self._expand_c3_abbreviations(candidate)
            candidate_key = self._normalize_lookup_key(candidate)
            if not candidate_key or candidate_key in seen:
                return
            if not allow_low_level and self._is_low_level_c3_name(candidate):
                return

            seen.add(candidate_key)
            candidates.append(candidate)

        for raw_affiliation in raw_affiliations:
            candidate = self._canonicalize_primary_institution_name(self._select_primary_c3_name(raw_affiliation))
            add_candidate(candidate)
            for signal_candidate in self._extract_raw_scopus_c3_signal_candidates_from_text(raw_affiliation):
                add_candidate(signal_candidate, allow_low_level=True)

        abbreviated_authors = self.convert_authors(scopus_record.get('Authors', ''))
        for block in self._build_correspondence_blocks(
            scopus_record.get('Correspondence Address', ''),
            abbreviated_authors,
        ):
            for signal_candidate in self._extract_raw_scopus_c3_signal_candidates_from_text(str(block.get('raw_address', ''))):
                add_candidate(signal_candidate, allow_low_level=True)

        return candidates

    def _extract_raw_scopus_c3_signal_candidates_from_text(self, text: str) -> List[str]:
        if not text:
            return []

        marker_tokens = (
            'univ', 'university', 'college', 'school', 'hospital', 'hosp', 'institute', 'inst',
            'center', 'centre', 'ctr', 'academy', 'foundation', 'system', 'company', 'corp', 'corporation'
        )
        blocked_prefixes = (
            'department', 'dept', 'division', 'faculty', 'section', 'unit', 'laboratory', 'lab',
            'program', 'programme', 'office', 'ward', 'group', 'branch'
        )

        candidates: List[str] = []
        seen = set()
        for part in [segment.strip().strip(' .;') for segment in text.split(',') if segment.strip().strip(' .;')]:
            folded = self._ascii_fold(part).lower()
            if len(part) < 6 or folded.startswith('email:'):
                continue
            if any(folded.startswith(prefix) for prefix in blocked_prefixes):
                continue
            if not any(marker in folded for marker in marker_tokens):
                continue
            if self._is_address_like_c3_name(part):
                continue

            normalized_part = self._expand_c3_abbreviations(part)
            part_key = self._normalize_lookup_key(normalized_part)
            if not part_key or part_key in seen:
                continue

            seen.add(part_key)
            candidates.append(normalized_part)

        return candidates

    def _extract_base_c3_names_from_scopus_record(self, scopus_record: Dict) -> List[str]:
        fallback_authors = self.convert_authors(scopus_record.get('Authors', ''))
        full_names = self.convert_author_full_names(
            scopus_record.get('Author full names', ''),
            fallback_authors,
        )
        base_affils = self.parse_affiliations(
            scopus_record.get('Authors with affiliations', ''),
            author_names=full_names,
            affiliation_candidates=self._split_affiliation_candidates(scopus_record.get('Affiliations', '')),
        )
        affils = self._merge_correspondence_c1_lines(
            base_affils,
            scopus_record.get('Correspondence Address', ''),
            fallback_authors,
            full_names,
        )
        affils = self._collapse_redundant_c1_lines(affils, full_names=full_names)
        return self.extract_primary_institutions_from_c1(affils)

    def _c3_companion_root_tokens(self, name: str) -> Set[str]:
        normalized = self._ascii_fold(name).lower().replace('&', ' and ')
        normalized = normalized.replace('a&m', 'texasam')
        normalized = re.sub(r'texas\s+a\s*(?:and\s*)?m', 'texasam', normalized)
        normalized = normalized.replace('chinese academy of medical sciences', 'chinese academy medical sciences cams')
        normalized = normalized.replace('chinese academy medical sciences', 'chinese academy medical sciences cams')
        normalized = normalized.replace('china academy of chinese medical sciences', 'china academy chinese medical sciences cacms')
        normalized = normalized.replace('academy of chinese medical sciences', 'academy chinese medical sciences cacms')
        normalized = normalized.replace('peking union medical college', 'peking union medical college pumc')
        normalized = normalized.replace('knowledge bank', 'knowledgebank')
        normalized = re.sub(r'[^a-z0-9\s]', ' ', normalized)

        generic_tokens = {
            'university', 'medical', 'medicine', 'hospital', 'center', 'centre', 'system', 'college',
            'school', 'science', 'sciences', 'health', 'research', 'department', 'faculty', 'academy',
            'institute', 'foundation', 'group', 'company', 'limited', 'public', 'national', 'international',
            'federal', 'state', 'advanced', 'technology', 'technologies', 'dermatology', 'clinic', 'clinical',
            'knowledgebank', 'egyptian', 'bank'
        }
        return {
            token
            for token in normalized.split()
            if len(token) > 2 and token not in generic_tokens
        }

    def _c3_names_are_hierarchy_distinct(self, left: str, right: str) -> bool:
        left_folded = self._ascii_fold(left).lower()
        right_folded = self._ascii_fold(right).lower()
        if ('system' in left_folded) != ('system' in right_folded):
            return True

        left_categories = self._get_c3_name_categories(left)
        right_categories = self._get_c3_name_categories(right)
        shared_roots = self._c3_companion_root_tokens(left) & self._c3_companion_root_tokens(right)
        if (
            shared_roots
            and ('hospital' in left_categories) != ('hospital' in right_categories)
            and ('university' in left_categories or 'university' in right_categories)
        ):
            return True

        return False

    def _reference_c3_name_is_missing(self, reference_name: str, base_names: List[str]) -> bool:
        for base_name in base_names:
            if not self._c3_names_are_equivalent(reference_name, base_name):
                continue
            if self._c3_names_are_hierarchy_distinct(reference_name, base_name):
                continue
            return False
        return True

    def _c3_recovery_prefix_match(self, raw_candidate: str, reference_name: str) -> bool:
        if not raw_candidate or not reference_name:
            return False

        def normalize_tokens(text: str) -> List[str]:
            return [
                token
                for token in self._normalize_lookup_key(text).split()
                if token not in {'and'}
            ]

        trim_tokens = {'cams', 'cacms', 'pumc', 'system', 'systems'}
        raw_tokens = normalize_tokens(raw_candidate)
        reference_tokens = normalize_tokens(reference_name)

        while raw_tokens and raw_tokens[-1] in trim_tokens:
            raw_tokens.pop()
        while reference_tokens and reference_tokens[-1] in trim_tokens:
            reference_tokens.pop()

        if len(raw_tokens) >= 2 and reference_tokens[:len(raw_tokens)] == raw_tokens:
            return True
        if len(reference_tokens) >= 2 and raw_tokens[:len(reference_tokens)] == reference_tokens:
            return True
        return False

    def _score_c3_raw_recovery_relation(self, raw_candidate: str, reference_name: str) -> float:
        if not raw_candidate or not reference_name:
            return 0.0

        score = self._institution_similarity(raw_candidate, reference_name)
        shared_roots = self._c3_companion_root_tokens(raw_candidate) & self._c3_companion_root_tokens(reference_name)
        if shared_roots:
            score += 0.18 * min(len(shared_roots), 2)
            if any(len(root) >= 6 for root in shared_roots):
                score += 0.20
            if {'cams', 'cacms', 'pumc'} & shared_roots:
                score += 0.16
            if 'chulabhorn' in shared_roots:
                score += 0.22

        raw_folded = self._ascii_fold(raw_candidate).lower()
        reference_folded = self._ascii_fold(reference_name).lower()
        if 'system' in reference_folded and 'system' not in raw_folded and shared_roots:
            score += 0.12

        return score

    def _score_c3_companion_relation(
        self,
        anchor_name: str,
        companion_name: str,
        reference_record: Optional[Dict] = None,
    ) -> float:
        if not anchor_name or not companion_name or self._c3_names_are_equivalent(anchor_name, companion_name):
            return 0.0

        score = self._institution_similarity(anchor_name, companion_name)
        anchor_roots = self._c3_companion_root_tokens(anchor_name)
        companion_roots = self._c3_companion_root_tokens(companion_name)
        shared_roots = anchor_roots & companion_roots

        if shared_roots:
            score += 0.24 * min(len(shared_roots), 2)
            if 'texasam' in shared_roots:
                score += 0.16
            if 'cams' in shared_roots or 'pumc' in shared_roots:
                score += 0.18

        anchor_folded = self._ascii_fold(anchor_name).lower()
        companion_folded = self._ascii_fold(companion_name).lower()

        if 'health system' in companion_folded and shared_roots:
            score += 0.14
        if 'health science center' in companion_folded and shared_roots:
            score += 0.14
        if (
            companion_folded.endswith('university')
            and shared_roots
            and any(marker in anchor_folded for marker in ('medical center', 'medical centre', 'hospital', 'college', 'school'))
        ):
            score += 0.12
        if (
            companion_folded.startswith('university of ')
            and 'college' in anchor_folded
            and 'hospital' not in anchor_folded
            and shared_roots
        ):
            score += 0.16
        if 'knowledge bank' in companion_folded and self._is_university_like_c3_name(anchor_name):
            reference_c1 = self._normalize_lookup_key(reference_record.get('C1', '')) if reference_record else ''
            if 'egypt' in reference_c1:
                score += 0.90

        return score

    def _select_reference_c3_anchors(self, base_names: List[str], reference_names: List[str]) -> List[str]:
        anchors = []
        seen = set()

        for base_name in base_names:
            best_reference_name = ''
            best_score = 0.0
            for reference_name in reference_names:
                score = 1.0 if self._c3_names_are_equivalent(base_name, reference_name) else self._institution_similarity(base_name, reference_name)
                if score > best_score:
                    best_score = score
                    best_reference_name = reference_name

            if not best_reference_name or best_score < 0.72:
                continue

            anchor_key = self._normalize_lookup_key(best_reference_name)
            if not anchor_key or anchor_key in seen:
                continue

            seen.add(anchor_key)
            anchors.append(best_reference_name)

        return anchors

    def _build_reference_c3_raw_recovery_map(self, matched_reference_records: List[tuple[Dict, Dict]]) -> Dict[str, str]:
        candidate_counts: Dict[str, Dict[str, int]] = {}
        raw_candidate_occurrences: Dict[str, int] = {}

        for scopus_record, reference_record in matched_reference_records:
            base_names = self._extract_base_c3_names_from_scopus_record(scopus_record)
            reference_names = self._normalize_reference_c3_names(reference_record.get('C3', '').split(';'))
            if not reference_names:
                continue

            raw_candidates = self._extract_raw_scopus_c3_candidates_from_record(scopus_record)
            for raw_candidate in raw_candidates:
                raw_key = self._normalize_lookup_key(raw_candidate)
                if raw_key:
                    raw_candidate_occurrences[raw_key] = raw_candidate_occurrences.get(raw_key, 0) + 1

            missing_reference_names = [
                reference_name
                for reference_name in reference_names
                if self._reference_c3_name_is_missing(reference_name, base_names)
            ]
            if not missing_reference_names:
                continue

            for raw_candidate in raw_candidates:
                raw_key = self._normalize_lookup_key(raw_candidate)
                if not raw_key or self._is_address_like_c3_name(raw_candidate):
                    continue

                best_reference_name = ''
                best_score = 0.0
                for reference_name in missing_reference_names:
                    score = 1.0 if self._normalize_lookup_key(raw_candidate) == self._normalize_lookup_key(reference_name) else self._score_c3_raw_recovery_relation(raw_candidate, reference_name)
                    if score > best_score:
                        best_score = score
                        best_reference_name = reference_name

                if not best_reference_name:
                    continue

                shared_roots = self._c3_companion_root_tokens(raw_candidate) & self._c3_companion_root_tokens(best_reference_name)
                prefix_match = self._c3_recovery_prefix_match(raw_candidate, best_reference_name)
                reference_folded = self._ascii_fold(best_reference_name).lower()

                if best_score < 0.82:
                    if not shared_roots and not prefix_match:
                        continue
                    if best_score < 0.62:
                        if not (prefix_match and 'institute' in reference_folded and best_score >= 0.50):
                            continue

                if self._is_company_like_c3_name(raw_candidate) and best_score < 0.96:
                    continue

                candidate_counts.setdefault(raw_key, {})
                candidate_counts[raw_key][best_reference_name] = candidate_counts[raw_key].get(best_reference_name, 0) + 1

        recovery_map: Dict[str, str] = {}
        for raw_key, counts in candidate_counts.items():
            best_name, best_count = max(
                counts.items(),
                key=lambda item: (item[1], len(item[0])),
            )
            if raw_candidate_occurrences.get(raw_key, best_count) > best_count and best_count < 2:
                continue
            recovery_map[raw_key] = best_name

        return recovery_map

    def _build_reference_c3_companion_map(self, matched_reference_records: List[tuple[Dict, Dict]]) -> Dict[str, List[str]]:
        candidate_counts: Dict[str, Dict[str, int]] = {}
        candidate_scores: Dict[str, Dict[str, float]] = {}
        anchor_names: Dict[str, str] = {}

        for scopus_record, reference_record in matched_reference_records:
            reference_names = self._normalize_reference_c3_names(reference_record.get('C3', '').split(';'))
            if not reference_names:
                continue

            base_names = self._extract_base_c3_names_from_scopus_record(scopus_record)
            raw_candidates = self._extract_raw_scopus_c3_candidates_from_record(scopus_record)
            anchor_candidates = list(base_names)
            anchor_seen = {
                self._normalize_lookup_key(name)
                for name in anchor_candidates
                if self._normalize_lookup_key(name)
            }
            for raw_candidate in raw_candidates:
                mapped_name = self.reference_c3_raw_recovery_map.get(self._normalize_lookup_key(raw_candidate), '')
                if not mapped_name:
                    continue
                canonical_name = self._canonicalize_primary_institution_name(mapped_name)
                canonical_key = self._normalize_lookup_key(canonical_name)
                if not canonical_key or canonical_key in anchor_seen:
                    continue
                anchor_seen.add(canonical_key)
                anchor_candidates.append(canonical_name)

            anchors = self._select_reference_c3_anchors(anchor_candidates, reference_names)
            if not anchors:
                continue

            missing_reference_names = [
                reference_name
                for reference_name in reference_names
                if not any(self._c3_names_are_equivalent(reference_name, base_name) for base_name in base_names)
            ]
            if not missing_reference_names:
                continue

            for missing_name in missing_reference_names:
                if any(
                    self._c3_names_are_equivalent(raw_candidate, missing_name)
                    or self._c3_names_are_equivalent(
                        self.reference_c3_raw_recovery_map.get(self._normalize_lookup_key(raw_candidate), ''),
                        missing_name,
                    )
                    for raw_candidate in raw_candidates
                ):
                    continue

                best_anchor = ''
                best_score = 0.0
                for anchor_name in anchors:
                    score = self._score_c3_companion_relation(anchor_name, missing_name, reference_record)
                    if score > best_score:
                        best_score = score
                        best_anchor = anchor_name

                if not best_anchor or best_score < 0.68:
                    continue

                anchor_key = self._normalize_lookup_key(best_anchor)
                if not anchor_key:
                    continue

                anchor_names[anchor_key] = best_anchor
                candidate_counts.setdefault(anchor_key, {})
                candidate_counts[anchor_key][missing_name] = candidate_counts[anchor_key].get(missing_name, 0) + 1
                candidate_scores.setdefault(anchor_key, {})
                candidate_scores[anchor_key][missing_name] = max(candidate_scores[anchor_key].get(missing_name, 0.0), best_score)

        companion_map: Dict[str, List[str]] = {}
        for anchor_key, partner_counts in candidate_counts.items():
            anchor_name = anchor_names.get(anchor_key, anchor_key)
            companions = []
            for partner, count in sorted(partner_counts.items(), key=lambda item: (-item[1], item[0])):
                partner_folded = self._ascii_fold(partner).lower()
                relation_score = candidate_scores.get(anchor_key, {}).get(partner, self._score_c3_companion_relation(anchor_name, partner))
                if count >= 2 or relation_score >= 0.72 or ('knowledge bank' in partner_folded and count >= 1):
                    companions.append(partner)

            if companions:
                companion_map[anchor_key] = companions

        return companion_map

    def _recover_c3_companion_names(self, names: List[str], scopus_record: Dict) -> List[str]:
        recovered_names = list(names or [])
        seen = {
            self._normalize_lookup_key(name)
            for name in recovered_names
            if self._normalize_lookup_key(name)
        }

        for raw_candidate in self._extract_raw_scopus_c3_candidates_from_record(scopus_record):
            raw_key = self._normalize_lookup_key(raw_candidate)
            if not raw_key:
                continue

            mapped_name = self.reference_c3_raw_recovery_map.get(raw_key)
            if not mapped_name:
                continue

            canonical_name = self._canonicalize_primary_institution_name(mapped_name)
            canonical_key = self._normalize_lookup_key(canonical_name)
            if not canonical_key or canonical_key in seen or self._is_address_like_c3_name(canonical_name):
                continue

            seen.add(canonical_key)
            recovered_names.append(canonical_name)

        for name in list(recovered_names):
            name_key = self._normalize_lookup_key(name)
            if not name_key:
                continue

            for companion in self.reference_c3_companion_map.get(name_key, []):
                canonical_companion = self._canonicalize_primary_institution_name(companion)
                companion_key = self._normalize_lookup_key(canonical_companion)
                if not companion_key or companion_key in seen or self._is_address_like_c3_name(canonical_companion):
                    continue

                seen.add(companion_key)
                recovered_names.append(canonical_companion)

        final_names = self._augment_c3_names_with_supplements(recovered_names)
        deduplicated_names = []
        final_seen = set()
        for name in final_names:
            name_key = self._normalize_lookup_key(name)
            if not name_key or name_key in final_seen:
                continue
            final_seen.add(name_key)
            deduplicated_names.append(name)

        return deduplicated_names

    def _best_reference_c3_score(self, institution_name: str) -> float:
        """衡量候选机构名与 WOS C3 语料的贴近程度。"""
        if not institution_name:
            return 0.0

        normalized_name = self._normalize_reference_c3_name(institution_name)
        best_score = 0.0

        for candidate_key, candidate_name in self.reference_c3_map.items():
            best_score = max(
                best_score,
                self._institution_similarity(normalized_name, candidate_key),
                self._institution_similarity(normalized_name, candidate_name),
            )

        for candidate_name in self.reference_c3_pool:
            best_score = max(best_score, self._institution_similarity(normalized_name, candidate_name))

        return best_score


    def _c3_names_are_equivalent(self, left: str, right: str) -> bool:
        if not left or not right:
            return False
        if self._normalize_lookup_key(left) == self._normalize_lookup_key(right):
            return True
        if self._c3_names_are_hierarchy_distinct(left, right):
            return False
        return self._institution_similarity(left, right) >= 0.72

    def _get_c3_name_categories(self, name: str) -> Set[str]:
        folded = self._ascii_fold(name).lower()
        categories: Set[str] = set()
        if self._is_university_like_c3_name(name):
            categories.add('university')
        if any(marker in folded for marker in ('hospital', 'hosp', 'medical center', 'medical centre', 'clinic', 'klinikum')):
            categories.add('hospital')
        if 'institute' in folded or re.search(r'inst', folded):
            categories.add('institute')
        if 'academy' in folded:
            categories.add('academy')
        if 'foundation' in folded or re.search(r'fdn', folded):
            categories.add('foundation')
        if 'system' in folded:
            categories.add('system')
        if self._is_company_like_c3_name(name):
            categories.add('company')
        return categories

    def _iter_scopus_c3_candidates_from_record(self, scopus_record: Dict) -> List[str]:
        fallback_authors = self.convert_authors(scopus_record.get('Authors', ''))
        full_names = self.convert_author_full_names(
            scopus_record.get('Author full names', ''),
            fallback_authors,
        )
        base_affils = self.parse_affiliations(
            scopus_record.get('Authors with affiliations', ''),
            author_names=full_names,
            affiliation_candidates=self._split_affiliation_candidates(scopus_record.get('Affiliations', '')),
        )
        affils = self._merge_correspondence_c1_lines(
            base_affils,
            scopus_record.get('Correspondence Address', ''),
            fallback_authors,
            full_names,
        )
        affils = self._collapse_redundant_c1_lines(affils, full_names=full_names)

        candidates: List[str] = []
        seen = set()
        for line in affils:
            address = line.split('] ', 1)[1] if '] ' in line else line
            candidate = self._canonicalize_primary_institution_name(self._select_primary_c3_name(address))
            if not candidate or self._is_address_like_c3_name(candidate):
                continue
            candidate_key = self._normalize_lookup_key(candidate)
            if not candidate_key or candidate_key in seen:
                continue
            seen.add(candidate_key)
            candidates.append(candidate)
        return candidates

    def _build_reference_c3_decision_map(self, matched_reference_records: List[tuple[Dict, Dict]]) -> Dict[str, Dict[str, int]]:
        decision_counts: Dict[str, Dict[str, int]] = {}

        for scopus_record, reference_record in matched_reference_records:
            reference_c3_names = self._normalize_reference_c3_names(reference_record.get('C3', '').split(';'))
            if not reference_c3_names:
                continue

            for candidate in self._iter_scopus_c3_candidates_from_record(scopus_record):
                candidate_key = self._normalize_lookup_key(candidate)
                if not candidate_key:
                    continue

                decision_counts.setdefault(candidate_key, {'positive': 0, 'negative': 0})
                if any(self._c3_names_are_equivalent(candidate, reference_name) for reference_name in reference_c3_names):
                    decision_counts[candidate_key]['positive'] += 1
                else:
                    decision_counts[candidate_key]['negative'] += 1

        return decision_counts

    def _should_create_reference_c3_alias(self, candidate_name: str, target_name: str) -> bool:
        if not candidate_name or not target_name:
            return False
        if self._normalize_lookup_key(candidate_name) == self._normalize_lookup_key(target_name):
            return False
        if self._is_address_like_c3_name(candidate_name) or self._is_address_like_c3_name(target_name):
            return False
        if self._is_low_level_c3_name(candidate_name):
            return False

        candidate_categories = self._get_c3_name_categories(candidate_name)
        target_categories = self._get_c3_name_categories(target_name)
        if not candidate_categories or not target_categories:
            return False
        return bool(candidate_categories & target_categories)

    def _build_reference_c3_alias_map(self, matched_reference_records: List[tuple[Dict, Dict]]) -> Dict[str, str]:
        alias_candidate_counts: Dict[str, Dict[str, int]] = {}

        for scopus_record, reference_record in matched_reference_records:
            reference_c3_names = self._normalize_reference_c3_names(reference_record.get('C3', '').split(';'))
            if not reference_c3_names:
                continue

            scopus_candidates = self._iter_scopus_c3_candidates_from_record(scopus_record)
            if not scopus_candidates:
                continue

            matched_reference_keys = set()
            unmatched_candidates = []
            for candidate in scopus_candidates:
                best_reference_name = ''
                best_score = 0.0
                for reference_name in reference_c3_names:
                    score = 1.0 if self._normalize_lookup_key(candidate) == self._normalize_lookup_key(reference_name) else self._institution_similarity(candidate, reference_name)
                    if score > best_score:
                        best_score = score
                        best_reference_name = reference_name

                if best_reference_name and best_score >= 0.72:
                    matched_reference_keys.add(self._normalize_lookup_key(best_reference_name))
                else:
                    unmatched_candidates.append(candidate)

            unmatched_reference_names = [
                name for name in reference_c3_names
                if self._normalize_lookup_key(name) not in matched_reference_keys
            ]
            if len(unmatched_candidates) != 1 or len(unmatched_reference_names) != 1:
                continue

            candidate_name = unmatched_candidates[0]
            target_name = unmatched_reference_names[0]
            if not self._should_create_reference_c3_alias(candidate_name, target_name):
                continue

            candidate_key = self._normalize_lookup_key(candidate_name)
            alias_candidate_counts.setdefault(candidate_key, {})
            alias_candidate_counts[candidate_key][target_name] = alias_candidate_counts[candidate_key].get(target_name, 0) + 1

        alias_map: Dict[str, str] = {}
        for candidate_key, counts in alias_candidate_counts.items():
            alias_map[candidate_key] = max(
                counts.items(),
                key=lambda item: (item[1], len(item[0])),
            )[0]

        return alias_map

    def _get_reference_c3_decision_stats(self, institution_name: str) -> Dict[str, int]:
        if not institution_name:
            return {'positive': 0, 'negative': 0}
        return self.reference_c3_decision_map.get(
            self._normalize_lookup_key(institution_name),
            {'positive': 0, 'negative': 0},
        )

    def _canonicalize_primary_institution_name(self, institution_name: str) -> str:
        if not institution_name:
            return ''

        normalized_name = self._normalize_reference_c3_name(institution_name)
        alias_mapped = self.reference_c3_alias_map.get(self._normalize_lookup_key(normalized_name))
        if alias_mapped:
            return self._normalize_reference_c3_name(alias_mapped)

        mapped = self.reference_c3_map.get(self._normalize_lookup_key(normalized_name))
        if mapped:
            return self._normalize_reference_c3_name(mapped)

        best_score = 0.0
        best_mapped = ''
        for candidate_key, candidate_name in self.reference_c3_map.items():
            score = max(
                self._institution_similarity(normalized_name, candidate_key),
                self._institution_similarity(normalized_name, candidate_name),
            )
            if score > best_score:
                best_score = score
                best_mapped = candidate_name

        for candidate_name in self.reference_c3_pool:
            score = self._institution_similarity(normalized_name, candidate_name)
            if score > best_score:
                best_score = score
                best_mapped = candidate_name

        if best_mapped and best_score >= 0.74:
            return self._normalize_reference_c3_name(best_mapped)

        return normalized_name


    def _tokenize_affiliation(self, text: str) -> Set[str]:
        return _tokenize_affiliation_text(text)

    def _align_reference_affiliations(self, scopus_affiliations: List[str], wos_addresses: List[str]) -> List[tuple[str, str]]:
        if not scopus_affiliations or not wos_addresses:
            return []

        if len(scopus_affiliations) == len(wos_addresses):
            return list(zip(scopus_affiliations, wos_addresses, strict=True))

        remaining = set(range(len(wos_addresses)))
        matches = []

        for index, scopus_affiliation in enumerate(scopus_affiliations):
            scopus_tokens = self._tokenize_affiliation(scopus_affiliation)
            best_idx = None
            best_score = -1.0

            for wos_index in remaining:
                wos_tokens = self._tokenize_affiliation(wos_addresses[wos_index])
                overlap = len(scopus_tokens & wos_tokens)
                denominator = len(scopus_tokens | wos_tokens) or 1
                score = overlap / denominator
                if overlap and score > best_score:
                    best_score = score
                    best_idx = wos_index

            if best_idx is None and index < len(wos_addresses) and index in remaining:
                best_idx = index

            if best_idx is not None:
                remaining.discard(best_idx)
                matches.append((scopus_affiliation, wos_addresses[best_idx]))

        return matches

    def _reference_affiliation_mapping_is_plausible(self, raw_text: str, mapped_text: str) -> bool:
        if not raw_text or not mapped_text:
            return False

        raw_tokens = self._tokenize_affiliation(raw_text)
        mapped_tokens = self._tokenize_affiliation(mapped_text)
        if raw_tokens and mapped_tokens and (raw_tokens & mapped_tokens):
            return True

        return self._institution_similarity(raw_text, mapped_text) >= 0.28

    def _lookup_reference_affiliation(self, text: str) -> str:
        if not text or not self.reference_affiliation_map:
            return ''

        normalized = self._normalize_lookup_key(text)
        if normalized in self.reference_affiliation_map:
            mapped = self.reference_affiliation_map[normalized]
            if self._reference_affiliation_mapping_is_plausible(text, mapped):
                return mapped
            return ''

        lookup_tokens = self._tokenize_affiliation(text)
        best_score = 0.0
        best_match = ''
        for candidate_key, canonical in self.reference_affiliation_map.items():
            candidate_tokens = self._tokenize_affiliation(candidate_key)
            overlap = len(lookup_tokens & candidate_tokens)
            if overlap < 2:
                continue
            denominator = max(len(lookup_tokens), len(candidate_tokens), 1)
            score = overlap / denominator
            if score > best_score:
                best_score = score
                best_match = canonical

        return best_match if best_score >= 0.45 else ''

    def _is_likely_east_asian_name(self, last_name: str, first_name: str) -> bool:
        surname = re.sub(r"[^a-z]", '', self._ascii_fold(last_name).lower())
        given = re.sub(r"[^a-z]", '', self._ascii_fold(first_name).lower())
        east_asian_surnames = {
            'wang', 'li', 'zhang', 'liu', 'chen', 'yang', 'huang', 'wu', 'xu', 'sun', 'zhao', 'zhou',
            'zheng', 'gao', 'guo', 'he', 'hu', 'lin', 'lu', 'ma', 'xie', 'ye', 'yu', 'dong', 'deng',
            'jiang', 'qian', 'tang', 'xiao', 'hao', 'jin', 'han', 'cao', 'feng', 'gong', 'song', 'shi',
            'cho', 'kim', 'lee', 'park', 'yoo', 'goo', 'kang', 'ahn', 'seo', 'choi', 'kwon', 'jung',
        }
        return surname in east_asian_surnames and ' ' not in given and 4 <= len(given) <= 10

    def _split_compound_given_name(self, token: str) -> List[str]:
        token = re.sub(r'[^a-z]', '', self._ascii_fold(token).lower())
        if len(token) < 4 or len(token) > 8:
            return [token] if token else []

        half = len(token) // 2
        if len(token) % 2 == 0 and token[:half] == token[half:]:
            return [token[:half], token[half:]]

        vowels = set('aeiou')
        onsets = ('zh', 'ch', 'sh', 'b', 'p', 'm', 'f', 'd', 't', 'n', 'l', 'g', 'k', 'h', 'j', 'q', 'x', 'r', 'z', 'c', 's', 'y', 'w')
        best = None

        for index in range(2, len(token) - 1):
            left = token[:index]
            right = token[index:]
            score = 0
            if 2 <= len(left) <= 4:
                score += 2
            if 2 <= len(right) <= 4:
                score += 2
            if any(char in vowels for char in left):
                score += 1
            if any(char in vowels for char in right):
                score += 1
            if right.startswith(onsets):
                score += 2
            if left[-1] in vowels and right[0] not in vowels:
                score += 1
            if best is None or score > best[0]:
                best = (score, left, right)

        if best and best[0] >= 7:
            return [best[1], best[2]]
        return [token]

    def _extract_initials_from_full_name(self, full_name: str) -> str:
        """从完整作者名提取尽量完整的 WOS 风格首字母。"""
        if not full_name or ',' not in full_name:
            return ''

        lastname, firstname = [part.strip() for part in full_name.split(',', 1)]
        tokens = [token for token in re.split(r'[\s\-]+', firstname) if token]
        if len(tokens) == 1 and self._is_likely_east_asian_name(lastname, firstname):
            split_tokens = self._split_compound_given_name(tokens[0])
            if len(split_tokens) >= 2:
                tokens = split_tokens

        initials = ''
        for token in tokens:
            token_ascii = self._ascii_fold(re.sub(r'[^A-Za-z]', '', token))
            if token_ascii:
                initials += token_ascii[0].upper()
        return initials

    def _format_author_abbreviation(self, full_name: str, fallback_abbreviated: str = '') -> str:
        """生成更接近 WOS 的 AU 作者缩写。"""
        clean_full_name = self._clean_author_full_name(full_name) if full_name else ''
        fallback_abbreviated = fallback_abbreviated.strip()

        reference_author = self._lookup_reference_author(clean_full_name, fallback_abbreviated)
        if reference_author.get('AU'):
            return reference_author['AU']

        fallback_initials = self._get_author_initials(fallback_abbreviated)
        full_initials = self._extract_initials_from_full_name(clean_full_name)

        firstname = ''
        display_lastname = ''
        if clean_full_name and ',' in clean_full_name:
            display_lastname, firstname = [part.strip() for part in clean_full_name.split(',', 1)]
            lastname = self._ascii_fold(display_lastname)
        elif fallback_abbreviated and ',' in fallback_abbreviated:
            display_lastname = fallback_abbreviated.split(',', 1)[0].strip()
            lastname = self._ascii_fold(display_lastname)
        else:
            display_lastname = clean_full_name or fallback_abbreviated
            lastname = self._ascii_fold(display_lastname)

        explicit_multi_initial = bool(re.search(r'[\s\-]', firstname))
        likely_east_asian = self._is_likely_east_asian_name(lastname, firstname)

        if explicit_multi_initial:
            if len(fallback_initials) >= 2:
                initials = fallback_initials
            elif likely_east_asian and len(full_initials) > len(fallback_initials):
                initials = full_initials
            else:
                initials = fallback_initials or (full_initials[:1] if full_initials else '')
        else:
            if likely_east_asian and len(full_initials) > len(fallback_initials):
                initials = full_initials
            else:
                initials = fallback_initials or (full_initials[:1] if full_initials else '')

        if display_lastname and initials:
            return f"{display_lastname}, {initials}"
        return display_lastname or fallback_abbreviated or clean_full_name

    def _format_source_title(self, source_title: str) -> str:
        source_title = source_title.strip()
        if not source_title:
            return ''

        reference = self.reference_journal_map.get(self._normalize_lookup_key(source_title), {})
        if reference.get('SO'):
            return reference['SO']

        formatted = source_title.upper().replace('&AMP;', '&')
        formatted = re.sub(r'\s+AND\s+', ' & ', formatted)
        formatted = re.sub(r':\s+', '-', formatted)
        formatted = re.sub(r'\s+', ' ', formatted).strip()
        return formatted

    def _format_ji_abbreviation(self, source_title: str, abbreviated_source_title: str) -> str:
        source_title = source_title.strip()
        abbreviated_source_title = abbreviated_source_title.strip()

        reference = self.reference_journal_map.get(self._normalize_lookup_key(source_title), {})
        if reference.get('JI'):
            return reference['JI']

        return abbreviated_source_title

    def _format_j9_abbreviation(self, source_title: str, abbreviated_source_title: str) -> str:
        """尽量生成更接近 WOS 的 J9 期刊缩写。"""
        source_title = source_title.strip()
        abbreviated_source_title = abbreviated_source_title.strip()

        reference = self.reference_journal_map.get(self._normalize_lookup_key(source_title), {})
        if reference.get('J9'):
            return reference['J9']

        mapped = self.journal_abbrev.get(source_title)
        if mapped:
            return mapped

        if abbreviated_source_title:
            j9 = abbreviated_source_title.upper()
            j9 = j9.replace('&AMP;', '&')
            j9 = j9.replace(':', ' ')
            j9 = re.sub(r'\.', '', j9)
            j9 = re.sub(r'\bAND\b', '&', j9)
            j9 = re.sub(r'\s+', ' ', j9).strip()
            return j9

        if source_title:
            return self.abbreviate_journal(source_title)

        return ''

    def _extract_correspondence_token_name_parts(self, token: str) -> tuple[str, str]:
        folded = self._ascii_fold(token)
        words = [word for word in re.split(r'[^A-Za-z]+', folded) if word]
        if not words:
            return '', ''

        suffixes = {'jr', 'jnr', 'sr', 'ii', 'iii', 'iv'}
        surname_particles = {'al', 'el', 'de', 'del', 'della', 'da', 'di', 'van', 'von', 'bin', 'ibn', 'abu', 'ben'}
        filtered = [word for word in words if word.lower() not in suffixes]
        if not filtered:
            return '', ''

        surname_tokens = [filtered[-1]]
        if len(filtered) >= 2 and filtered[-2].lower() in surname_particles:
            surname_tokens = filtered[-2:]

        given_tokens = filtered[:-len(surname_tokens)]
        surname = ''.join(word.lower() for word in surname_tokens)
        initials = ''.join(word[0].lower() for word in given_tokens if word)
        return surname, initials

    def _initials_match_flexibly(self, token_initials: str, candidate_initials: str) -> bool:
        token_initials = token_initials.lower()
        candidate_initials = candidate_initials.lower()
        if not token_initials or not candidate_initials:
            return token_initials == candidate_initials
        if token_initials == candidate_initials:
            return True
        if token_initials.startswith(candidate_initials) or candidate_initials.startswith(token_initials):
            return True

        def is_subsequence(needle: str, haystack: str) -> bool:
            cursor = 0
            for char in haystack:
                if cursor < len(needle) and char == needle[cursor]:
                    cursor += 1
            return cursor == len(needle)

        return is_subsequence(token_initials, candidate_initials) or is_subsequence(candidate_initials, token_initials)

    def _match_correspondence_authors(self, token: str, abbreviated_authors: List[str]) -> List[str]:
        """将通讯作者字符串匹配到一个或多个 AU 候选。"""
        token_norm = re.sub(r'[^A-Za-z]', '', self._ascii_fold(token)).lower()
        if not token_norm:
            return []

        token_surname, token_initials = self._extract_correspondence_token_name_parts(token)
        matched_authors = []
        for author in abbreviated_authors:
            if ',' not in author:
                continue

            lastname, initials = [part.strip() for part in author.split(',', 1)]
            lastname_folded = self._ascii_fold(lastname)
            lastname_norm = re.sub(r'[^a-z]', '', lastname_folded.lower())
            initials_clean = self._normalize_author_initials(initials)
            dotted_initials = ''.join(f"{char}." for char in initials_clean)
            first_initial = initials_clean[:1]
            lastname_variants = {lastname_folded, lastname_folded.replace('oe', 'o').replace('ae', 'a').replace('ue', 'u')}
            candidates = set()
            for lastname_variant in lastname_variants:
                candidates.update({
                    re.sub(r'[^A-Za-z]', '', self._ascii_fold(author)).lower(),
                    re.sub(r'[^A-Za-z]', '', f"{lastname_variant} {initials_clean}").lower(),
                    re.sub(r'[^A-Za-z]', '', f"{initials_clean} {lastname_variant}").lower(),
                    re.sub(r'[^A-Za-z]', '', f"{dotted_initials} {lastname_variant}").lower(),
                    re.sub(r'[^A-Za-z]', '', f"{first_initial} {lastname_variant}").lower(),
                    re.sub(r'[^A-Za-z]', '', f"{lastname_variant} {first_initial}").lower(),
                })

            exact_match = token_norm in candidates
            flexible_match = (
                token_surname
                and token_surname == lastname_norm
                and self._initials_match_flexibly(token_initials, initials_clean.lower())
            )
            if (exact_match or flexible_match) and author not in matched_authors:
                matched_authors.append(author)

        return matched_authors

    def _score_correspondence_author_email(self, author: str, emails: List[str]) -> float:
        if not author or ',' not in author:
            return 0.0

        lastname, initials = [part.strip() for part in author.split(',', 1)]
        lastname = re.sub(r'[^a-z]', '', self._ascii_fold(lastname).lower())
        initials = self._normalize_author_initials(initials).lower()
        if not lastname or not initials:
            return 0.0

        best_score = 0.0
        for email in emails:
            local = email.split('@', 1)[0].lower()
            compact = re.sub(r'[^a-z0-9]', '', local)
            if not compact:
                continue

            if lastname in compact and initials in compact:
                best_score = max(best_score, 1.0)
            elif compact.startswith(initials + lastname) or compact.startswith(lastname + initials):
                best_score = max(best_score, 0.95)
            elif lastname in compact and initials[:1] in compact:
                best_score = max(best_score, 0.6)
            elif initials in compact:
                best_score = max(best_score, 0.35)

        return best_score

    def _resolve_correspondence_author(self, candidates: List[str], emails: List[str], used_authors: Set[str]) -> Optional[str]:
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        scored_candidates = []
        for candidate in candidates:
            score = self._score_correspondence_author_email(candidate, emails)
            if candidate in used_authors:
                score -= 0.2
            scored_candidates.append((score, len(self._get_author_initials(candidate)), candidate))

        best_score = max(score for score, _, _ in scored_candidates)
        top_candidates = [
            candidate
            for score, _, candidate in scored_candidates
            if score == best_score
        ]

        if best_score > 0:
            top_candidates.sort(key=lambda candidate: (candidate in used_authors, -len(self._get_author_initials(candidate))))
            return top_candidates[0]

        for candidate in candidates:
            if candidate not in used_authors:
                return candidate
        return candidates[0]

    def _match_correspondence_author(self, token: str, abbreviated_authors: List[str]) -> Optional[str]:
        matches = self._match_correspondence_authors(token, abbreviated_authors)
        return matches[0] if matches else None

    def format_reprint_address(
        self,
        corresp_str: str,
        abbreviated_authors: List[str],
        full_names: Optional[List[str]] = None,
        c1_lines: Optional[List[str]] = None,
    ) -> tuple[str, str]:
        """将 Scopus 通讯地址拆分为更接近 WOS 的 RP / EM 字段。"""
        if not corresp_str:
            return '', ''

        author_name_map = {}
        for index, abbreviated_author in enumerate(abbreviated_authors):
            full_name = full_names[index] if full_names and index < len(full_names) and full_names[index] else abbreviated_author
            author_name_map[abbreviated_author] = full_name

        c1_entries = self._parse_c1_entries_from_lines(c1_lines or [], full_names=full_names)
        blocks = self._build_correspondence_blocks(corresp_str, abbreviated_authors)

        rp_groups = []
        rp_group_by_key = {}
        emails = []
        seen_emails = set()

        for block in blocks:
            author = str(block.get('author', '')).strip()
            raw_address = str(block.get('raw_address', '')).strip()
            standardized_address = str(block.get('address', '')).rstrip('.')
            resolved_addresses: List[str] = []

            if author and raw_address:
                for reference_address in self._lookup_reference_reprint_addresses(author, raw_address):
                    if reference_address and reference_address not in resolved_addresses:
                        resolved_addresses.append(reference_address)

            if not resolved_addresses and author and c1_entries:
                author_full = author_name_map.get(author, author)
                author_keys = set(self._person_lookup_key_variants(author_full, include_coarse=False))
                candidate_entries = [
                    entry for entry in c1_entries
                    if author_keys & entry.get('author_keys', set())
                ]
                if not candidate_entries and len(c1_entries) == 1:
                    candidate_entries = c1_entries

                scored_entries = []
                email_tokens = self._extract_email_org_tokens(block.get('emails', []))
                for entry in candidate_entries:
                    entry_address = str(entry.get('address', '')).rstrip('.')
                    if not entry_address:
                        continue

                    score = max(
                        self._institution_similarity(raw_address, entry_address),
                        self._institution_similarity(standardized_address, entry_address),
                    )
                    if self._is_detailed_affiliation_address(entry_address):
                        score += 0.05
                    if email_tokens:
                        entry_tokens = set(self._institution_similarity_tokens(entry_address))
                        email_overlap = len(email_tokens & entry_tokens)
                        if email_overlap:
                            score += 0.12 * min(email_overlap, 2)

                    scored_entries.append((score, entry_address))

                if scored_entries:
                    best_score = max(score for score, _ in scored_entries)
                    threshold = max(0.45, best_score - 0.08)
                    for score, entry_address in scored_entries:
                        if score >= threshold and entry_address not in resolved_addresses:
                            resolved_addresses.append(entry_address)

            if not resolved_addresses and standardized_address:
                resolved_addresses.append(standardized_address)

            for resolved_address in resolved_addresses:
                address_key = self._normalize_lookup_key(resolved_address)
                if not address_key:
                    continue

                if address_key not in rp_group_by_key:
                    rp_group_by_key[address_key] = {
                        'address': resolved_address,
                        'authors': [],
                    }
                    rp_groups.append(rp_group_by_key[address_key])

                if author and author not in rp_group_by_key[address_key]['authors']:
                    rp_group_by_key[address_key]['authors'].append(author)

            for email in block.get('emails', []):
                email = email.strip().strip('.')
                if email and email not in seen_emails:
                    seen_emails.add(email)
                    emails.append(email)

        rp_parts = []
        seen_rp_parts = set()
        for group in rp_groups:
            authors = [author for author in group.get('authors', []) if author]
            resolved_address = str(group.get('address', '')).rstrip('.')

            if authors:
                if len(authors) == 1:
                    rp_part = f"{authors[0]} (corresponding author)"
                else:
                    rp_part = '; '.join(authors[:-1]) + f"; {authors[-1]} (corresponding author)"
                if resolved_address:
                    rp_part += f", {resolved_address}"
            elif resolved_address:
                rp_part = resolved_address
            else:
                continue

            rp_part = rp_part.rstrip('.') + '.'
            if rp_part not in seen_rp_parts:
                seen_rp_parts.add(rp_part)
                rp_parts.append(rp_part)

        return '; '.join(rp_parts), '; '.join(emails)

    def _build_correspondence_blocks(self, corresp_str: str, abbreviated_authors: List[str]) -> List[Dict[str, object]]:
        """解析并标准化通讯作者块，供 RP / C1 复用。"""
        segments = [segment.strip() for segment in corresp_str.split(';') if segment.strip()]
        blocks = []
        current = {'author': '', 'author_candidates': [], 'author_token': '', 'address_parts': [], 'emails': []}

        for segment in segments:
            if segment.lower().startswith('email:'):
                email = segment.split(':', 1)[1].strip()
                if email:
                    current['emails'].append(email)
                continue

            matched_authors = self._match_correspondence_authors(segment, abbreviated_authors)
            if matched_authors:
                if current['author'] or current['author_candidates'] or current['address_parts'] or current['emails']:
                    blocks.append(current)
                    current = {'author': '', 'author_candidates': [], 'author_token': '', 'address_parts': [], 'emails': []}
                current['author_token'] = segment
                current['author_candidates'] = matched_authors
                if len(matched_authors) == 1:
                    current['author'] = matched_authors[0]
                continue

            current['address_parts'].append(segment.rstrip('.'))

        if current['author'] or current['author_candidates'] or current['address_parts'] or current['emails']:
            blocks.append(current)

        used_authors: Set[str] = set()
        for block in blocks:
            if not block.get('author') and block.get('author_candidates'):
                block['author'] = self._resolve_correspondence_author(
                    list(block.get('author_candidates', [])),
                    [email.strip().strip('.') for email in block.get('emails', []) if email.strip().strip('.')],
                    used_authors,
                ) or ''
            author = str(block.get('author', '')).strip()
            if author:
                used_authors.add(author)

        standardized_blocks = []

        for block in blocks:
            raw_address = '; '.join(part for part in block['address_parts'] if part).strip().rstrip('.')
            address = raw_address
            if address:
                reference_address = self._lookup_reference_affiliation(address)
                if reference_address:
                    address = reference_address
                else:
                    address = self.reorder_institution_parts(address)
                    address = self.abbreviate_institution(address)
                    address = self.standardize_country(address)
                    address = re.sub(
                        r',\s*(\d{4,6})(?:-\d{4})?\s*,\s*(USA|Peoples R China|Germany|France|Thailand|Japan|South Korea|England|Turkiye|Russia|Brazil|India|Italy|Spain|Canada|Australia)$',
                        r', \1 \2',
                        address,
                    )
                address = address.rstrip('.')

            standardized_blocks.append({
                'author': str(block.get('author', '')).strip(),
                'raw_address': raw_address,
                'address': address,
                'emails': [email.strip().strip('.') for email in block.get('emails', []) if email.strip().strip('.')],
            })

        return standardized_blocks

    def _looks_like_institutional_address(self, address: str) -> bool:
        folded = self._ascii_fold(address).lower()
        markers = (
            'univ', 'university', 'hosp', 'hospital', 'inst', 'institute', 'company',
            'college', 'academy', 'school', 'center', 'centre', 'ctr', 'clinic', 'medical center'
        )
        return any(marker in folded for marker in markers)

    def _merge_correspondence_c1_lines(
        self,
        c1_lines: List[str],
        corresp_str: str,
        abbreviated_authors: List[str],
        full_names: List[str],
    ) -> List[str]:
        merged_lines = list(c1_lines or [])
        corresp_lines = self.build_correspondence_c1_lines(corresp_str, abbreviated_authors, full_names)
        if not corresp_lines:
            return merged_lines

        existing_entries = self._parse_c1_entries_from_lines(merged_lines, full_names=full_names)
        existing_line_keys = {self._normalize_lookup_key(line) for line in merged_lines if line.strip()}

        for corresp_line in corresp_lines:
            line_key = self._normalize_lookup_key(corresp_line)
            if not line_key or line_key in existing_line_keys:
                continue

            corresp_entries = self._parse_c1_entries_from_lines([corresp_line], full_names=full_names)
            if not corresp_entries:
                continue

            corresp_entry = corresp_entries[0]
            corresp_address = str(corresp_entry.get('address', '')).rstrip('.')
            corresp_author_keys = set(corresp_entry.get('author_keys', set()))
            if not corresp_address:
                continue

            should_add = True
            replace_index = None
            for existing_index, existing_entry in enumerate(existing_entries):
                existing_address = str(existing_entry.get('address', '')).rstrip('.')
                if not existing_address:
                    continue

                existing_author_keys = set(existing_entry.get('author_keys', set()))
                if corresp_author_keys and existing_author_keys and not (corresp_author_keys & existing_author_keys):
                    continue

                similarity = self._institution_similarity(corresp_address, existing_address)
                if similarity < 0.78:
                    continue

                corresp_is_detailed = self._is_detailed_affiliation_address(corresp_address)
                existing_is_detailed = self._is_detailed_affiliation_address(existing_address)
                if corresp_is_detailed and not existing_is_detailed:
                    if similarity >= 0.90:
                        replace_index = existing_index
                        should_add = False
                        break
                    continue

                should_add = False
                break

            if replace_index is not None:
                old_line_key = self._normalize_lookup_key(merged_lines[replace_index])
                if old_line_key:
                    existing_line_keys.discard(old_line_key)
                merged_lines[replace_index] = corresp_line
                existing_entries[replace_index] = corresp_entry
                existing_line_keys.add(line_key)
            elif should_add:
                merged_lines.append(corresp_line)
                existing_entries.extend(corresp_entries)
                existing_line_keys.add(line_key)

        return merged_lines

    def build_correspondence_c1_lines(self, corresp_str: str, abbreviated_authors: List[str], full_names: List[str]) -> List[str]:
        if not corresp_str:
            return []

        author_name_map = {}
        for index, abbreviated_author in enumerate(abbreviated_authors):
            full_name = full_names[index] if index < len(full_names) and full_names[index] else abbreviated_author
            author_name_map[abbreviated_author] = full_name

        lines = []
        seen = set()
        for block in self._build_correspondence_blocks(corresp_str, abbreviated_authors):
            author = str(block.get('author', '')).strip()
            raw_address = str(block.get('raw_address', '')).strip()
            mapped_addresses: List[str] = []
            if author and raw_address:
                for mapped_reprint_address in self._lookup_reference_reprint_addresses(author, raw_address):
                    mapped_reprint_address = mapped_reprint_address.rstrip('.')
                    if mapped_reprint_address and self._looks_like_institutional_address(mapped_reprint_address) and mapped_reprint_address not in mapped_addresses:
                        mapped_addresses.append(mapped_reprint_address)
            if not mapped_addresses:
                fallback_address = str(block.get('address', '')).rstrip('.')
                if fallback_address:
                    mapped_addresses = [fallback_address]
            if not author or not mapped_addresses:
                continue

            line_author = author_name_map.get(author, author)
            author_key = self._normalize_person_lookup_key(line_author)
            for address in mapped_addresses:
                dedup_key = (author_key, self._normalize_lookup_key(address))
                if dedup_key in seen:
                    continue

                seen.add(dedup_key)
                lines.append(f"[{line_author}] {address}.")

        return lines

    def convert_author_full_names(self, full_names_str: str, abbreviated_authors: List[str] = None) -> List[str]:
        """
        转换完整作者姓名。

        优先保留 Scopus 原始全名，只有在缺少全名时才谨慎回退到作者数据库，
        这样可以避免像 "Xiao, Y" → "Xiao, Yang" 这类同姓同首字母的误匹配。
        """
        authors = self._parse_scopus_full_names(full_names_str)
        total = max(len(authors), len(abbreviated_authors or []))
        converted = []

        for i in range(total):
            author_clean = ''
            if i < len(authors):
                author_clean = authors[i]
            abbreviated = abbreviated_authors[i] if abbreviated_authors and i < len(abbreviated_authors) else ''

            if author_clean:
                reference_author = self._lookup_reference_author(author_clean, abbreviated)
                if reference_author.get('AF'):
                    converted.append(reference_author['AF'])
                    continue

                if self.author_db and not self._has_explicit_given_name(author_clean):
                    preferred_full_name = self.author_db.get_preferred_full_name(author_clean)
                    if self._is_author_database_name_usable(author_clean, preferred_full_name):
                        converted.append(preferred_full_name)
                        continue

                converted.append(author_clean)
                continue

            if abbreviated:
                reference_author = self._lookup_reference_author(abbreviated_author=abbreviated)
                if reference_author.get('AF'):
                    converted.append(reference_author['AF'])
                    continue

                if self.author_db and self._should_use_author_database(abbreviated):
                    db_full_name = self.author_db.get_full_name(abbreviated)
                    if self._is_author_database_name_usable(abbreviated, db_full_name):
                        logger.debug(f"从数据库获取作者全名: {abbreviated} -> {db_full_name}")
                        converted.append(db_full_name)
                        continue
                converted.append(abbreviated)

        return converted

    def parse_reference(self, ref: str) -> Dict[str, str]:
        """
        解析Scopus参考文献格式

        Scopus格式：
        Neumann, William L., Autoimmune atrophic gastritis-pathogenesis, pathology and management,
        Nature Reviews Gastroenterology and Hepatology, 10, 9, pp. 529-541, (2013)

        拆解：
        parts[0] = "Neumann"
        parts[1] = "William L."
        parts[2] = "文章标题"
        parts[-4] = "期刊名" (通常)
        parts[-3] = "卷号"
        parts[-2] = "期号"
        parts[-1] = "pp. 页码" 或直接是年份

        需要提取：作者, 年份, 期刊, 卷号, 页码
        """
        result = {
            'author': '',
            'year': '',
            'journal': '',
            'volume': '',
            'page': '',
            'doi': ''
        }

        # 1. 提取年份（括号内）
        year_match = re.search(r'\((\d{4})\)', ref)
        if year_match:
            result['year'] = year_match.group(1)
            # 移除年份部分
            ref = ref[:year_match.start()].strip().rstrip(',')

        # 2. 按逗号分割
        parts = [p.strip() for p in ref.split(',')]

        if len(parts) == 0:
            return result

        # 3. 提取作者（前两个字段：姓 + 名）
        # Scopus格式: "Neumann, William L., ..."
        # parts[0] = "Neumann" (姓)
        # parts[1] = "William L." (名)
        if len(parts) >= 2:
            # 合并姓和名: "Neumann, William L."
            result['author'] = f"{parts[0]}, {parts[1]}"
        elif len(parts) >= 1:
            # 如果只有姓，也保存
            result['author'] = parts[0]

        # 4. 从后往前解析数字字段
        # 倒数第1个：可能是页码（pp. X-Y格式）
        if len(parts) >= 1:
            last_part = parts[-1]
            page_match = re.search(r'pp\.\s*(\d+)[\-]?', last_part)
            if page_match:
                result['page'] = page_match.group(1)

        # 倒数第2个：可能是期号（纯数字）
        # 倒数第3个：可能是卷号（纯数字）
        # 我们主要关心卷号
        for i in range(len(parts) - 1, max(0, len(parts) - 4), -1):
            part = parts[i]
            if re.match(r'^\d+$', part) and not result['volume']:
                result['volume'] = part
                break

        # 5. 期刊名：启发式查找
        # 策略：找到最后一个长度>15且包含大写字母的字段（在数字字段之前）
        # 注意：现在作者占用前2个字段（姓+名），标题是第3个字段
        journal_candidates = []
        for i, part in enumerate(parts):
            # 跳过作者名字段（前2个）和标题字段（第3个）
            if i <= 2:
                continue
            # 期刊名通常比较长，包含多个单词
            if len(part) > 15 and any(c.isupper() for c in part):
                journal_candidates.append(part)

        # 取最后一个候选（最接近数字字段的长字段）
        if journal_candidates:
            result['journal'] = journal_candidates[-1]

        return result

    def format_reference_wos(self, ref_data: Dict[str, str]) -> str:
        """
        格式化为WOS参考文献格式

        WOS格式: LastName Initials, Year, JOURNAL ABBREV, VVolume, PPage, DOI doi

        示例:
        - 输入: author="Neumann, William L."
        - 输出: "Neumann WL, 2013, NAT REV GASTRO HEPAT, V10, P529"

        关键点:
        1. 姓和首字母之间用空格分隔（无逗号）
        2. 提取所有首字母（不只是第一个）
        3. 首字母之间无空格（WL不是W L）
        """
        author_str = ref_data.get('author', '').strip()

        # 解析作者名：处理 "Lastname, Firstname Middlename" 格式
        if ',' in author_str:
            # Scopus格式: "Neumann, William L."
            parts = author_str.split(',', 1)
            lastname = parts[0].strip()
            firstname_part = parts[1].strip() if len(parts) > 1 else ''

            # 提取所有首字母
            initials = ''
            if firstname_part:
                # 分割名字部分: "William L." -> ["William", "L."]
                name_parts = firstname_part.split()
                for name in name_parts:
                    # 移除点号，取首字母
                    clean_name = name.replace('.', '').strip()
                    if clean_name:
                        initials += clean_name[0].upper()

            # WOS格式: "Lastname Initials" (无逗号)
            author_short = f"{lastname} {initials}" if initials else lastname
        else:
            # 如果没有逗号，直接使用原始格式
            author_short = author_str

        year = ref_data.get('year', '')
        journal = ref_data.get('journal', '')

        # 尝试缩写期刊名
        journal_abbrev = self.JOURNAL_ABBREV.get(journal, journal.upper())

        volume = ref_data.get('volume', '')
        page = ref_data.get('page', '')

        parts = [author_short, year, journal_abbrev]
        if volume:
            parts.append(f"V{volume}")
        if page:
            parts.append(f"P{page}")

        return ', '.join([p for p in parts if p])

    def convert_references(self, references_str: str) -> List[str]:
        """转换参考文献列表"""
        if not references_str:
            return []

        # 按分号分割各条参考文献
        refs = [r.strip() for r in references_str.split(';')]

        converted_refs = []
        for ref in refs:
            if ref:
                ref_data = self.parse_reference(ref)
                wos_ref = self.format_reference_wos(ref_data)
                if wos_ref:
                    converted_refs.append(wos_ref)

        return converted_refs

    def abbreviate_journal(self, journal_name: str) -> str:
        """
        期刊名缩写

        首先查找映射表，如果没有则使用规则生成
        """
        # 查找映射表
        if journal_name in self.JOURNAL_ABBREV:
            return self.JOURNAL_ABBREV[journal_name]

        # 使用规则生成缩写
        # 1. 移除常见词
        remove_words = ['the', 'of', 'and', 'in', 'for', 'on', '&']
        words = journal_name.split()

        # 2. 保留主要词汇并缩写
        abbrev_words = []
        for word in words:
            if word.lower() not in remove_words:
                if len(word) > 4:
                    # 长词取前几个字母
                    abbrev_words.append(word[:4].upper())
                else:
                    abbrev_words.append(word.upper())

        return ' '.join(abbrev_words)

    def parse_affiliations(self, affil_str: str, author_names: Optional[List[str]] = None,
                           affiliation_candidates: Optional[List[str]] = None) -> List[str]:
        """
        解析作者机构信息。

        优先使用 Scopus `Affiliations` 作为边界候选，再结合重复文献学到的作者-机构校准，
        尽量把 Scopus 的粗粒度机构块还原成更接近 WOS 的作者地址分组。
        """
        if not affil_str:
            return []

        author_groups = self._extract_author_affiliation_groups(
            affil_str,
            author_names=author_names,
            affiliation_candidates=affiliation_candidates,
        )
        raw_affiliation_counts = {}
        for _, raw_affiliations in author_groups:
            for raw_affiliation in raw_affiliations:
                raw_key = self._normalize_lookup_key(raw_affiliation)
                if raw_key:
                    raw_affiliation_counts[raw_key] = raw_affiliation_counts.get(raw_key, 0) + 1

        author_institutions = []

        for author_full, raw_affiliations in author_groups:
            author_local_affiliation_counts = {}
            for raw_affiliation in raw_affiliations:
                raw_key = self._normalize_lookup_key(raw_affiliation)
                if raw_key:
                    author_local_affiliation_counts[raw_key] = author_local_affiliation_counts.get(raw_key, 0) + 1

            for raw_affiliation in raw_affiliations:
                if not raw_affiliation.strip(' .,;'):
                    continue

                mapped_institutions = self._lookup_reference_author_affiliations(author_full, raw_affiliation)
                if not mapped_institutions:
                    reference_institution = self._lookup_reference_affiliation(raw_affiliation)
                    mapped_institutions = [reference_institution] if reference_institution else []

                if not mapped_institutions:
                    inst_reordered = self.reorder_institution_parts(raw_affiliation)
                    inst_short = self.abbreviate_institution(inst_reordered)
                    mapped_institutions = [self.standardize_country(inst_short)]

                raw_key = self._normalize_lookup_key(raw_affiliation)
                shared_author_count = raw_affiliation_counts.get(raw_key, 1)
                author_repeat_count = author_local_affiliation_counts.get(raw_key, 1)
                mapped_institutions = self._select_contextual_affiliation_matches(
                    raw_affiliation,
                    mapped_institutions,
                    shared_author_count=shared_author_count,
                    author_repeat_count=author_repeat_count,
                )

                for institution in mapped_institutions:
                    inst_standard = institution.rstrip('.')
                    if not inst_standard.strip(' .,;'):
                        continue
                    author_institutions.append((author_full, inst_standard))

        institution_to_authors = {}
        for author_full, institution in author_institutions:
            if institution not in institution_to_authors:
                institution_to_authors[institution] = []
            if author_full not in institution_to_authors[institution]:
                institution_to_authors[institution].append(author_full)

        converted = []
        for institution, authors in institution_to_authors.items():
            author_list = '; '.join(authors)
            converted.append(f"[{author_list}] {institution}.")

        return converted

    def standardize_country(self, institution: str) -> str:
        """
        标准化国家名称为WOS格式

        WOS使用的标准国家名称：
        - USA (不是United States)
        - England / Scotland / Wales / North Ireland (不是United Kingdom)
        - Peoples R China (不是China)
        - South Korea (不是Korea)
        - Turkiye (不是Turkey)

        Args:
            institution: 机构字符串（包含国家名）

        Returns:
            标准化后的机构字符串
        """
        # 国家名称映射表（Scopus → WOS标准）
        country_mapping = {
            'United States': 'USA',
            'United Kingdom': 'England',  # 默认England，除非明确是Scotland等
            'P. R. China': 'Peoples R China',
            'PR China': 'Peoples R China',
            'China': 'Peoples R China',
            'South Korea': 'South Korea',
            'Korea': 'South Korea',
            'Turkey': 'Turkiye',
            'Russia': 'Russia',
            'Iran': 'Iran',
            'Vietnam': 'Vietnam',
            'Czech Republic': 'Czech Republic',
            'Taiwan': 'Taiwan',
        }

        parts = [p.strip() for p in institution.split(',')]
        if not parts:
            return institution

        last_part = re.sub(r'\s+', ' ', parts[-1]).strip()

        for scopus_name, wos_name in sorted(country_mapping.items(), key=lambda item: len(item[0]), reverse=True):
            if last_part.lower() == scopus_name.lower():
                parts[-1] = wos_name
                break

        return ', '.join(parts)

    def _normalize_page_value(self, page_value: str) -> str:
        if not page_value:
            return ''

        page_value = page_value.strip()
        if re.fullmatch(r'[eE]\d+', page_value):
            return page_value.upper()
        return page_value

    def _calculate_page_count(self, page_start: str, page_end: str) -> str:
        """尽量从页码范围推导 PG，兼容 WOS 常见的字母页码。"""
        if not page_start or not page_end:
            return ''

        page_start = page_start.strip()
        page_end = page_end.strip()
        if not page_start or not page_end:
            return ''

        try:
            return str(int(page_end) - int(page_start) + 1)
        except Exception:
            pass

        prefixed_start = re.fullmatch(r'([A-Za-z]+)(\d+)', page_start)
        prefixed_end = re.fullmatch(r'([A-Za-z]+)(\d+)', page_end)
        if (
            prefixed_start
            and prefixed_end
            and prefixed_start.group(1).lower() == prefixed_end.group(1).lower()
        ):
            try:
                return str(int(prefixed_end.group(2)) - int(prefixed_start.group(2)) + 1)
            except Exception:
                return ''

        return ''

    def _normalize_issn(self, value: str) -> str:
        """规范化 ISSN 为 WOS 常见的 1234-5678 形式。"""
        if not value:
            return ''

        compact = re.sub(r'[^0-9Xx]', '', value).upper()
        if len(compact) == 8:
            return f"{compact[:4]}-{compact[4:]}"
        return value.strip()

    def _extract_issn_candidates(self, issn_str: str) -> List[str]:
        if not issn_str:
            return []

        candidates = []
        seen = set()
        for raw_candidate in re.split(r'[;,/|]+', issn_str):
            normalized = self._normalize_issn(raw_candidate)
            if not normalized:
                continue
            lookup_key = normalized.upper()
            if lookup_key not in seen:
                seen.add(lookup_key)
                candidates.append(normalized)

        return candidates

    def _select_issn_fields(self, source_title: str, issn_str: str) -> tuple[str, str]:
        """优先复用 WOS 已观测到的期刊 ISSN/EISSN，避免 Scopus 次序扰动。"""
        reference = self.reference_journal_map.get(self._normalize_lookup_key(source_title), {})
        reference_sn = self._normalize_issn(reference.get('SN', ''))
        reference_ei = self._normalize_issn(reference.get('EI', ''))
        if reference_sn or reference_ei:
            return reference_sn, reference_ei

        candidates = self._extract_issn_candidates(issn_str)
        if not candidates:
            return '', ''
        if len(candidates) == 1:
            return candidates[0], ''
        return candidates[0], candidates[1]

    def _is_independent_college_or_school(self, name: str, all_parts: List[str]) -> bool:
        """
        判断College/School是否为独立机构

        逻辑：
        1. 如果在已知独立机构列表中 → 独立机构
        2. 如果同一行已有University → 二级机构
        3. 如果College/School后面有专业名称（如Medical, Pharmacy）→ 独立机构
        4. 否则 → 二级机构（保守策略）

        Args:
            name: 当前部分的名称
            all_parts: 整个机构信息的所有部分

        Returns:
            bool: True表示是独立机构，False表示是二级单位
        """
        name_lower = name.lower()

        # 1. 检查是否在白名单中
        for independent in self.institution_config.get('independent_colleges', []):
            if independent.lower() in name_lower:
                return True

        for independent in self.institution_config.get('independent_schools', []):
            if independent.lower() in name_lower:
                return True

        # 2. 检查是否已有University（上下文判断）
        has_university = any('university' in p.lower() or 'università' in p.lower() or 'universit' in p.lower()
                            for p in all_parts if p != name)
        if has_university:
            return False  # 有University则College/School是二级机构

        # 3. 检查是否是专业学院（Medical, Pharmacy等）
        professional_indicators = [
            'medical', 'medicine', 'pharmacy', 'law', 'business',
            'engineering', 'public health', 'hygiene', 'economics',
            'tropical', 'veterinary', 'dental', 'nursing'
        ]

        if 'school' in name_lower:
            for indicator in professional_indicators:
                if indicator in name_lower:
                    return True  # School of Medicine这种通常是独立机构

        # 4. College of XX（学院名称）通常是二级机构，除非特别知名
        if 'college of' in name_lower:
            # "College of Pharmacy"可能是二级，但"Imperial College"是一级
            return False

        # 5. 如果College不带"of"且是完整名称，可能是独立学院
        if 'college' in name_lower and 'of' not in name_lower:
            # "Boston College", "King's College"这种
            words = name.split()
            if len(words) >= 2:  # 至少两个词
                return True

        # 默认：保守策略，当作二级机构
        return False

    def reorder_institution_parts(self, institution: str) -> str:
        """
        重新排序机构信息：一级机构在前，二级单位在后

        Scopus格式：Department of Internal Medicine, Università degli Studi di Pavia, Pavia, Italy
        WOS格式：Univ Pavia, Dept Internal Med, Pavia, Italy

        逻辑：
        1. 识别一级机构（University, Hospital, Institute, Foundation等）
        2. 识别二级单位（Department, Division, Unit, Laboratory等）
        3. 智能判断School/College的层级
        4. 识别地理信息（城市、国家）
        5. 重新排序：一级机构 → 二级单位 → 地理信息
        """
        # 按逗号分割各部分
        parts = [p.strip() for p in institution.split(',')]

        if len(parts) < 2:
            return institution

        # 一级机构关键词（明确的）
        primary_keywords = [
            'University', 'Università', 'Universität', 'Universit', 'Univ',
            'Hospital', 'Ospedale', 'Hosp',
            'Institute', 'Istituto', 'Institut',
            'Foundation', 'Fondazione', 'Fdn',
            'IRCCS', 'Policlinico', 'Clinic',
            'Center', 'Centre', 'Centro', 'Academy', 'Accademia'
        ]

        # 二级单位关键词（明确的）
        secondary_keywords = [
            'Department', 'Dipartimento', 'Dept',
            'Division', 'Divisione', 'Div',
            'Faculty', 'Facolta', 'Fac',
            'Unit', 'Unità',
            'Laboratory', 'Laboratorio', 'Lab',
            'Service', 'Servizio',
            'Section', 'Sezione'
        ]

        # 分类各部分
        primary_parts = []
        secondary_parts = []
        geo_parts = []

        # 假设最后1-2个部分是地理信息（城市、国家）
        if len(parts) >= 2:
            last_part = parts[-1]
            second_last = parts[-2] if len(parts) >= 2 else None

            # 检查是否是地理信息
            is_last_geo = not any(kw.lower() in last_part.lower() for kw in primary_keywords + secondary_keywords)
            is_last_geo = is_last_geo and 'college' not in last_part.lower() and 'school' not in last_part.lower()

            is_second_last_geo = (second_last and
                                 not any(kw.lower() in second_last.lower() for kw in primary_keywords + secondary_keywords) and
                                 'college' not in second_last.lower() and 'school' not in second_last.lower())

            if is_last_geo:
                geo_parts.append(last_part)
                parts = parts[:-1]

                if is_second_last_geo and len(parts) >= 1:
                    geo_parts.insert(0, parts[-1])
                    parts = parts[:-1]

        # 对剩余部分分类
        for part in parts:
            part_lower = part.lower()

            # 检查是否包含明确的二级单位关键词
            is_secondary = any(kw.lower() in part_lower for kw in secondary_keywords)
            if is_secondary:
                secondary_parts.append(part)
                continue

            # 检查是否包含一级机构关键词
            is_primary = any(kw.lower() in part_lower for kw in primary_keywords)

            # 特殊处理：School和College需要智能判断
            has_school = 'school' in part_lower
            has_college = 'college' in part_lower

            if has_school or has_college:
                # 使用智能判断
                if self._is_independent_college_or_school(part, parts):
                    primary_parts.append(part)
                else:
                    secondary_parts.append(part)
            elif is_primary:
                primary_parts.append(part)
            else:
                # 不确定的情况，放入一级机构（保守策略）
                primary_parts.append(part)

        # 重新组合：一级机构 + 二级单位 + 地理信息
        reordered = primary_parts + secondary_parts + geo_parts

        return ', '.join(reordered)

    def abbreviate_institution(self, institution: str) -> str:
        """
        缩写机构名称

        例如：
        "Department of Internal Medicine" -> "Dept Internal Med"
        "Fondazione IRCCS Policlinico San Matteo" -> "Fdn IRCCS Policlin San Matteo"
        "School of Medicine" -> "Sch Med"
        """
        # 使用配置文件中的缩写规则
        abbrev_map = self.institution_config['abbreviations']

        result = institution
        for full, abbrev in abbrev_map.items():
            result = re.sub(r'\b' + re.escape(full) + r'\b', abbrev, result, flags=re.IGNORECASE)

        # 移除常见介词和冠词（WOS风格）
        prepositions = ['of', 'for', 'the', 'in', 'at', 'on']
        for prep in prepositions:
            # 只移除单独的介词（前后有空格的），不移除单词中间的部分
            result = re.sub(r'\s+' + re.escape(prep) + r'\s+', ' ', result, flags=re.IGNORECASE)

        # 特殊处理 "and" -> "&"
        result = re.sub(r'\s+and\s+', ' & ', result, flags=re.IGNORECASE)

        # 清理多余空格
        result = re.sub(r'\s+', ' ', result).strip()
        result = re.sub(r',\s*,', ',', result)  # 移除连续逗号
        # 清理逗号前后多余空格
        result = re.sub(r'\s*,\s*', ', ', result)

        return result


    def _expand_c3_abbreviations(self, name: str) -> str:
        replacements = {
            'Univ': 'University',
            'Hosp': 'Hospital',
            'Inst': 'Institute',
            'Ctr': 'Center',
            'Sch': 'School',
            'Dept': 'Department',
            'Fac': 'Faculty',
            'Res': 'Research',
            'Innovat': 'Innovation',
            'Chem': 'Chemistry',
            'Phys': 'Physics',
            'Engn': 'Engineering',
            'Biomed': 'Biomedical',
            'Med': 'Medicine',
            'Mfg': 'Manufacturing',
            'Sci': 'Science',
            'Syst': 'Systems',
            'Hlth': 'Health',
            'Publ': 'Public',
            'Clin': 'Clinic',
        }
        expanded = name.strip().rstrip('.')
        for short, full in replacements.items():
            expanded = re.sub(rf'\b{re.escape(short)}\b', full, expanded)
        expanded = re.sub(r'\bCo\s+Ltd\b', 'Company, Limited', expanded, flags=re.IGNORECASE)
        expanded = re.sub(r'\bCorp\b', 'Corporation', expanded, flags=re.IGNORECASE)
        expanded = re.sub(r'\s+', ' ', expanded).strip(' ,;')

        if re.search(r"l['’]?oreal", expanded, flags=re.IGNORECASE):
            return "L'Oreal Group"
        if re.search(r'shiseido', expanded, flags=re.IGNORECASE) and 'Company' not in expanded:
            return 'Shiseido Company, Limited'

        klinikum_match = re.search(r'(?:Universitatsklinikum|Univ Klinikum|University Hospital)\s+(.+)$', self._ascii_fold(expanded), flags=re.IGNORECASE)
        if klinikum_match:
            return f"University of {klinikum_match.group(1).strip()}"

        if expanded.startswith('UAB '):
            return expanded.replace('UAB', 'University of Alabama Birmingham', 1)
        if expanded.startswith('University Alabama '):
            return expanded.replace('University Alabama', 'University of Alabama', 1)
        if expanded == 'UNESP':
            return 'Universidade Estadual Paulista'
        if expanded.startswith('UNESP '):
            return expanded.replace('UNESP', 'Universidade Estadual Paulista', 1)

        return expanded

    def _is_strong_c3_name(self, name: str) -> bool:
        folded = self._ascii_fold(name).lower()
        strong_markers = (
            'university', 'hospital', 'company', 'corporation', 'group', 'academy',
            'college', 'foundation', 'system', 'medical center'
        )
        return any(marker in folded for marker in strong_markers)

    def _is_university_like_c3_name(self, name: str) -> bool:
        folded = self._ascii_fold(name).lower()
        markers = (
            'university', 'academy', 'college', 'system', 'school', 'medical university'
        )
        return any(marker in folded for marker in markers)

    def _is_company_like_c3_name(self, name: str) -> bool:
        folded = self._ascii_fold(name).lower()
        markers = ('company', 'limited', 'corporation', 'group', 'biotech', "l'oreal", 'shiseido')
        return any(marker in folded for marker in markers)

    def _is_academic_c3_name(self, name: str) -> bool:
        folded = self._ascii_fold(name).lower()
        academic_markers = (
            'university', 'academy', 'college', 'institute', 'school', 'system',
            'medical center', 'faculty', 'department'
        )
        return any(marker in folded for marker in academic_markers)

    def _is_address_like_c3_name(self, name: str) -> bool:
        folded = self._ascii_fold(name).lower()
        if re.search(r'\b\d{2,}\b', folded):
            return True
        if re.match(r'^\d+\b', folded):
            return True
        return bool(re.search(r'\b(?:road|rd|avenue|ave|boulevard|blvd|lane|ln|rue|way|drive|dr|suite|ste|room|building|bldg)\b', folded))

    def _is_suppressible_c3_name(self, name: str) -> bool:
        """在同条记录已有更强学术组织时，压制明显噪声/外围机构。"""
        folded = self._ascii_fold(name).lower()
        if self._is_address_like_c3_name(name):
            return True
        if any(marker in folded for marker in ('company', 'limited', 'corporation', 'group')):
            return True
        if 'clinic' in folded or 'clin' in folded:
            return True
        if 'center' in folded or 'centre' in folded or 'ctr' in folded:
            return not self._is_academic_c3_name(name)
        if 'histo' in folded and not self._is_strong_c3_name(name):
            return True

        alpha_tokens = [token for token in re.split(r'[^a-z]+', folded) if token]
        if alpha_tokens and len(alpha_tokens) <= 2 and not self._is_strong_c3_name(name) and not self._is_academic_c3_name(name):
            return True
        return False

    def _should_suppress_fallback_c3_name(self, name: str, university_like_present: bool) -> bool:
        folded = self._ascii_fold(name).lower()
        if self._is_suppressible_c3_name(name):
            return True
        if not university_like_present:
            return False
        if self._is_university_like_c3_name(name):
            return False
        if any(marker in folded for marker in ('hospital', 'hosp', 'clinic', 'medical center', 'centre', 'center', 'ctr')):
            return True
        return False

    def _deduplicate_c3_names(self, candidate_items: List[Dict[str, str]]) -> List[str]:
        deduplicated = []
        seen = set()
        for candidate in candidate_items:
            name = candidate.get('name', '')
            if not name:
                continue
            lookup_key = self._normalize_lookup_key(name)
            if not lookup_key or lookup_key in seen:
                continue
            seen.add(lookup_key)
            deduplicated.append(name)
        return deduplicated

    def _augment_c3_names_with_supplements(self, names: List[str]) -> List[str]:
        if not names or not self.reference_c3_supplement_map:
            return names

        augmented_names = list(names)
        seen = {
            self._normalize_lookup_key(name)
            for name in augmented_names
            if self._normalize_lookup_key(name)
        }

        for name in list(augmented_names):
            name_key = self._normalize_lookup_key(name)
            if not name_key:
                continue

            for supplement in self.reference_c3_supplement_map.get(name_key, []):
                supplement_key = self._normalize_lookup_key(supplement)
                if not supplement_key or supplement_key in seen:
                    continue
                seen.add(supplement_key)
                augmented_names.append(supplement)

        return augmented_names

    def _collapse_redundant_c1_lines(
        self,
        c1_lines: List[str],
        full_names: Optional[List[str]] = None,
    ) -> List[str]:
        if len(c1_lines) <= 1:
            return c1_lines

        entries = self._parse_c1_entries_from_lines(c1_lines, full_names=full_names)
        kept_indices: List[int] = []

        for index, entry in enumerate(entries):
            current_address = str(entry.get('address', '')).rstrip('.')
            current_authors = set(entry.get('author_keys', set()))
            current_primary = self._normalize_lookup_key(self._select_primary_c3_name(current_address))
            current_tokens = set(self._institution_similarity_tokens(current_address))
            skip_current = False

            for kept_index in list(kept_indices):
                kept_entry = entries[kept_index]
                kept_address = str(kept_entry.get('address', '')).rstrip('.')
                kept_authors = set(kept_entry.get('author_keys', set()))
                kept_primary = self._normalize_lookup_key(self._select_primary_c3_name(kept_address))
                kept_tokens = set(self._institution_similarity_tokens(kept_address))

                if current_primary and kept_primary and current_primary != kept_primary:
                    continue

                similarity = self._institution_similarity(current_address, kept_address)
                if similarity < 0.82:
                    continue

                comparable_variants = (
                    current_tokens == kept_tokens
                    or current_tokens.issubset(kept_tokens)
                    or kept_tokens.issubset(current_tokens)
                )
                if not comparable_variants:
                    continue

                if current_authors and kept_authors and current_authors < kept_authors:
                    skip_current = True
                    break

                if current_authors and kept_authors and kept_authors < current_authors:
                    kept_indices.remove(kept_index)

            if not skip_current:
                kept_indices.append(index)

        return [c1_lines[index] for index in kept_indices]

    def _is_low_level_c3_name(self, name: str) -> bool:
        folded = self._ascii_fold(name).lower()
        low_level_markers = (
            'innovation center', 'research center', 'research unit', 'technology', 'technol',
            'section', 'unit', 'laboratory', 'lab', 'department', 'faculty', 'division',
            'service', 'platform', 'core', 'program', 'programme', 'clinic', 'clin', 'centre', 'center',
            'ctr', 'histo', 'campus'
        )
        return any(marker in folded for marker in low_level_markers) and not self._is_strong_c3_name(name)

    def _select_primary_c3_name(self, institution_text: str) -> str:
        if not institution_text:
            return ''

        if '] ' in institution_text:
            institution_text = institution_text.split('] ', 1)[1]

        parts = [part.strip().rstrip('.') for part in institution_text.split(',') if part.strip()]
        if len(parts) >= 3:
            organization_parts = parts[:-2]
        elif len(parts) >= 2:
            organization_parts = parts[:-1]
        else:
            organization_parts = parts

        if not organization_parts:
            organization_parts = parts[:1]

        institution_markers = (
            'univ', 'university', 'college', 'school', 'hospital', 'hosp', 'klinikum', 'clinic',
            'company', 'co ltd', 'co', 'corporation', 'corp', 'group', 'foundation', 'academy',
            'ministry', 'institute', 'inst', 'center', 'centre', 'ctr', 'dept', 'department',
            'division', 'faculty', 'uab', 'nanotechnology', 'loreal', "l'oreal", 'limited', 'biotech',
            'unesp'
        )
        filtered_parts = [part for part in organization_parts if any(marker in self._ascii_fold(part).lower() for marker in institution_markers)]
        if filtered_parts:
            organization_parts = filtered_parts

        def priority(part: str) -> tuple[int, int]:
            part_folded = self._ascii_fold(part).lower()
            if 'campus' in part_folded:
                return (7, -len(part))
            if 'unesp' in part_folded:
                return (0, -len(part))
            if 'univ' in part_folded or 'university' in part_folded:
                return (0, -len(part))
            if 'company' in part_folded or 'co ltd' in part_folded or 'corporation' in part_folded or 'corp' in part_folded or 'limited' in part_folded or 'group' in part_folded or 'biotech' in part_folded or "l'oreal" in part_folded or 'loreal' in part_folded:
                return (1, -len(part))
            if 'college' in part_folded or 'school' in part_folded:
                return (2, -len(part))
            if 'hospital' in part_folded or 'hosp' in part_folded or 'klinikum' in part_folded:
                return (3, -len(part))
            if 'foundation' in part_folded or 'academy' in part_folded or 'ministry' in part_folded:
                return (4, -len(part))
            if 'institute' in part_folded or 'inst' in part_folded:
                return (5, -len(part))
            if 'center' in part_folded or 'centre' in part_folded or 'ctr' in part_folded or 'clinic' in part_folded or 'lab' in part_folded:
                return (6, -len(part))
            if 'department' in part_folded or 'dept' in part_folded or 'division' in part_folded or 'faculty' in part_folded:
                return (9, -len(part))
            return (8, -len(part))

        best = min(organization_parts, key=priority)
        return self._expand_c3_abbreviations(best)

    def extract_primary_institutions_from_c1(self, c1_lines: List[str]) -> List[str]:
        if not c1_lines:
            return []

        primary_candidates = []
        for line in c1_lines:
            address = line
            if '] ' in address:
                address = address.split('] ', 1)[1]
            address = address.rstrip('.')

            mapped_names = self._lookup_reference_c3_names_for_address(address) or []
            if mapped_names:
                mapped_names = self._match_reference_c3_names_for_address(address, mapped_names)
                for mapped_name in mapped_names:
                    canonical_name = self._canonicalize_primary_institution_name(mapped_name)
                    if canonical_name and not self._is_address_like_c3_name(canonical_name):
                        primary_candidates.append({'name': canonical_name, 'source': 'reference'})
                if mapped_names:
                    continue

            primary_name = self._select_primary_c3_name(line)
            if primary_name:
                primary_name = self._canonicalize_primary_institution_name(primary_name)
                if primary_name and not self._is_address_like_c3_name(primary_name):
                    primary_candidates.append({'name': primary_name, 'source': 'fallback'})

        primary_institutions = [candidate['name'] for candidate in primary_candidates if candidate.get('name')]
        strong_present = any(self._is_strong_c3_name(name) for name in primary_institutions)
        university_like_present = any(self._is_university_like_c3_name(name) for name in primary_institutions)
        academic_present = any(
            candidate.get('source') == 'reference' or self._is_academic_c3_name(candidate.get('name', ''))
            for candidate in primary_candidates
        )
        wos_like_present = any(
            candidate.get('source') == 'reference' or self._best_reference_c3_score(candidate.get('name', '')) >= 0.74
            for candidate in primary_candidates
        )

        filtered_candidates = []
        for candidate in primary_candidates:
            name = candidate.get('name', '')
            candidate_score = self._best_reference_c3_score(name)
            decision_stats = self._get_reference_c3_decision_stats(name)
            positive_count = decision_stats.get('positive', 0)
            negative_count = decision_stats.get('negative', 0)

            if self._is_address_like_c3_name(name):
                continue
            if university_like_present and self._is_company_like_c3_name(name):
                continue
            if strong_present and candidate.get('source') != 'reference' and self._is_low_level_c3_name(name):
                continue
            if academic_present and candidate.get('source') != 'reference' and self._should_suppress_fallback_c3_name(name, university_like_present):
                continue
            if (
                wos_like_present
                and candidate.get('source') != 'reference'
                and positive_count == 0
                and negative_count >= 1
                and candidate_score < 0.62
            ):
                continue
            if (
                wos_like_present
                and candidate.get('source') != 'reference'
                and negative_count >= max(2, positive_count + 2)
                and candidate_score < 0.68
            ):
                continue
            if (
                wos_like_present
                and candidate.get('source') != 'reference'
                and candidate_score < 0.62
                and not self._is_university_like_c3_name(name)
            ):
                continue
            filtered_candidates.append(candidate)

        return self._augment_c3_names_with_supplements(self._deduplicate_c3_names(filtered_candidates))

    def extract_primary_institutions(self, affil_str: str) -> List[str]:
        """
        从Scopus机构信息中提取一级机构（用于C3字段）

        Scopus格式：Department of Surgery, Chiba Aoba Municipal Hospital, Chiba, Japan
        目标：提取 "Chiba Aoba Municipal Hospital"

        策略：
        1. 识别一级机构关键词（University, Hospital, Institute, College等）
        2. 智能判断College/School是否为一级机构
        3. 提取包含这些关键词的机构名称
        4. 去除部门名称（Department, Division等）
        5. 去重并标准化
        """
        if not affil_str:
            return []

        # 一级机构的关键词（明确的）
        primary_keywords = [
            'University', 'Università', 'Universität', 'Universi',  # 大学
            'Hospital', 'Ospedale', 'Clinic', 'Medical Center',     # 医院
            'Institute', 'Istituto', 'Institut',                    # 研究所
            'Academy', 'Accademia',                                 # 科学院
            'Foundation', 'Fondazione', 'IRCCS',                    # 基金会/研究机构
            'Corporation', 'Company', 'Ltd',                        # 企业
            'Ministry', 'Government',                               # 政府机构
        ]

        # 二级单位关键词（需要过滤掉）
        # 匹配策略：
        # 1. "xxx of" 形式：精确匹配开头
        # 2. 单词形式（dept, faculty等）：匹配任意位置或开头
        secondary_keywords_strict = [
            # 严格匹配开头的模式（"of"形式）
            'department of', 'dept of', 'dept.',
            'division of', 'div of',
            'section of', 'unit of',
            'laboratory of', 'lab of',
            'center for', 'centre for',
            'school of', 'faculty of', 'college of',
            'group of', 'branch of',
        ]

        # 宽松匹配的二级单位标识（匹配任意位置）
        secondary_indicators = [
            'dept ', ' dept', 'dept.', 'dept,',  # dept作为单词
            'department',  # department作为单词
            'faculty ',  # faculty作为单词（注意空格，避免匹配Faculty of XX）
            'facoltà', 'faculdade', 'fac ',  # 意大利语/葡萄牙语/西班牙语学院
            'graduate school',  # 研究生院
            'u.o.', 'uo ', 'uoc ',  # 意大利语部门缩写（Unità Operativa）
            ' unit', ' group', ' programme', ' program',  # 单元、小组、项目
            ' branch', ' ward', ' office',  # 分支、病区、办公室
            'oncologia ', 'anatomia ', 'epidemiologia ',  # 意大利语学科部门
            'departamento de', 'dipartimento di',  # 西班牙语/意大利语部门
            'sch ', ' sch',  # school的缩写（如"sch pharm", "tongji sch"）
            'school med', 'school pharm', 'school engn',  # 学院+专业缩写组合
            'faculty med', 'faculty pharm', 'faculty phys',  # 学院+专业缩写组合
            'college engn',  # 学院+专业缩写组合
            ' med iii', ' med ii', ' med i',  # 内科三科、二科、一科（部门编号）
            'internal med',  # 内科（部门）
        ]

        # 地址信息关键词
        address_indicators = [
            'ave', 'avenue', 'blvd', 'boulevard', 'rd', 'road',
            'st ', 'street', 'dr ', 'drive', 'lane', 'way'
        ]

        # 单个学科词（没有机构关键词时应该过滤）
        discipline_only_patterns = [
            'microbiology', 'immunology', 'oncology', 'pathology',
            'pharmacology', 'physiology', 'biochemistry', 'biology',
            'chemistry', 'physics', 'engineering', 'development',
            'pulmonary', 'cardiology', 'neurology', 'dermatology',
            'venereology', 'allergology', 'translational',
            'biotechnological', 'pharmaceutical', 'biomedical',
            'therapeutics', 'genomics', 'immunotherapy', 'biophysical',
            'thermodynamics', 'interface', 'medicinal', 'regulatory',
            'zoology', 'transplantation', 'infectious diseases',
            'pneumology', 'surgical', 'experimental', 'clinical',
            ' sci', ' biol', ' chem',  # 缩写形式（带空格避免误匹配）
        ]

        # 设施类关键词（应该被过滤）
        facility_indicators = [
            'facility', 'core', 'platform', 'service',
        ]

        # 按分号分割每个作者的机构
        author_affils = [a.strip() for a in affil_str.split(';')]

        primary_institutions = []
        seen_primary_institutions = set()

        def add_primary_institution(clean_name: str):
            if not clean_name:
                return
            key = clean_name.lower()
            if key not in seen_primary_institutions:
                seen_primary_institutions.add(key)
                primary_institutions.append(clean_name)

        for affil in author_affils:
            if not affil:
                continue

            # 跳过作者名（第一个逗号前）
            if ',' in affil:
                parts = affil.split(',')
                # 第一个部分是作者名，跳过
                institution_parts = parts[1:]
            else:
                institution_parts = [affil]

            # 遍历每个机构部分
            for part in institution_parts:
                part = part.strip()
                part_lower = part.lower()

                # === 第0层：检查白名单（优先级最高）===

                # 首先检查是否在independent_schools或independent_colleges白名单中
                # 如果在白名单中，直接认定为一级机构，跳过所有过滤
                is_whitelisted = False
                for independent in self.institution_config.get('independent_schools', []):
                    if independent.lower() in part_lower:
                        is_whitelisted = True
                        break

                if not is_whitelisted:
                    for independent in self.institution_config.get('independent_colleges', []):
                        if independent.lower() in part_lower:
                            is_whitelisted = True
                            break

                if is_whitelisted:
                    # 在白名单中，直接添加为一级机构
                    clean_name = self.clean_institution_name(part)
                    if clean_name:
                        add_primary_institution(clean_name)
                    continue  # 跳过后续所有过滤

                # === 第1层过滤：明显无效的内容 ===

                # 跳过过短的内容（城市、国家、缩写等）
                if len(part) < 10:
                    continue

                # 跳过只有标点的内容
                if part.strip('., ') == '':
                    continue

                # 跳过常见的无意义词
                if part_lower in ['organization', 'development', 'technol']:
                    continue

                # 跳过只有国家/城市的（以句点结尾的短字符串）
                if part.endswith('.') and len(part) < 20:
                    continue

                # === 第2层过滤：地址信息 ===

                # 检查是否包含街道地址
                is_address = False
                for addr_ind in address_indicators:
                    if addr_ind in part_lower:
                        is_address = True
                        break

                # 检查是否是纯数字开头的地址（如"2103 cornell rd"）
                if part[0].isdigit():
                    is_address = True

                if is_address:
                    continue

                # === 第3层过滤：二级单位（严格匹配开头）===

                is_secondary = False
                for sec_keyword in secondary_keywords_strict:
                    if part_lower.startswith(sec_keyword):
                        is_secondary = True
                        break

                if is_secondary:
                    continue

                # === 第4层过滤：二级单位（宽松匹配任意位置）===

                for sec_ind in secondary_indicators:
                    if sec_ind in part_lower:
                        is_secondary = True
                        break

                if is_secondary:
                    continue

                # === 第5层过滤：不完整的附属医院 ===

                # "the xxx affiliated hosp"如果没有大学名称，则过滤
                if 'affiliated' in part_lower and 'hosp' in part_lower:
                    has_university = any(kw.lower() in part_lower for kw in ['university', 'univ', 'università'])
                    if not has_university:
                        continue  # 不完整的附属医院

                # === 第6层过滤：设施类（facility/core/service等）===

                is_facility = False
                for fac_ind in facility_indicators:
                    if fac_ind in part_lower:
                        # facility等通常是支持性设施，不是一级机构
                        is_facility = True
                        break

                if is_facility:
                    continue

                # === 第7层过滤：单个学科词 ===

                # 检查是否只包含学科词，没有机构关键词
                is_discipline_only = False
                for disc in discipline_only_patterns:
                    if disc in part_lower:
                        # 如果包含学科词，检查是否也包含机构关键词
                        has_institution = any(kw.lower() in part_lower for kw in primary_keywords)
                        if not has_institution:
                            is_discipline_only = True
                            break

                if is_discipline_only:
                    continue

                # === 第8层：识别一级机构 ===

                # 检查是否包含一级机构关键词
                is_primary = any(kw.lower() in part_lower for kw in primary_keywords)

                # 特殊处理：College和School需要智能判断
                has_college = 'college' in part_lower
                has_school = 'school' in part_lower

                if has_college or has_school:
                    # 使用智能判断方法
                    if self._is_independent_college_or_school(part, institution_parts):
                        is_primary = True
                    else:
                        is_primary = False  # 是二级单位，跳过

                if is_primary:
                    # 清理机构名称
                    clean_name = self.clean_institution_name(part)
                    if clean_name:
                        add_primary_institution(clean_name)

        return primary_institutions

    def clean_institution_name(self, name: str) -> str:
        """
        清理机构名称，用于C3字段

        例如：
        "Università degli Studi di Pavia" -> "University of Pavia"
        "Fondazione IRCCS Policlinico San Matteo" -> "IRCCS Fondazione Policlinico San Matteo"
        "Sun Yat-Sen Univ Canc Ctr" -> "Sun Yat Sen University"
        """
        # 移除多余空格
        name = re.sub(r'\s+', ' ', name).strip()

        # 移除尾部的部门/中心后缀（这些不应该出现在C3字段中）
        department_suffixes = [
            r'\s+Canc(?:er)?\s+Ctr$',  # Cancer Center
            r'\s+Canc(?:er)?\s+Cent(?:er|re)$',
            r'\s+Med(?:ical)?\s+Cent(?:er|re)$',  # Medical Center (但保留前面的机构名)
            r'\s+Res(?:earch)?\s+Cent(?:er|re)$',
            r'\s+Dept\.?$',
            r'\s+Dept\s+\w+$',  # Dept Med, Dept Oncol等
            r',?\s+Ltd\.?$',  # Ltd., Ltd
            r',?\s+Inc\.?$',  # Inc., Inc
            r',?\s+Co\.?$',   # Co., Co
        ]

        for suffix_pattern in department_suffixes:
            name = re.sub(suffix_pattern, '', name, flags=re.IGNORECASE)

        # 标准化常见表达
        replacements = {
            'Università degli Studi di': 'University of',
            'Università di': 'University of',
            'Università': 'University',
            'Ospedale': 'Hospital',
            'Istituto': 'Institute',
            'Fondazione IRCCS': 'IRCCS Fondazione',
        }

        for old, new in replacements.items():
            name = re.sub(r'\b' + re.escape(old) + r'\b', new, name, flags=re.IGNORECASE)

        # 标准化人名中的连字符（Sun Yat-Sen -> Sun Yat Sen）
        # 但保留复合词中的连字符（如Clermont-Ferrand）
        # 策略：如果连字符两边都是大写字母开头的短词（2-5字母），则替换为空格
        name = re.sub(r'\b([A-Z][a-z]{1,4})-([A-Z][a-z]{1,4})\b', r'\1 \2', name)

        # 清理多余空格
        name = re.sub(r'\s+', ' ', name).strip()

        # 最终检查：如果清理后太短（< 5字符），可能是无效的
        if len(name) < 5:
            return ''

        return name

    def convert_record(self, scopus_record: Dict) -> str:
        """
        将单条Scopus记录转换为WOS格式

        Args:
            scopus_record: Scopus CSV的一行记录（字典）

        Returns:
            WOS格式的文本
        """
        wos_lines = []

        # PT - Publication Type (固定为 J = Journal)
        wos_lines.append("PT J")

        # 先准备作者信息，再统一生成更接近 WOS 的 AU / AF
        scopus_authors_str = scopus_record.get('Authors', '')
        fallback_abbreviated_authors = self.convert_authors(scopus_authors_str)

        scopus_full_names_str = scopus_record.get('Author full names', '')
        full_names = self.convert_author_full_names(scopus_full_names_str, fallback_abbreviated_authors)

        abbreviated_authors = []
        total_authors = max(len(full_names), len(fallback_abbreviated_authors))
        for index in range(total_authors):
            full_name = full_names[index] if index < len(full_names) else ''
            fallback_abbrev = fallback_abbreviated_authors[index] if index < len(fallback_abbreviated_authors) else ''
            abbreviated_authors.append(self._format_author_abbreviation(full_name, fallback_abbrev))

        if abbreviated_authors:
            wos_lines.append(f"AU {abbreviated_authors[0]}")
            for author in abbreviated_authors[1:]:
                wos_lines.append(f"   {author}")

        if full_names:
            wos_lines.append(f"AF {full_names[0]}")
            for name in full_names[1:]:
                wos_lines.append(f"   {name}")

        # TI - Title
        title = scopus_record.get('Title', '')
        if title:
            # 标题在约80字符换行（WOS格式）
            wos_lines.append(self.format_multiline_field('TI', title, max_width=80))

        # SO - Source (期刊名，全大写)
        source = scopus_record.get('Source title', '')
        if source:
            wos_lines.append(f"SO {self._format_source_title(source)}")

        # LA - Language
        language = scopus_record.get('Language of Original Document', '')
        if language:
            wos_lines.append(f"LA {language}")

        # DT - Document Type
        doc_type = scopus_record.get('Document Type', 'Article')
        wos_lines.append(f"DT {doc_type}")

        # DE - Author Keywords
        keywords = scopus_record.get('Author Keywords', '')
        if keywords:
            # WOS格式修正：vitamin B12 -> vitamin B-12
            keywords = keywords.replace('vitamin B12', 'vitamin B-12')
            # DE字段在约80字符换行（WOS格式）
            wos_lines.append(self.format_multiline_field('DE', keywords, max_width=80))

        # ID - Keywords Plus
        # Scopus Index Keywords 与 WOS Keywords Plus 语义不同；
        # 直接写入 ID 会污染后续基于 WOS 字段语义的关键词分析，因此这里宁缺勿滥。

        # AB - Abstract
        abstract = scopus_record.get('Abstract', '')
        if abstract:
            # 修复Scopus摘要格式：在章节标题后添加空格
            # INTRODUCTION:The -> INTRODUCTION: The
            # METHODS:Prospective -> METHODS: Prospective
            abstract_fixed = re.sub(r'([A-Z]+):([A-Z])', r'\1: \2', abstract)

            # WOS格式细节修复：
            # 1. "F: M ratio" -> "F:M ratio"（比例中的冒号不要空格）
            abstract_fixed = re.sub(r'([A-Z]): ([A-Z]) ratio', r'\1:\2 ratio', abstract_fixed)
            # 2. "±" -> "+/-"（特殊符号转换）
            abstract_fixed = abstract_fixed.replace('±', '+/-')

            # AB字段必须单行，不换行（WOS格式规范）
            wos_lines.append(f"AB {abstract_fixed}")

        # C1 - Author Addresses
        base_affils = self.parse_affiliations(
            scopus_record.get('Authors with affiliations', ''),
            author_names=full_names,
            affiliation_candidates=self._split_affiliation_candidates(scopus_record.get('Affiliations', '')),
        )

        corresp = scopus_record.get('Correspondence Address', '')
        affils = self._merge_correspondence_c1_lines(base_affils, corresp, abbreviated_authors, full_names)
        affils = self._collapse_redundant_c1_lines(affils, full_names=full_names)

        if affils:
            wos_lines.append(f"C1 {affils[0]}")
            for affil in affils[1:]:
                wos_lines.append(f"   {affil}")

        # C3 - Organization Enhanced
        # 直接基于最终 C1 推导，避免 C1/C3 语义分裂，并借助校准映射尽量贴近 WOS 的组织增强风格。
        primary_insts = self.extract_primary_institutions_from_c1(affils)
        primary_insts = self._recover_c3_companion_names(primary_insts, scopus_record)
        if primary_insts:
            c3_line = '; '.join(primary_insts)
            wos_lines.append(self.format_multiline_field('C3', c3_line, max_width=80, separator=';'))

        # RP / EM - 通讯作者与邮箱
        rp_text, em_text = self.format_reprint_address(
            corresp,
            abbreviated_authors,
            full_names=full_names,
            c1_lines=affils,
        )
        if rp_text:
            wos_lines.append(f"RP {rp_text}")
        if em_text:
            wos_lines.append(f"EM {em_text}")

        # CR - Cited References
        references = self.convert_references(scopus_record.get('References', ''))
        if references:
            wos_lines.append(f"CR {references[0]}")
            for ref in references[1:]:
                wos_lines.append(f"   {ref}")

        # NR - Number of References
        if references:
            wos_lines.append(f"NR {len(references)}")

        # TC - Times Cited
        cited_by = scopus_record.get('Cited by', '0')
        wos_lines.append(f"TC {cited_by}")

        # Z9 - Total Times Cited (设为与TC相同)
        wos_lines.append(f"Z9 {cited_by}")

        # U1, U2 - Usage Count (Scopus没有，设为0)
        wos_lines.append("U1 0")
        wos_lines.append("U2 0")

        # PU - Publisher
        publisher = scopus_record.get('Publisher', '')
        if publisher:
            wos_lines.append(f"PU {publisher}")

        # SN / EI - ISSN / EISSN
        issn = scopus_record.get('ISSN', '')
        sn_value, ei_value = self._select_issn_fields(source, issn)
        if sn_value:
            wos_lines.append(f"SN {sn_value}")
        if ei_value:
            wos_lines.append(f"EI {ei_value}")

        # J9 / JI - 期刊缩写
        abbrev_title = scopus_record.get('Abbreviated Source Title', '')
        j9_title = self._format_j9_abbreviation(source, abbrev_title)
        if j9_title:
            wos_lines.append(f"J9 {j9_title}")

        ji_title = self._format_ji_abbreviation(source, abbrev_title)
        if ji_title:
            wos_lines.append(f"JI {ji_title}")

        # PY - Publication Year
        year = scopus_record.get('Year', '')
        if year:
            wos_lines.append(f"PY {year}")

        # VL - Volume
        volume = scopus_record.get('Volume', '')
        if volume:
            wos_lines.append(f"VL {volume}")

        # IS - Issue
        issue = scopus_record.get('Issue', '')
        if issue:
            wos_lines.append(f"IS {issue}")

        # AR - Article Number
        art_no = scopus_record.get('Art. No.', '')
        if art_no:
            wos_lines.append(f"AR {art_no}")

        # BP - Beginning Page
        page_start = self._normalize_page_value(scopus_record.get('Page start', ''))
        if page_start:
            wos_lines.append(f"BP {page_start}")

        # EP - Ending Page
        page_end = self._normalize_page_value(scopus_record.get('Page end', ''))
        if page_end:
            wos_lines.append(f"EP {page_end}")

        # PG - Page Count
        page_count = self._calculate_page_count(page_start, page_end)
        if page_count:
            wos_lines.append(f"PG {page_count}")

        # DI - DOI
        doi = scopus_record.get('DOI', '')
        if doi:
            wos_lines.append(f"DI {doi}")

        # WC, WE, SC - Web of Science Categories
        # 注：这些字段需要根据期刊手动分类，这里设置为通用值
        # 用户可以根据需要在文献计量工具中重新分类
        wos_lines.append("WE Scopus")

        # UT - Unique Article Identifier (使用Scopus EID)
        eid = scopus_record.get('EID', '')
        if eid:
            wos_lines.append(f"UT SCOPUS:{eid}")

        # PM - PubMed ID
        pmid = scopus_record.get('PubMed ID', '')
        if pmid:
            wos_lines.append(f"PM {pmid}")

        # DA - Date of Export
        today = datetime.now().strftime('%Y-%m-%d')
        wos_lines.append(f"DA {today}")

        # ER - End of Record
        wos_lines.append("ER")

        return '\n'.join(wos_lines)

    def convert(self):
        """
        执行转换

        Raises:
            IOError: 写入文件失败
        """
        logger.info("="*60)
        logger.info("开始转换 Scopus CSV → WOS 纯文本格式")
        logger.info("="*60)

        # 读取Scopus CSV
        self.records = self.read_scopus_csv()

        if not self.records:
            logger.warning("没有找到任何记录，终止转换")
            return

        # 以整份 WOS 语料建立通用校准映射（期刊 / 作者），而不是逐条借用重复记录字段
        self._build_reference_calibration(self.records)

        # 转换每条记录
        wos_content = []

        # WOS文件头（无空行分隔）
        wos_content.append("FN Clarivate Analytics Web of Science")
        wos_content.append("VR 1.0")

        total = len(self.records)
        logger.info(f"开始转换 {total} 条记录...")

        # 转换每条记录
        for i, record in enumerate(self.records, 1):
            title = record.get('Title', 'N/A')
            title_short = title[:50] + "..." if len(title) > 50 else title

            # 进度显示（每10%或每100条显示一次）
            if i % max(1, total // 10) == 0 or i % 100 == 0 or i == total:
                progress = (i / total) * 100
                logger.info(f"进度: {progress:.1f}% ({i}/{total}) - {title_short}")

            try:
                wos_record = self.convert_record(record)
                # 在记录前添加空行（除了第一条记录）
                if i > 1:
                    wos_content.append("")  # 空行
                wos_content.append(wos_record)
            except Exception as e:
                logger.error(f"转换第 {i} 条记录时出错: {e}")
                logger.error(f"问题记录: {title_short}")
                # 继续处理下一条

        # WOS文件尾（前面加空行）
        wos_content.append("")  # 空行
        wos_content.append("EF")

        # 写入文件（用单个换行符连接，包含UTF-8 BOM，与WOS格式完全一致）
        try:
            with open(self.output_file, 'w', encoding='utf-8-sig') as f:
                f.write('\n'.join(wos_content))
            logger.info("="*60)
            logger.info("转换完成！")
            logger.info(f"输出文件: {self.output_file}")
            logger.info(f"共转换 {len(self.records)} 条记录")
            logger.info("="*60)
        except IOError as e:
            logger.error(f"写入文件失败: {e}")
            raise
        except Exception as e:
            logger.error(f"写入文件时发生未知错误: {e}")
            raise


def main():
    """主函数"""
    import argparse

    # 命令行参数解析
    parser = argparse.ArgumentParser(
        description='Scopus CSV to WOS Plain Text Converter',
        epilog='示例: python3 scopus_to_wos_converter.py scopus.csv output.txt'
    )
    parser.add_argument('input_file', nargs='?', default='scopus.csv',
                       help='Scopus CSV文件路径（默认: scopus.csv）')
    parser.add_argument('output_file', nargs='?', default='scopus_converted_to_wos.txt',
                       help='输出WOS文件路径（默认: scopus_converted_to_wos.txt）')
    parser.add_argument('--config-dir', default='config',
                       help='配置文件目录（默认: config）')
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                       default='INFO', help='日志级别（默认: INFO）')

    args = parser.parse_args()

    # 设置日志级别
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    logger.info("=" * 60)
    logger.info("Scopus to WOS Converter v3.1")
    logger.info("=" * 60)
    logger.info(f"输入文件: {args.input_file}")
    logger.info(f"输出文件: {args.output_file}")
    logger.info(f"配置目录: {args.config_dir}")

    try:
        # 执行转换
        converter = ScopusToWosConverter(
            args.input_file,
            args.output_file,
            args.config_dir
        )
        converter.convert()

        logger.info("")
        logger.info("转换完成！现在可以将输出文件导入文献计量学分析工具。")
        logger.info("=" * 60)
        return 0

    except FileNotFoundError as e:
        logger.error(f"文件错误: {e}")
        return 1
    except ValueError as e:
        logger.error(f"数据错误: {e}")
        return 1
    except Exception as e:
        logger.error(f"发生未知错误: {e}")
        logger.exception("详细错误信息:")
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    main()
