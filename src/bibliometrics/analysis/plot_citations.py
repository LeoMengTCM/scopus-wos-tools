#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
年度发文量及引用量分析和可视化 v3.0 (Professional Edition with Trend Lines)

自动从WOS文件中提取年度发文量和引用量数据并生成高质量可视化图表
包含趋势线分析和专业的视觉设计

作者：Meng Linghan
开发工具：Claude Code
日期：2025-11-17
版本：v3.0
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import re
from pathlib import Path
from typing import Dict, Optional, Tuple
from collections import defaultdict

from ..utils.paths import find_existing_analysis_file
from ..utils.wos_text import split_wos_records


class PublicationCitationAnalyzer:
    """年度发文量和引用量分析器"""

    def __init__(self):
        """初始化分析器"""
        self._setup_plot_style()
        self._setup_colors()

    def _setup_plot_style(self):
        """设置专业图表样式"""
        try:
            plt.rcParams['font.family'] = 'Helvetica'
        except Exception:
            print("Helvetica font not found. Falling back to sans-serif.")
            plt.rcParams['font.family'] = 'sans-serif'

        plt.rcParams['font.size'] = 12
        plt.rcParams['axes.labelsize'] = 14
        plt.rcParams['axes.titlesize'] = 18
        plt.rcParams['xtick.labelsize'] = 12
        plt.rcParams['ytick.labelsize'] = 12
        plt.rcParams['legend.fontsize'] = 12
        plt.rcParams['figure.titlesize'] = 20

    def _setup_colors(self):
        """设置专业配色方案"""
        self.colors = {
            'publications': '#5780A4',      # 发文量主色
            'citations': '#F08E64',         # 引用量主色
            'trend_publications': '#CB5623', # 发文量趋势线
            'trend_citations': '#333333',    # 引用量趋势线
            'text': '#333333',              # 文本颜色
            'subtle': '#AAAAAA',            # 次要元素颜色
        }

    def parse_wos_file(self, file_path: str) -> Tuple[Dict[int, int], Dict[int, int]]:
        """
        解析WOS文件，提取年度发文量和引用量

        Args:
            file_path: WOS文件路径

        Returns:
            (publications_dict, citations_dict): 年份->数量的字典
        """
        publications = defaultdict(int)
        citations = defaultdict(int)

        with open(file_path, encoding='utf-8-sig') as f:
            content = f.read()

        # 按记录分割（兼容头部后有/无空行两种形态）
        records = split_wos_records(content)

        for record in records:
            if not record.strip():
                continue

            # 提取年份 (PY字段)
            py_match = re.search(r'^PY\s+(\d{4})', record, re.MULTILINE)
            if not py_match:
                continue

            year = int(py_match.group(1))
            publications[year] += 1

            # 提取引用次数 (TC字段)
            tc_match = re.search(r'^TC\s+(\d+)', record, re.MULTILINE)
            if tc_match:
                citation_count = int(tc_match.group(1))
                citations[year] += citation_count

        return dict(publications), dict(citations)

    def create_dataframe(self, publications: Dict[int, int],
                        citations: Dict[int, int]) -> pd.DataFrame:
        """
        创建DataFrame

        Args:
            publications: 年份->发文量字典
            citations: 年份->引用量字典

        Returns:
            包含Year, Publications, Citations列的DataFrame
        """
        # 获取所有年份
        all_years = sorted(set(publications.keys()) | set(citations.keys()))

        data = {
            'Year': all_years,
            'Publications': [publications.get(year, 0) for year in all_years],
            'Citations': [citations.get(year, 0) for year in all_years]
        }

        return pd.DataFrame(data)


    def _build_trendline(self, values: pd.Series) -> Optional[np.ndarray]:
        """根据数据点数量自适应生成趋势线。"""
        point_count = len(values)
        if point_count < 2:
            return None

        x_numeric = np.arange(point_count)
        degree = min(2, point_count - 1)
        coeffs = np.polyfit(x_numeric, values, degree)
        return np.poly1d(coeffs)(x_numeric)

    def _get_axis_upper_bound(self, values: pd.Series) -> float:
        """返回稳健的 Y 轴上界，避免空值或全零时报错。"""
        max_value = float(values.max()) if not values.empty else 0.0
        return max(1.0, max_value * 1.25)

    def plot_publications(self, data: pd.DataFrame, output_dir: str):
        """
        绘制年度发文量图（带趋势线）

        Args:
            data: 包含Year和Publications列的DataFrame
            output_dir: 输出目录
        """
        trendline_values = self._build_trendline(data['Publications'])

        # 创建图表
        fig, ax = plt.subplots(figsize=(10, 6))

        # 绘制柱状图
        bars = ax.bar(data['Year'], data['Publications'],
                     color=self.colors['publications'],
                     edgecolor='black',
                     linewidth=0.5)

        # 添加数值标签
        ax.bar_label(bars, padding=3, fontsize=9, color=self.colors['text'])

        # 绘制趋势线（数据点过少时跳过）
        if trendline_values is not None:
            ax.plot(data['Year'], trendline_values,
                   color=self.colors['trend_publications'],
                   linestyle='--',
                   linewidth=2.5,
                   label='Trend Line')

        # 设置样式
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_color(self.colors['subtle'])
        ax.spines['bottom'].set_color(self.colors['subtle'])
        ax.grid(axis='y', linestyle='--', alpha=0.6, color=self.colors['subtle'])
        ax.tick_params(axis='both', direction='out',
                      colors=self.colors['subtle'],
                      labelcolor=self.colors['text'])

        # 设置标签和标题
        ax.set_ylabel('Number of Documents', fontsize=14, labelpad=10,
                     color=self.colors['text'])
        ax.set_xlabel('Year', fontsize=14, labelpad=10,
                     color=self.colors['text'])
        ax.set_ylim(0, self._get_axis_upper_bound(data['Publications']))

        # 确保显示所有年份标签
        ax.set_xticks(data['Year'])
        plt.setp(ax.get_xticklabels(), rotation=45, ha="right",
                rotation_mode="anchor")

        # 添加图例和标签
        if trendline_values is not None:
            ax.legend(loc='upper left', frameon=False, fontsize=12)
        ax.text(-0.1, 1.05, 'A', transform=ax.transAxes,
               fontsize=24, fontweight='bold', va='top',
               color=self.colors['text'])

        plt.tight_layout()

        # 保存图片
        output_path = Path(output_dir)
        for fmt in ['tiff', 'png']:
            fig.savefig(output_path / f'各年发文量.{fmt}',
                       dpi=300, bbox_inches='tight',
                       format=fmt, facecolor='white', edgecolor='none')

        plt.close(fig)
        print("  ✓ 各年发文量图已保存")

    def plot_citations(self, data: pd.DataFrame, output_dir: str):
        """
        绘制年度引用量图（带趋势线）

        Args:
            data: 包含Year和Citations列的DataFrame
            output_dir: 输出目录
        """
        trendline_values = self._build_trendline(data['Citations'])

        # 创建图表
        fig, ax = plt.subplots(figsize=(10, 6))

        # 绘制柱状图
        bars = ax.bar(data['Year'], data['Citations'],
                     color=self.colors['citations'],
                     edgecolor='black',
                     linewidth=0.5)

        # 添加数值标签
        ax.bar_label(bars, padding=3, fontsize=9, color=self.colors['text'])

        # 绘制趋势线（数据点过少时跳过）
        if trendline_values is not None:
            ax.plot(data['Year'], trendline_values,
                   color=self.colors['trend_citations'],
                   linestyle='--',
                   linewidth=2.5,
                   label='Trend Line')

        # 设置样式
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_color(self.colors['subtle'])
        ax.spines['bottom'].set_color(self.colors['subtle'])
        ax.grid(axis='y', linestyle='--', alpha=0.6, color=self.colors['subtle'])
        ax.tick_params(axis='both', direction='out',
                      colors=self.colors['subtle'],
                      labelcolor=self.colors['text'])

        # 设置标签和标题
        ax.set_ylabel('Number of Citations', fontsize=14, labelpad=10,
                     color=self.colors['text'])
        ax.set_xlabel('Year', fontsize=14, labelpad=10,
                     color=self.colors['text'])
        ax.set_ylim(0, self._get_axis_upper_bound(data['Citations']))

        # 确保显示所有年份标签
        ax.set_xticks(data['Year'])
        plt.setp(ax.get_xticklabels(), rotation=45, ha="right",
                rotation_mode="anchor")

        # 添加图例和标签
        if trendline_values is not None:
            ax.legend(loc='upper left', frameon=False, fontsize=12)
        ax.text(-0.1, 1.05, 'B', transform=ax.transAxes,
               fontsize=24, fontweight='bold', va='top',
               color=self.colors['text'])

        plt.tight_layout()

        # 保存图片
        output_path = Path(output_dir)
        for fmt in ['tiff', 'png']:
            fig.savefig(output_path / f'各年引用量.{fmt}',
                       dpi=300, bbox_inches='tight',
                       format=fmt, facecolor='white', edgecolor='none')

        plt.close(fig)
        print("  ✓ 各年引用量图已保存")

    def plot_combined(self, data: pd.DataFrame, output_dir: str):
        """
        绘制组合图（发文量和引用量，带趋势线）

        Args:
            data: 包含Year, Publications, Citations列的DataFrame
            output_dir: 输出目录
        """
        trendline_pubs = self._build_trendline(data['Publications'])
        trendline_cites = self._build_trendline(data['Citations'])

        # 创建图表（两个子图垂直排列）
        fig, (ax1, ax2) = plt.subplots(nrows=2, ncols=1, figsize=(10, 12))

        # --- 子图A: 发文量 ---
        bars1 = ax1.bar(data['Year'], data['Publications'],
                       color=self.colors['publications'],
                       edgecolor='black',
                       linewidth=0.5)
        ax1.bar_label(bars1, padding=3, fontsize=9, color=self.colors['text'])
        if trendline_pubs is not None:
            ax1.plot(data['Year'], trendline_pubs,
                    color=self.colors['trend_publications'],
                    linestyle='--',
                    linewidth=2.5,
                    label='Trend Line')

        # 样式设置
        ax1.spines['top'].set_visible(False)
        ax1.spines['right'].set_visible(False)
        ax1.spines['left'].set_color(self.colors['subtle'])
        ax1.spines['bottom'].set_color(self.colors['subtle'])
        ax1.grid(axis='y', linestyle='--', alpha=0.6, color=self.colors['subtle'])
        ax1.tick_params(axis='both', direction='out',
                       colors=self.colors['subtle'],
                       labelcolor=self.colors['text'])

        ax1.set_ylabel('Number of Documents', fontsize=14, labelpad=10,
                      color=self.colors['text'])
        ax1.set_xlabel('Year', fontsize=14, labelpad=10,
                      color=self.colors['text'])
        ax1.set_ylim(0, self._get_axis_upper_bound(data['Publications']))
        ax1.set_xticks(data['Year'])
        plt.setp(ax1.get_xticklabels(), rotation=45, ha="right",
                rotation_mode="anchor")
        if trendline_pubs is not None:
            ax1.legend(loc='upper left', frameon=False, fontsize=12)
        ax1.text(-0.1, 1.05, 'A', transform=ax1.transAxes,
                fontsize=24, fontweight='bold', va='top',
                color=self.colors['text'])

        # --- 子图B: 引用量 ---
        bars2 = ax2.bar(data['Year'], data['Citations'],
                       color=self.colors['citations'],
                       edgecolor='black',
                       linewidth=0.5)
        ax2.bar_label(bars2, padding=3, fontsize=9, color=self.colors['text'])
        if trendline_cites is not None:
            ax2.plot(data['Year'], trendline_cites,
                    color=self.colors['trend_citations'],
                    linestyle='--',
                    linewidth=2.5,
                    label='Trend Line')

        # 样式设置
        ax2.spines['top'].set_visible(False)
        ax2.spines['right'].set_visible(False)
        ax2.spines['left'].set_color(self.colors['subtle'])
        ax2.spines['bottom'].set_color(self.colors['subtle'])
        ax2.grid(axis='y', linestyle='--', alpha=0.6, color=self.colors['subtle'])
        ax2.tick_params(axis='both', direction='out',
                       colors=self.colors['subtle'],
                       labelcolor=self.colors['text'])

        ax2.set_ylabel('Number of Citations', fontsize=14, labelpad=10,
                      color=self.colors['text'])
        ax2.set_xlabel('Year', fontsize=14, labelpad=10,
                      color=self.colors['text'])
        ax2.set_ylim(0, self._get_axis_upper_bound(data['Citations']))
        ax2.set_xticks(data['Year'])
        plt.setp(ax2.get_xticklabels(), rotation=45, ha="right",
                rotation_mode="anchor")
        if trendline_cites is not None:
            ax2.legend(loc='upper left', frameon=False, fontsize=12)
        ax2.text(-0.1, 1.05, 'B', transform=ax2.transAxes,
                fontsize=24, fontweight='bold', va='top',
                color=self.colors['text'])

        plt.tight_layout(pad=3.0)

        # 保存图片
        output_path = Path(output_dir)
        for fmt in ['tiff', 'png']:
            fig.savefig(output_path / f'各年发文量及引用量.{fmt}',
                       dpi=300, bbox_inches='tight',
                       format=fmt, facecolor='white', edgecolor='none')

        plt.close(fig)
        print("  ✓ 各年发文量及引用量组合图已保存")


