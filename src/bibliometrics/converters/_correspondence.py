#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通讯作者（RP 字段）的识别与消歧。

Scopus 的 correspondence 字段是一段自由文本，作者名的写法与 AU 列表并不一致
（可能是 "Di Sabatino A."、"A. Di Sabatino" 或全名）。这里先把 token 拆成姓与首字母，
再用多种拼写变体去匹配 AU 候选；当一个 token 匹配到多个作者时，用邮箱局部名做二次
消歧——邮箱里通常同时含有姓和首字母。

从 ``converters/scopus.py`` 中拆出，行为与拆分前逐字节一致。
"""

from __future__ import annotations

import re
from typing import List, Optional, Set, Tuple

from ._authors import get_author_initials, normalize_author_initials
from ._normalization import ascii_fold


def extract_correspondence_token_name_parts(token: str) -> Tuple[str, str]:
    """把 correspondence token 拆成（姓, 名字首字母），姓氏粒子归入姓。"""
    folded = ascii_fold(token)
    words = [word for word in re.split(r'[^A-Za-z]+', folded) if word]
    if not words:
        return '', ''

    suffixes = {'jr', 'jnr', 'sr', 'ii', 'iii', 'iv'}
    surname_particles = {'al', 'el', 'de', 'del', 'della', 'da', 'di', 'van', 'von',
                         'bin', 'ibn', 'abu', 'ben'}
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


def initials_match_flexibly(token_initials: str, candidate_initials: str) -> bool:
    """首字母是否兼容：相等、互为前缀，或互为子序列。"""
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


def match_correspondence_authors(token: str, abbreviated_authors: List[str]) -> List[str]:
    """将通讯作者字符串匹配到一个或多个 AU 候选。"""
    token_norm = re.sub(r'[^A-Za-z]', '', ascii_fold(token)).lower()
    if not token_norm:
        return []

    token_surname, token_initials = extract_correspondence_token_name_parts(token)
    matched_authors = []
    for author in abbreviated_authors:
        if ',' not in author:
            continue

        lastname, initials = [part.strip() for part in author.split(',', 1)]
        lastname_folded = ascii_fold(lastname)
        lastname_norm = re.sub(r'[^a-z]', '', lastname_folded.lower())
        initials_clean = normalize_author_initials(initials)
        dotted_initials = ''.join(f"{char}." for char in initials_clean)
        first_initial = initials_clean[:1]
        lastname_variants = {
            lastname_folded,
            lastname_folded.replace('oe', 'o').replace('ae', 'a').replace('ue', 'u'),
        }
        candidates = set()
        for lastname_variant in lastname_variants:
            candidates.update({
                re.sub(r'[^A-Za-z]', '', ascii_fold(author)).lower(),
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
            and initials_match_flexibly(token_initials, initials_clean.lower())
        )
        if (exact_match or flexible_match) and author not in matched_authors:
            matched_authors.append(author)

    return matched_authors


def score_correspondence_author_email(author: str, emails: List[str]) -> float:
    """用邮箱局部名给候选作者打分：同时含姓与首字母得分最高。"""
    if not author or ',' not in author:
        return 0.0

    lastname, initials = [part.strip() for part in author.split(',', 1)]
    lastname = re.sub(r'[^a-z]', '', ascii_fold(lastname).lower())
    initials = normalize_author_initials(initials).lower()
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


def resolve_correspondence_author(
    candidates: List[str],
    emails: List[str],
    used_authors: Set[str],
) -> Optional[str]:
    """在多个候选中选定一位：先看邮箱证据，再避免重复占用同一作者。"""
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    scored_candidates = []
    for candidate in candidates:
        score = score_correspondence_author_email(candidate, emails)
        if candidate in used_authors:
            score -= 0.2
        scored_candidates.append((score, len(get_author_initials(candidate)), candidate))

    best_score = max(score for score, _, _ in scored_candidates)
    top_candidates = [
        candidate
        for score, _, candidate in scored_candidates
        if score == best_score
    ]

    if best_score > 0:
        top_candidates.sort(
            key=lambda candidate: (candidate in used_authors, -len(get_author_initials(candidate)))
        )
        return top_candidates[0]

    for candidate in candidates:
        if candidate not in used_authors:
            return candidate
    return candidates[0]


def looks_like_institutional_address(address: str) -> bool:
    """地址里是否出现组织级机构词（用于判断该段是否值得保留为 C1/RP）。"""
    folded = ascii_fold(address).lower()
    markers = (
        'univ', 'university', 'hosp', 'hospital', 'inst', 'institute', 'company',
        'college', 'academy', 'school', 'center', 'centre', 'ctr', 'clinic', 'medical center'
    )
    return any(marker in folded for marker in markers)
