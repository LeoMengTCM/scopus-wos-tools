#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C3（机构组织）名称的判定、分类与规范化。

WOS 的 ``C3`` 字段收录的是"组织级"机构名（大学、医院、公司、科学院），而 Scopus 的
affiliation 是逐层地址串。这里的函数负责在两者之间做判断：一个候选名到底是组织级
实体、下级科室，还是纯粹的街道地址；两个名字指的是不是同一个组织，还是父子层级
关系（"某大学" vs "某大学附属医院"）。

判定全部基于关键词标记 + 词元重叠，不依赖外部机构权威库——这是项目刻意的设计边界。

从 ``converters/scopus.py`` 中拆出，行为与拆分前逐字节一致。
"""

from __future__ import annotations

import re
from typing import Dict, List, Set

from ._normalization import ascii_fold, institution_similarity, normalize_lookup_key


def expand_c3_abbreviations(name: str) -> str:
    """把 WOS 风格缩写展开为全称，并归一化若干已知集团名。"""
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

    klinikum_match = re.search(
        r'(?:Universitatsklinikum|Univ Klinikum|University Hospital)\s+(.+)$',
        ascii_fold(expanded),
        flags=re.IGNORECASE,
    )
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


def is_strong_c3_name(name: str) -> bool:
    """是否带有明确的组织级标记（大学 / 医院 / 公司 / 科学院等）。"""
    folded = ascii_fold(name).lower()
    strong_markers = (
        'university', 'hospital', 'company', 'corporation', 'group', 'academy',
        'college', 'foundation', 'system', 'medical center'
    )
    return any(marker in folded for marker in strong_markers)


def is_university_like_c3_name(name: str) -> bool:
    folded = ascii_fold(name).lower()
    markers = (
        'university', 'academy', 'college', 'system', 'school', 'medical university'
    )
    return any(marker in folded for marker in markers)


def is_company_like_c3_name(name: str) -> bool:
    folded = ascii_fold(name).lower()
    markers = ('company', 'limited', 'corporation', 'group', 'biotech', "l'oreal", 'shiseido')
    return any(marker in folded for marker in markers)


def is_academic_c3_name(name: str) -> bool:
    folded = ascii_fold(name).lower()
    academic_markers = (
        'university', 'academy', 'college', 'institute', 'school', 'system',
        'medical center', 'faculty', 'department'
    )
    return any(marker in folded for marker in academic_markers)


def is_address_like_c3_name(name: str) -> bool:
    """看起来是街道地址而非组织名（含门牌号或道路类词）。"""
    folded = ascii_fold(name).lower()
    if re.search(r'\b\d{2,}\b', folded):
        return True
    if re.match(r'^\d+\b', folded):
        return True
    return bool(re.search(
        r'\b(?:road|rd|avenue|ave|boulevard|blvd|lane|ln|rue|way|drive|dr|suite|ste|room|building|bldg)\b',
        folded,
    ))


def is_suppressible_c3_name(name: str) -> bool:
    """在同条记录已有更强学术组织时，压制明显噪声/外围机构。"""
    folded = ascii_fold(name).lower()
    if is_address_like_c3_name(name):
        return True
    if any(marker in folded for marker in ('company', 'limited', 'corporation', 'group')):
        return True
    if 'clinic' in folded or 'clin' in folded:
        return True
    if 'center' in folded or 'centre' in folded or 'ctr' in folded:
        return not is_academic_c3_name(name)
    if 'histo' in folded and not is_strong_c3_name(name):
        return True

    alpha_tokens = [token for token in re.split(r'[^a-z]+', folded) if token]
    if alpha_tokens and len(alpha_tokens) <= 2 and not is_strong_c3_name(name) and not is_academic_c3_name(name):
        return True
    return False


def should_suppress_fallback_c3_name(name: str, university_like_present: bool) -> bool:
    folded = ascii_fold(name).lower()
    if is_suppressible_c3_name(name):
        return True
    if not university_like_present:
        return False
    if is_university_like_c3_name(name):
        return False
    if any(marker in folded for marker in
           ('hospital', 'hosp', 'clinic', 'medical center', 'centre', 'center', 'ctr')):
        return True
    return False


def is_low_level_c3_name(name: str) -> bool:
    """是否为科室 / 实验室 / 中心一类的下级单位（且没有组织级标记）。"""
    folded = ascii_fold(name).lower()
    low_level_markers = (
        'innovation center', 'research center', 'research unit', 'technology', 'technol',
        'section', 'unit', 'laboratory', 'lab', 'department', 'faculty', 'division',
        'service', 'platform', 'core', 'program', 'programme', 'clinic', 'clin', 'centre', 'center',
        'ctr', 'histo', 'campus'
    )
    return any(marker in folded for marker in low_level_markers) and not is_strong_c3_name(name)


def deduplicate_c3_names(candidate_items: List[Dict[str, str]]) -> List[str]:
    """按归一化键去重，保留首次出现的原始写法。"""
    deduplicated = []
    seen = set()
    for candidate in candidate_items:
        name = candidate.get('name', '')
        if not name:
            continue
        lookup_key = normalize_lookup_key(name)
        if not lookup_key or lookup_key in seen:
            continue
        seen.add(lookup_key)
        deduplicated.append(name)
    return deduplicated


def c3_companion_root_tokens(name: str) -> Set[str]:
    """机构名中去掉通用组织词后的判别性词根，用于判断两个名字是否同源。"""
    normalized = ascii_fold(name).lower().replace('&', ' and ')
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


def get_c3_name_categories(name: str) -> Set[str]:
    """机构名命中的组织类别集合（可同时属于多类）。"""
    folded = ascii_fold(name).lower()
    categories: Set[str] = set()
    if is_university_like_c3_name(name):
        categories.add('university')
    if any(marker in folded for marker in
           ('hospital', 'hosp', 'medical center', 'medical centre', 'clinic', 'klinikum')):
        categories.add('hospital')
    if 'institute' in folded or re.search(r'inst', folded):
        categories.add('institute')
    if 'academy' in folded:
        categories.add('academy')
    if 'foundation' in folded or re.search(r'fdn', folded):
        categories.add('foundation')
    if 'system' in folded:
        categories.add('system')
    if is_company_like_c3_name(name):
        categories.add('company')
    return categories


def c3_names_are_hierarchy_distinct(left: str, right: str) -> bool:
    """两个同源名字是否分属不同层级（如"某大学" vs "某大学附属医院"）。"""
    left_folded = ascii_fold(left).lower()
    right_folded = ascii_fold(right).lower()
    if ('system' in left_folded) != ('system' in right_folded):
        return True

    left_categories = get_c3_name_categories(left)
    right_categories = get_c3_name_categories(right)
    shared_roots = c3_companion_root_tokens(left) & c3_companion_root_tokens(right)
    if (
        shared_roots
        and ('hospital' in left_categories) != ('hospital' in right_categories)
        and ('university' in left_categories or 'university' in right_categories)
    ):
        return True

    return False


def c3_names_are_equivalent(left: str, right: str) -> bool:
    """两个名字是否指向同一组织（层级不同则判为不等价）。"""
    if not left or not right:
        return False
    if normalize_lookup_key(left) == normalize_lookup_key(right):
        return True
    if c3_names_are_hierarchy_distinct(left, right):
        return False
    return institution_similarity(left, right) >= 0.72


def select_primary_c3_name(institution_text: str) -> str:
    """从一条 affiliation 地址中选出组织级主体名，并展开缩写。

    去掉尾部的城市/国家段后，按组织类型优先级排序：大学 > 公司 > 学院 > 医院 >
    基金会 > 研究所 > 中心 > 科室，同级取更长的名字。
    """
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
    filtered_parts = [
        part for part in organization_parts
        if any(marker in ascii_fold(part).lower() for marker in institution_markers)
    ]
    if filtered_parts:
        organization_parts = filtered_parts

    def priority(part: str) -> tuple[int, int]:
        part_folded = ascii_fold(part).lower()
        if 'campus' in part_folded:
            return (7, -len(part))
        if 'unesp' in part_folded:
            return (0, -len(part))
        if 'univ' in part_folded or 'university' in part_folded:
            return (0, -len(part))
        if ('company' in part_folded or 'co ltd' in part_folded or 'corporation' in part_folded
                or 'corp' in part_folded or 'limited' in part_folded or 'group' in part_folded
                or 'biotech' in part_folded or "l'oreal" in part_folded or 'loreal' in part_folded):
            return (1, -len(part))
        if 'college' in part_folded or 'school' in part_folded:
            return (2, -len(part))
        if 'hospital' in part_folded or 'hosp' in part_folded or 'klinikum' in part_folded:
            return (3, -len(part))
        if 'foundation' in part_folded or 'academy' in part_folded or 'ministry' in part_folded:
            return (4, -len(part))
        if 'institute' in part_folded or 'inst' in part_folded:
            return (5, -len(part))
        if ('center' in part_folded or 'centre' in part_folded or 'ctr' in part_folded
                or 'clinic' in part_folded or 'lab' in part_folded):
            return (6, -len(part))
        if ('department' in part_folded or 'dept' in part_folded or 'division' in part_folded
                or 'faculty' in part_folded):
            return (9, -len(part))
        return (8, -len(part))

    best = min(organization_parts, key=priority)
    return expand_c3_abbreviations(best)
