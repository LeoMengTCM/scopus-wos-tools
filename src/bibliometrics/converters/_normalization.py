#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Scopus → WOS 转换过程中的文本归一化原语。

这里的函数是整个转换流程的最底层工具，在一次运行中会被调用数百万次，因此纯计算部分
统一带 ``lru_cache``。所有对外函数都是**空值安全**的：传入空串或 ``None`` 返回空结果，
而不是抛异常——调用点大量来自解析出的可选字段。

从 ``converters/scopus.py`` 中拆出，行为与拆分前逐字节一致。
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import FrozenSet, List, Tuple

_ASCII_FOLD_SPECIAL_MAP = str.maketrans({
    'ı': 'i', 'İ': 'I', 'Ł': 'L', 'ł': 'l', 'Ø': 'O', 'ø': 'o',
    'Đ': 'D', 'đ': 'd', 'Æ': 'AE', 'æ': 'ae', 'Œ': 'OE', 'œ': 'oe',
    'ß': 'ss',
})


@lru_cache(maxsize=None)
def _ascii_fold_cached(text: str) -> str:
    folded = text.translate(_ASCII_FOLD_SPECIAL_MAP)
    return unicodedata.normalize('NFKD', folded).encode('ascii', 'ignore').decode('ascii')


def ascii_fold(text: str) -> str:
    """去除重音等非 ASCII 差异，使作者缩写与机构名更贴近 WOS 风格。"""
    if not text:
        return ''
    return _ascii_fold_cached(text)


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
def _institution_similarity_token_tuple(text: str) -> Tuple[str, ...]:
    """机构名分词：同义词归并 + 词组展开 + 停用词过滤。"""
    normalized = ascii_fold(text).lower().replace('&', ' and ')
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
def _institution_similarity_token_set(text: str) -> FrozenSet[str]:
    return frozenset(_institution_similarity_token_tuple(text))


def institution_similarity_tokens(text: str) -> List[str]:
    """机构名的相似度分词结果。"""
    if not text:
        return []
    return list(_institution_similarity_token_tuple(text))


def institution_similarity(left: str, right: str) -> float:
    """两个机构名的 Dice 系数（0.0–1.0），按相似度分词后计算。"""
    left_tokens = _institution_similarity_token_set(left) if left else frozenset()
    right_tokens = _institution_similarity_token_set(right) if right else frozenset()

    if not left_tokens or not right_tokens:
        return 0.0

    overlap = len(left_tokens & right_tokens)
    if not overlap:
        return 0.0

    return (2 * overlap) / (len(left_tokens) + len(right_tokens))


@lru_cache(maxsize=None)
def _normalize_lookup_key_cached(text: str) -> str:
    folded = ascii_fold(text).lower().replace('&', ' and ')
    folded = re.sub(r'[^a-z0-9\s]', ' ', folded)
    return re.sub(r'\s+', ' ', folded).strip()


def normalize_lookup_key(text: str) -> str:
    """跨库对齐用的宽松匹配键：折叠重音、去标点、压缩空白。"""
    if not text:
        return ''
    return _normalize_lookup_key_cached(text)


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
def tokenize_affiliation(text: str) -> FrozenSet[str]:
    """机构地址分词：去掉通用组织词后剩下的判别性词元。"""
    normalized = normalize_lookup_key(text)
    return frozenset(
        token for token in normalized.split()
        if len(token) > 1 and token not in _AFFILIATION_TOKEN_STOPWORDS
    )
