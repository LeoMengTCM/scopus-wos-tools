#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gemini API配置模块

作者：Meng Linghan
开发工具：Claude Code
日期：2025-11-10
版本：v1.0
"""

import os
import json
import logging
from typing import Optional

from .utils.paths import resolve_project_path

logger = logging.getLogger(__name__)


PLACEHOLDER_API_KEYS = {
    'YOUR_API_KEY',
    'YOUR_API_KEY_HERE',
    'YOUR_GEMINI_API_KEY'
}


class GeminiConfig:
    """Gemini API配置管理"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        model: Optional[str] = None
    ):
        """
        初始化Gemini配置

        Args:
            api_key: API密钥
            api_url: API地址
            model: 模型名称
        """
        # 优先使用传入的参数，其次使用环境变量，最后使用默认值
        self.api_key = api_key or os.getenv('GEMINI_API_KEY')
        self.api_url = api_url or os.getenv('GEMINI_API_URL', 'https://generativelanguage.googleapis.com/v1beta')
        self.model = model or os.getenv('GEMINI_MODEL', 'gemini-2.5-flash-lite')

        # API配置
        self.max_tokens = int(os.getenv('GEMINI_MAX_TOKENS', '5000'))  # 增加到5000
        self.temperature = float(os.getenv('GEMINI_TEMPERATURE', '0.1'))
        self.timeout = int(os.getenv('GEMINI_TIMEOUT', '60'))  # 增加超时时间

        # 重试配置
        self.max_retries = int(os.getenv('GEMINI_MAX_RETRIES', '3'))
        self.retry_delay = int(os.getenv('GEMINI_RETRY_DELAY', '5'))  # 秒

        # 功能开关
        self.enabled = self._has_real_api_key(self.api_key)
        self.enable_caching = True
        self.fallback_to_rules = True

    @staticmethod
    def _has_real_api_key(api_key: Optional[str]) -> bool:
        if not api_key:
            return False

        normalized = api_key.strip()
        return bool(normalized) and normalized not in PLACEHOLDER_API_KEYS

    @classmethod
    def from_file(cls, config_file: str = 'config/gemini_config.json') -> 'GeminiConfig':
        """
        从配置文件加载

        Args:
            config_file: 配置文件路径

        Returns:
            GeminiConfig实例
        """
        config_path = resolve_project_path(config_file)

        if not config_path.exists():
            logger.warning(f"配置文件不存在: {config_file}，使用默认配置")
            return cls()

        try:
            with open(config_path, encoding='utf-8') as f:
                config_data = json.load(f)

            config = cls(
                api_key=config_data.get('api_key'),
                api_url=config_data.get('api_url'),
                model=config_data.get('model')
            )
            # save_to_file 会写出这些字段，读取时也应生效（否则配置往返不对称）
            if 'max_tokens' in config_data:
                config.max_tokens = int(config_data['max_tokens'])
            if 'temperature' in config_data:
                config.temperature = float(config_data['temperature'])
            if 'timeout' in config_data:
                config.timeout = int(config_data['timeout'])
            if 'enable_caching' in config_data:
                config.enable_caching = bool(config_data['enable_caching'])
            if 'fallback_to_rules' in config_data:
                config.fallback_to_rules = bool(config_data['fallback_to_rules'])
            return config
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            return cls()

    @classmethod
    def from_params(cls, api_key: str, api_url: str, model: str) -> 'GeminiConfig':
        """
        从参数创建配置

        Args:
            api_key: API密钥
            api_url: API地址
            model: 模型名称

        Returns:
            GeminiConfig实例
        """
        return cls(api_key=api_key, api_url=api_url, model=model)

    def save_to_file(self, config_file: str = 'config/gemini_config.json'):
        """
        保存配置到文件

        Args:
            config_file: 配置文件路径
        """
        config_path = resolve_project_path(config_file)
        config_path.parent.mkdir(parents=True, exist_ok=True)

        config_data = {
            'api_key': self.api_key,
            'api_url': self.api_url,
            'model': self.model,
            'max_tokens': self.max_tokens,
            'temperature': self.temperature,
            'timeout': self.timeout,
            'enable_caching': self.enable_caching,
            'fallback_to_rules': self.fallback_to_rules
        }

        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, ensure_ascii=False, indent=2)

        logger.info(f"配置已保存到: {config_file}")

    def is_enabled(self) -> bool:
        """检查是否启用Gemini API"""
        return self.enabled and self._has_real_api_key(self.api_key)

    def validate(self) -> bool:
        """验证配置是否有效"""
        if not self._has_real_api_key(self.api_key):
            logger.error("API密钥未配置")
            return False

        if not self.api_url:
            logger.error("API地址未配置")
            return False

        if not self.model:
            logger.error("模型名称未配置")
            return False

        return True

    def __repr__(self) -> str:
        """字符串表示（隐藏API密钥，只显示末4位）"""
        masked_key = f"...{self.api_key[-4:]}" if self.api_key and len(self.api_key) > 8 else ("已配置" if self.api_key else "未配置")
        return (
            f"GeminiConfig(\n"
            f"  api_key={masked_key},\n"
            f"  api_url={self.api_url},\n"
            f"  model={self.model},\n"
            f"  enabled={self.enabled}\n"
            f")"
        )


def create_default_config_file():
    """创建默认配置文件模板"""
    config_path = resolve_project_path('config/gemini_config.json')
    config_path.parent.mkdir(parents=True, exist_ok=True)

    if config_path.exists():
        logger.warning(f"配置文件已存在: {config_path}")
        return

    default_config = {
        'api_key': 'YOUR_API_KEY_HERE',
        'api_url': 'https://generativelanguage.googleapis.com/v1beta',
        'model': 'gemini-2.5-flash-lite',
        'max_tokens': 1000,
        'temperature': 0.1,
        'timeout': 30,
        'enable_caching': True,
        'fallback_to_rules': True
    }

    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(default_config, f, ensure_ascii=False, indent=2)

    print(f"✓ 已创建配置文件模板: {config_path}")
    print("  请编辑该文件，填入你的API密钥")


if __name__ == '__main__':
    # 测试配置
    print("=" * 80)
    print("Gemini API配置测试")
    print("=" * 80)
    print()

    # 创建配置
    config = GeminiConfig.from_params(
        api_key=os.getenv('GEMINI_API_KEY', 'YOUR_API_KEY'),
        api_url=os.getenv('GEMINI_API_URL', 'https://generativelanguage.googleapis.com/v1beta'),
        model='gemini-2.5-flash-lite'
    )

    print("配置信息:")
    print(config)
    print()

    # 验证配置
    if config.validate():
        print("✓ 配置验证通过")
    else:
        print("✗ 配置验证失败")
