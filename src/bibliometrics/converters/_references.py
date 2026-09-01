#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Scopus 参考文献（CR 字段）的解析与 WOS 格式化。

Scopus 导出的参考文献是一行自由文本，字段间只用逗号分隔且没有稳定的位置约定，
因此这里的解析全部是启发式的：先摘出括号内的年份，再从尾部往前找卷号与页码，
最后按"长度 + 含大写字母"猜期刊名。

从 ``converters/scopus.py`` 中拆出，行为与拆分前逐字节一致。
"""

from __future__ import annotations

import re
from typing import Dict, List, Mapping


def parse_reference(ref: str) -> Dict[str, str]:
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


def format_reference_wos(ref_data: Dict[str, str], journal_abbrev_map: Mapping[str, str]) -> str:
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
    journal_abbrev = journal_abbrev_map.get(journal, journal.upper())

    volume = ref_data.get('volume', '')
    page = ref_data.get('page', '')

    parts = [author_short, year, journal_abbrev]
    if volume:
        parts.append(f"V{volume}")
    if page:
        parts.append(f"P{page}")

    return ', '.join([p for p in parts if p])


def convert_references(references_str: str, journal_abbrev_map: Mapping[str, str]) -> List[str]:
    """转换参考文献列表"""
    if not references_str:
        return []

    # 按分号分割各条参考文献
    refs = [r.strip() for r in references_str.split(';')]

    converted_refs = []
    for ref in refs:
        if ref:
            ref_data = parse_reference(ref)
            wos_ref = format_reference_wos(ref_data, journal_abbrev_map)
            if wos_ref:
                converted_refs.append(wos_ref)

    return converted_refs