def generate_publications_citations_analysis(data_dir: str, final_file: Optional[str] = None):
    """
    生成年度发文量及引用量分析

    Args:
        data_dir: 数据目录
        final_file: 可选，显式指定最终分析文件路径

    Returns:
        bool: 是否成功
    """
    data_dir = Path(data_dir)

    # 文件路径 - 优先使用显式传入文件，其次为 Final_Version，再次为 *_only.txt
    resolved_final_file = find_existing_analysis_file(data_dir, final_file)

    # 检查文件
    print("\n检查必要文件...")
    if resolved_final_file is None or not resolved_final_file.exists():
        print("  ✗ 最终数据文件: 未找到 Final_Version.txt 或 *_only.txt")
        print("\n✗ 缺少必要文件，无法生成图表")
        print("提示：请确保工作流已完整执行")
        return False

    print(f"  ✓ 最终数据文件: {resolved_final_file}")
    print("✓ 所有必要文件都存在\n")

    output_dir = data_dir / 'Figures and Tables' / '02 各年发文及引文量'
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"✓ 输出目录: {output_dir}\n")

    # 分析
    print("正在分析数据...")
    analyzer = PublicationCitationAnalyzer()
    publications, citations = analyzer.parse_wos_file(str(resolved_final_file))
    data = analyzer.create_dataframe(publications, citations)

    if data.empty:
        print("✗ 最终数据文件中没有可用于年度图表的有效记录")
        return False

    # 保存数据
    print("正在保存分析结果...")
    csv_file = output_dir / 'publications_citations_data.csv'
    data.to_csv(csv_file, index=False)
    print(f"  ✓ 统计数据: {csv_file.name}")

    # 生成图表
    print("正在生成图表...")
    analyzer.plot_publications(data, str(output_dir))
    analyzer.plot_citations(data, str(output_dir))
    analyzer.plot_combined(data, str(output_dir))

    # 保存代码副本
    import shutil
    code_copy = output_dir / 'plot_publications_citations.py'
    shutil.copy(__file__, code_copy)
    print(f"  ✓ 脚本副本: {code_copy.name}")

    # 最后总结
    print("\n" + "=" * 80)
    print("📊 年度发文量及引用量分析完成！")
    print("=" * 80)
    print(f"\n图表输出目录: {output_dir}")
    print("\n生成的文件:")
    print("  - 各年发文量.tiff/png              - 年度发文量图（带趋势线）")
    print("  - 各年引用量.tiff/png              - 年度引用量图（带趋势线）")
    print("  - 各年发文量及引用量.tiff/png      - 组合图（带趋势线）")
    print("  - publications_citations_data.csv  - 统计数据（Excel可读）")
    print("  - plot_publications_citations.py   - 绘图脚本副本")
    print("\n✓ 图表已保存到: {}\n".format(output_dir))

    return True


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        generate_publications_citations_analysis(sys.argv[1])
    else:
        print("Usage: python3 plot_publications_citations.py <data_dir>")
