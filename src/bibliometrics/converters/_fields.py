#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WOS 输出字段的规范化：国家名、机构名、页码与 ISSN。

WOS 对这几个字段有自己的写法约定（``USA`` 而非 ``United States``、
``Peoples R China`` 而非 ``China``、ISSN 带连字符、PG 由页码范围推导），
Scopus 导出则各写各的。这里负责把 Scopus 侧改写成 WOS 约定。

从 ``converters/scopus.py`` 中拆出，行为与拆分前逐字节一致。
"""

from __future__ import annotations

import re
from typing import List

# 国家名称映射表（Scopus → WOS标准）
_COUNTRY_MAPPING = {
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


def standardize_country(institution: str) -> str:
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
    parts = [p.strip() for p in institution.split(',')]
    if not parts:
        return institution

    last_part = re.sub(r'\s+', ' ', parts[-1]).strip()

    for scopus_name, wos_name in sorted(_COUNTRY_MAPPING.items(),
                                        key=lambda item: len(item[0]), reverse=True):
        if last_part.lower() == scopus_name.lower():
            parts[-1] = wos_name
            break

    return ', '.join(parts)


def clean_institution_name(name: str) -> str:
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


def normalize_page_value(page_value: str) -> str:
    """电子页码（e123）统一成大写 E 前缀，其余原样。"""
    if not page_value:
        return ''

    page_value = page_value.strip()
    if re.fullmatch(r'[eE]\d+', page_value):
        return page_value.upper()
    return page_value


def calculate_page_count(page_start: str, page_end: str) -> str:
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


def normalize_issn(value: str) -> str:
    """规范化 ISSN 为 WOS 常见的 1234-5678 形式。"""
    if not value:
        return ''

    compact = re.sub(r'[^0-9Xx]', '', value).upper()
    if len(compact) == 8:
        return f"{compact[:4]}-{compact[4:]}"
    return value.strip()


def extract_issn_candidates(issn_str: str) -> List[str]:
    """一个 ISSN 字段里可能并列多个号，拆开并去重（保持出现顺序）。"""
    if not issn_str:
        return []

    candidates = []
    seen = set()
    for raw_candidate in re.split(r'[;,/|]+', issn_str):
        normalized = normalize_issn(raw_candidate)
        if not normalized:
            continue
        lookup_key = normalized.upper()
        if lookup_key not in seen:
            seen.add(lookup_key)
            candidates.append(normalized)

    return candidates
