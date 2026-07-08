#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Dict, Optional


class AuthorDatabase:
    """作者数据库读取器。"""

    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        with open(self.db_path, encoding='utf-8') as f:
            data = json.load(f)

        self.authors: Dict[str, Dict] = data.get('authors', {})
        self._normalized_index = {
            self._normalize_name(name): record
            for name, record in self.authors.items()
        }
        self._full_name_index: Dict[str, Dict] = {}
        self._surname_index = defaultdict(list)

        for record in self.authors.values():
            if not isinstance(record, dict):
                continue
            full_name = record.get('full_name', '')
            if not full_name:
                continue

            full_key = self._normalize_person_name(full_name)
            if full_key and full_key not in self._full_name_index:
                self._full_name_index[full_key] = record

            surname_key = self._normalize_surname(full_name)
            if surname_key:
                self._surname_index[surname_key].append(record)

    def get_full_name(self, abbreviated_name: str) -> str:
        record = self.authors.get(abbreviated_name)
        if record is None:
            record = self._normalized_index.get(self._normalize_name(abbreviated_name))

        if isinstance(record, dict):
            return record.get('full_name') or abbreviated_name
        if isinstance(record, str):
            return record
        return abbreviated_name

    def get_preferred_full_name(self, full_name: str) -> str:
        record = self._match_record_by_full_name(full_name)
        if isinstance(record, dict):
            return record.get('full_name') or full_name
        return full_name

    def get_preferred_abbreviated(self, full_name: str) -> str:
        record = self._match_record_by_full_name(full_name)
        if isinstance(record, dict):
            return record.get('abbreviated') or ''
        return ''

    def _match_record_by_full_name(self, full_name: str) -> Optional[Dict]:
        normalized_full = self._normalize_person_name(full_name)
        if not normalized_full:
            return None

        exact = self._full_name_index.get(normalized_full)
        if exact:
            return exact

        surname_key = self._normalize_surname(full_name)
        if not surname_key:
            return None

        input_tokens = self._extract_given_tokens(full_name)
        if not input_tokens:
            return None

        for candidate in self._surname_index.get(surname_key, []):
            candidate_tokens = self._extract_given_tokens(candidate.get('full_name', ''))
            if self._given_names_compatible(input_tokens, candidate_tokens):
                return candidate

        return None

    @staticmethod
    def _ascii_fold(text: str) -> str:
        return unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')

    @classmethod
    def _normalize_name(cls, name: str) -> str:
        return ' '.join(name.strip().lower().split())

    @classmethod
    def _normalize_person_name(cls, name: str) -> str:
        if not name:
            return ''
        name = re.sub(r'\s*\([^)]*\)', '', name)
        name = cls._ascii_fold(name)
        name = name.replace(',', ' ')
        name = re.sub(r'[^A-Za-z0-9\s\-\.]', ' ', name)
        name = re.sub(r'\s+', ' ', name).strip().lower()
        return name

    @classmethod
    def _normalize_surname(cls, name: str) -> str:
        if not name or not name.strip():
            return ''
        surname = name.split(',', 1)[0] if ',' in name else name.split()[-1]
        surname = cls._ascii_fold(surname)
        surname = re.sub(r'[^A-Za-z\s\-\']', ' ', surname)
        surname = re.sub(r'\s+', ' ', surname).strip().lower()
        return surname

    @classmethod
    def _extract_given_tokens(cls, full_name: str) -> list[str]:
        if not full_name:
            return []
        given = full_name.split(',', 1)[1] if ',' in full_name else ' '.join(full_name.split()[:-1])
        given = cls._ascii_fold(given)
        tokens = [
            token.lower()
            for token in re.split(r'[\s\-\.]+', given)
            if token and re.search(r'[A-Za-z]', token)
        ]
        return tokens

    @staticmethod
    def _tokens_compatible(left: str, right: str) -> bool:
        if not left or not right:
            return False
        if left == right:
            return True
        if len(left) == 1:
            return right.startswith(left)
        if len(right) == 1:
            return left.startswith(right)
        return False

    @classmethod
    def _given_names_compatible(cls, input_tokens: list[str], candidate_tokens: list[str]) -> bool:
        if not input_tokens or not candidate_tokens:
            return False

        if len(input_tokens) == 1 and len(candidate_tokens) > 1 and input_tokens[0] != candidate_tokens[0]:
            return False

        overlap = min(len(input_tokens), len(candidate_tokens))
        for index in range(overlap):
            if not cls._tokens_compatible(input_tokens[index], candidate_tokens[index]):
                return False

        if len(candidate_tokens) > len(input_tokens):
            extra = candidate_tokens[len(input_tokens):]
            return all(len(token) == 1 for token in extra)

        return True
