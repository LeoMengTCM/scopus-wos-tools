#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""作者姓名的解析、缩写与查找键生成。

Scopus 与 WOS 的作者字段差异集中在三处：缩写写法（``M.V.`` vs ``MV``）、复合姓氏的
断句（``Akar, Firas Abu`` 应为 ``Abu Akar, Firas``），以及东亚姓名的单词式名字
（``Xiaoming`` 在 WOS 里常拆成 ``XM``）。这里的函数负责把 Scopus 侧向 WOS 风格对齐，
并生成跨库匹配用的多档查找键。

从 ``converters/scopus.py`` 中拆出，行为与拆分前逐字节一致。
"""

from __future__ import annotations

import logging
import re
from typing import List

from ._normalization import ascii_fold

logger = logging.getLogger(__name__)


def convert_authors(authors_str: str) -> List[str]:
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


def fix_compound_lastname(author_name: str) -> str:
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

                logger.debug(f"修复复合姓氏: '{author_name}' -> '{new_lastname}, {new_firstname}'")

                return f"{new_lastname}, {new_firstname}"

    # 没有发现问题，返回原样
    return author_name


def clean_author_full_name(author: str) -> str:
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
            author_clean = fix_compound_lastname(author_clean)

    return author_clean


def parse_scopus_full_names(full_names_str: str) -> List[str]:
    """解析 Scopus 作者全名，并尽量保留原始信息密度。"""
    if not full_names_str:
        return []

    parsed_names = []
    for raw_author in full_names_str.split(';'):
        parsed_names.append(clean_author_full_name(raw_author.strip()))

    return parsed_names


def extract_given_name_tokens(author_name: str) -> List[str]:
    """取出名字部分的词元（折叠重音、按空格/连字符/点号切分）。"""
    if not author_name or ',' not in author_name:
        return []

    given_name = author_name.split(',', 1)[1].strip()
    return [
        token
        for token in re.split(r'[\s\-\.]+', ascii_fold(given_name))
        if token and re.search(r'[A-Za-z]', token)
    ]


def has_explicit_given_name(author_name: str) -> bool:
    """名字部分是否含有完整拼写（而非只有首字母）。"""
    return any(len(token) > 1 for token in extract_given_name_tokens(author_name))


def normalize_surname(author_name: str) -> str:
    if not author_name:
        return ''

    surname = author_name.split(',', 1)[0].strip() if ',' in author_name else author_name.strip()
    surname = ascii_fold(surname)
    surname = re.sub(r'[^A-Za-z\s\-\']', ' ', surname)
    surname = re.sub(r'\s+', ' ', surname).strip().lower()
    return surname


def is_author_database_name_usable(original_name: str, candidate_name: str) -> bool:
    """作者库只用于补全，不允许把更明确的 Scopus 全名降级。"""
    if not candidate_name or candidate_name == original_name:
        return False

    if ',' not in candidate_name:
        return False

    original_surname = normalize_surname(original_name)
    candidate_surname = normalize_surname(candidate_name)
    if original_surname and candidate_surname and original_surname != candidate_surname:
        return False

    if has_explicit_given_name(original_name) and not has_explicit_given_name(candidate_name):
        return False

    original_given = ''.join(extract_given_name_tokens(original_name))
    candidate_given = ''.join(extract_given_name_tokens(candidate_name))
    if original_given and candidate_given and len(candidate_given) < len(original_given):
        return False

    return True


def normalize_author_initials(initials: str) -> str:
    """剥掉 Jr/Sr/III 一类的后缀，只保留字母。"""
    if not initials:
        return ''

    suffix_pattern = r'\b(jr|jnr|sr|ii|iii|iv)\b'
    initials = re.sub(suffix_pattern, ' ', ascii_fold(initials), flags=re.IGNORECASE)
    return re.sub(r'[^A-Za-z]', '', initials)


def get_author_initials(abbreviated_author: str) -> str:
    """提取缩写作者中的名字首字母。"""
    if ',' not in abbreviated_author:
        return ''
    initials = abbreviated_author.split(',', 1)[1]
    return normalize_author_initials(initials)


def should_use_author_database(abbreviated_author: str) -> bool:
    """仅在缩写信息相对不含糊时才使用作者数据库。"""
    return len(get_author_initials(abbreviated_author)) >= 2


def normalize_person_lookup_key(text: str) -> str:
    """人名查找键：去括注、折叠重音、只留字母数字与分隔符。"""
    if not text:
        return ''
    text = re.sub(r'\s*\([^)]*\)', '', text)
    text = ascii_fold(text).lower()
    text = re.sub(r'[^a-z0-9\s,\-\.]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def coarsen_person_lookup_key(author_key: str) -> str:
    """把查找键退化到"姓 + 首个首字母"，用于放宽匹配。"""
    if not author_key or ',' not in author_key:
        return author_key
    lastname, initials = author_key.split(',', 1)
    initials = re.sub(r'[^a-z]', '', initials)
    if initials:
        return f"{lastname.strip()}, {initials[0]}"
    return lastname.strip()


def person_lookup_key_variants(text: str, include_coarse: bool = True) -> List[str]:
    """生成由严到宽的一组人名查找键（保持顺序，去重）。"""
    author_key = normalize_person_lookup_key(text)
    if not author_key:
        return []

    variants: List[str] = []

    def add(candidate: str) -> None:
        candidate = candidate.strip()
        if candidate and candidate not in variants:
            variants.append(candidate)

    add(author_key)
    if include_coarse:
        add(coarsen_person_lookup_key(author_key))

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


def compose_author_affiliation_key(author_key: str, affiliation_key: str) -> str:
    return f"{author_key}||{affiliation_key}"


def is_likely_east_asian_name(last_name: str, first_name: str) -> bool:
    """姓氏在东亚常见姓表内、且名字是单个较长词——多半需要拆成双字名。"""
    surname = re.sub(r"[^a-z]", '', ascii_fold(last_name).lower())
    given = re.sub(r"[^a-z]", '', ascii_fold(first_name).lower())
    east_asian_surnames = {
        'wang', 'li', 'zhang', 'liu', 'chen', 'yang', 'huang', 'wu', 'xu', 'sun', 'zhao', 'zhou',
        'zheng', 'gao', 'guo', 'he', 'hu', 'lin', 'lu', 'ma', 'xie', 'ye', 'yu', 'dong', 'deng',
        'jiang', 'qian', 'tang', 'xiao', 'hao', 'jin', 'han', 'cao', 'feng', 'gong', 'song', 'shi',
        'cho', 'kim', 'lee', 'park', 'yoo', 'goo', 'kang', 'ahn', 'seo', 'choi', 'kwon', 'jung',
    }
    return surname in east_asian_surnames and ' ' not in given and 4 <= len(given) <= 10


def split_compound_given_name(token: str) -> List[str]:
    """把 "xiaoming" 一类的拼音双字名切成两段，按声母/韵母启发式打分。"""
    token = re.sub(r'[^a-z]', '', ascii_fold(token).lower())
    if len(token) < 4 or len(token) > 8:
        return [token] if token else []

    half = len(token) // 2
    if len(token) % 2 == 0 and token[:half] == token[half:]:
        return [token[:half], token[half:]]

    vowels = set('aeiou')
    onsets = ('zh', 'ch', 'sh', 'b', 'p', 'm', 'f', 'd', 't', 'n', 'l', 'g', 'k', 'h', 'j', 'q',
              'x', 'r', 'z', 'c', 's', 'y', 'w')
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


def extract_initials_from_full_name(full_name: str) -> str:
    """从完整作者名提取尽量完整的 WOS 风格首字母。"""
    if not full_name or ',' not in full_name:
        return ''

    lastname, firstname = [part.strip() for part in full_name.split(',', 1)]
    tokens = [token for token in re.split(r'[\s\-]+', firstname) if token]
    if len(tokens) == 1 and is_likely_east_asian_name(lastname, firstname):
        split_tokens = split_compound_given_name(tokens[0])
        if len(split_tokens) >= 2:
            tokens = split_tokens

    initials = ''
    for token in tokens:
        token_ascii = ascii_fold(re.sub(r'[^A-Za-z]', '', token))
        if token_ascii:
            initials += token_ascii[0].upper()
    return initials
