#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档类型分析和可视化

自动从WOS文件中提取文档类型统计并生成可视化图表
"""

import pandas as pd
import matplotlib.pyplot as plt
import re
from pathlib import Path
from typing import Dict, Optional

from ..utils.paths import find_existing_analysis_file
from ..utils.wos_text import split_wos_records


class DocumentTypeAnalyzer:
    def __init__(self):
        """初始化分析器"""
        self._setup_plot_style()
        self._setup_color_palette()

    def _setup_plot_style(self):
        """设置图表样式"""
        try:
            plt.rcParams['font.family'] = 'Arial'
        except Exception:
            pass
        plt.rcParams['axes.labelsize'] = 14
        plt.rcParams['xtick.labelsize'] = 12
        plt.rcParams['ytick.labelsize'] = 12
        plt.rcParams['legend.fontsize'] = 12
        plt.rcParams['figure.titlesize'] = 22
        plt.rcParams['axes.titlesize'] = 18
        plt.rcParams['axes.titleweight'] = 'bold'
        plt.rcParams['axes.labelweight'] = 'bold'
        plt.style.use('seaborn-v0_8-whitegrid')

    def _setup_color_palette(self):
        """设置颜色"""
        self.palette = {
            'Article': '#1f77b4',
            'Review': '#ff7f0e',
        }

    def parse_wos_file(self, file_path: str, min_year: int = None, max_year: int = None) -> Dict[str, int]:
        """解析WOS文件，统计文档类型

        Args:
            file_path: WOS文件路径
            min_year: 最小年份（可选，用于筛选）
            max_year: 最大年份（可选，用于筛选）
        """
        counts = {'Article': 0, 'Review': 0}

        with open(file_path, encoding='utf-8-sig') as f:
            content = f.read()

        records = split_wos_records(content)  # 兼容头部后有/无空行两种形态

        for record in records:
            if record.strip():
                match = re.search(r'^J\s*$', record, re.MULTILINE)
                if match:
                    # 如果指定了年份范围，先检查年份
                    if min_year is not None or max_year is not None:
                        py_match = re.search(r'^PY\s+(\d{4})', record, re.MULTILINE)
                        if py_match:
                            year = int(py_match.group(1))
                            # 年份不在范围内，跳过
                            if min_year and year < min_year:
                                continue
                            if max_year and year > max_year:
                                continue
                        else:
                            # 没有年份信息，跳过
                            continue

                    # 查找DT字段
                    dt_match = re.search(r'^DT\s+(.+?)$', record, re.MULTILINE)
                    if dt_match:
                        doc_type = dt_match.group(1).strip()
                        if 'Article' in doc_type:
                            counts['Article'] += 1
                        elif 'Review' in doc_type:
                            counts['Review'] += 1

        return counts

    def create_data_from_files(self, wos_file: str, scopus_file: str, final_file: str,
                               min_year: int = None, max_year: int = None) -> pd.DataFrame:
        """从三个文件中提取数据

        Args:
            wos_file: WOS 文件路径
            scopus_file: Scopus 转换后文件路径
            final_file: 最终文件路径
            min_year: 最小年份（可选）
            max_year: 最大年份（可选）
        """
        # 为了兼容 workflow 与独立调用，三个输入都允许再次应用年份筛选。
        wos_counts = self.parse_wos_file(wos_file, min_year, max_year)
        scopus_counts = self.parse_wos_file(scopus_file, min_year, max_year)
        final_counts = self.parse_wos_file(final_file, min_year, max_year)

        data = pd.DataFrame({
            'Article_Type': ['Article', 'Review'],
            'WoS_Count': [wos_counts['Article'], wos_counts['Review']],
            'Scopus_Count': [scopus_counts['Article'], scopus_counts['Review']],
            'Final_Count': [final_counts['Article'], final_counts['Review']]
        })

        return data

    def plot_distribution(self, data: pd.DataFrame, output_dir: str):
        """绘制文档类型分布图"""
        fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(22, 8))

        donut_width = 0.4
        wedge_props = {'width': donut_width, 'edgecolor': 'white', 'linewidth': 2}
        text_props = {'fontsize': 16, 'fontweight': 'bold'}

        # Web of Science
        data1 = data[['Article_Type', 'WoS_Count']].rename(columns={'WoS_Count': 'Count'})
        total1 = int(data1['Count'].sum())
        if total1 > 0:
            colors1 = [self.palette[cat] for cat in data1['Article_Type']]
            labels1 = [f"{row['Article_Type']}\n(n={int(row['Count'])})" for _, row in data1.iterrows()]
            ax1.pie(data1['Count'], labels=labels1, colors=colors1, autopct='%1.1f%%',
                    startangle=90, wedgeprops=wedge_props, textprops=text_props, pctdistance=0.8)
            ax1.text(0, 0, f'n={total1}', ha='center', va='center', fontsize=30, fontweight='bold')
        else:
            ax1.text(0.5, 0.5, 'No Data', ha='center', va='center', fontsize=20,
                    transform=ax1.transAxes, color='gray')
        ax1.set_title('Web of Science', pad=20)

        # Scopus
        data2 = data[['Article_Type', 'Scopus_Count']].rename(columns={'Scopus_Count': 'Count'})
        total2 = int(data2['Count'].sum())
        if total2 > 0:
            colors2 = [self.palette[cat] for cat in data2['Article_Type']]
            labels2 = [f"{row['Article_Type']}\n(n={int(row['Count'])})" for _, row in data2.iterrows()]
            ax2.pie(data2['Count'], labels=labels2, colors=colors2, autopct='%1.1f%%',
                    startangle=90, wedgeprops=wedge_props, textprops=text_props, pctdistance=0.8)
            ax2.text(0, 0, f'n={total2}', ha='center', va='center', fontsize=30, fontweight='bold')
        else:
            ax2.text(0.5, 0.5, 'No Data', ha='center', va='center', fontsize=20,
                    transform=ax2.transAxes, color='gray')
        ax2.set_title('Scopus', pad=20)

        # Final Dataset
        data3 = data[['Article_Type', 'Final_Count']].rename(columns={'Final_Count': 'Count'})
        total3 = int(data3['Count'].sum())
        if total3 > 0:
            colors3 = [self.palette[cat] for cat in data3['Article_Type']]
            labels3 = [f"{row['Article_Type']}\n(n={int(row['Count'])})" for _, row in data3.iterrows()]
            ax3.pie(data3['Count'], labels=labels3, colors=colors3, autopct='%1.1f%%',
                    startangle=90, wedgeprops=wedge_props, textprops=text_props, pctdistance=0.8)
            ax3.text(0, 0, f'n={total3}', ha='center', va='center', fontsize=30, fontweight='bold')
        else:
            ax3.text(0.5, 0.5, 'No Data', ha='center', va='center', fontsize=20,
                    transform=ax3.transAxes, color='gray')
        ax3.set_title('Final Dataset', pad=20)

        # 设置百分比标签颜色为白色
        for ax in [ax1, ax2, ax3]:
            for text in ax.texts:
                if text.get_text().endswith('%'):
                    text.set_color('white')
                    text.set_fontsize(16)
                    text.set_fontweight('bold')

        fig.suptitle('Distribution of Articles and Reviews Across Databases', y=1.02, fontweight='bold')
        fig.tight_layout(rect=[0, 0, 1, 0.95])

        # 保存图片
        output_path = Path(output_dir)
        for fmt in ['tiff', 'png']:
            fig.savefig(output_path / f'document_types.{fmt}', dpi=300, bbox_inches='tight',
                       format=fmt, facecolor='white', edgecolor='none')

        plt.close(fig)
        print(f"✓ 图表已保存: {output_path}/document_types.tiff 和 .png")


def generate_document_type_analysis(data_dir: str, min_year: int = None, max_year: int = None, final_file: Optional[str] = None):
    """生成文档类型分析

    Args:
        data_dir: 数据目录
        min_year: 最小年份（可选，如果指定则对 WOS 和 Scopus 数据也进行年份筛选）
        max_year: 最大年份（可选，如果指定则对 WOS 和 Scopus 数据也进行年份筛选）
        final_file: 可选，显式指定最终分析文件路径
    """
    data_dir = Path(data_dir)

    # 文件路径（v4.5.0更新：年份过滤已在源头完成）
    wos_file = data_dir / 'wos.txt'

    # Scopus文件：优先使用AI补全后的文件，否则使用转换后的文件
    scopus_file = data_dir / 'scopus_enriched.txt'
    if not scopus_file.exists():
        scopus_file = data_dir / 'scopus_converted_to_wos.txt'

    # 尝试查找最终文件（优先使用显式传入文件，其次为 Final_Version，再次为 *_only.txt）
    final_file = find_existing_analysis_file(data_dir, final_file)

    # 先检查文件是否存在（检查失败就不创建输出目录）
    print("\n检查必要文件...")
    missing_files = []
    if not wos_file.exists():
        missing_files.append(f"  ✗ WOS 文件: {wos_file}")
    else:
        print(f"  ✓ WOS 文件: {wos_file}")

    if not scopus_file.exists():
        missing_files.append(f"  ✗ Scopus 转换文件: {scopus_file}")
    else:
        print(f"  ✓ Scopus 转换文件: {scopus_file}")

    if final_file is None or not final_file.exists():
        missing_files.append("  ✗ 最终数据文件: 未找到 Final_Version.txt 或 *_only.txt")
    else:
        print(f"  ✓ 最终数据文件: {final_file}")

    if missing_files:
        print("\n✗ 缺少必要文件，无法生成图表:")
        for msg in missing_files:
            print(msg)
        print("\n提示：请确保工作流已完整执行")
        return False

    print("✓ 所有必要文件都存在\n")

    # 文件都存在，创建输出目录
    output_dir = data_dir / 'Figures and Tables' / '01 文档类型'
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"✓ 输出目录: {output_dir}\n")

    # 显示年份筛选信息
    if min_year or max_year:
        year_info = f"应用年份筛选: {min_year or '不限'} - {max_year or '不限'}"
        print(f"✓ {year_info}")
    else:
        print("⚠ 未指定年份范围，WOS 和 Scopus 数据将不进行年份筛选")

    # 分析
    analyzer = DocumentTypeAnalyzer()
    data = analyzer.create_data_from_files(str(wos_file), str(scopus_file), str(final_file),
                                          min_year, max_year)

    # 保存数据
    print("正在保存分析结果...")
    csv_file = output_dir / 'document_types_data.csv'
    data.to_csv(csv_file, index=False)
    print(f"  ✓ 统计数据: {csv_file.name}")

    # 生成图表
    print("正在生成图表...")
    analyzer.plot_distribution(data, str(output_dir))
    print("  ✓ 图表文件: document_types.tiff 和 .png")

    # 复制最终数据文件到 data 文件夹（方便直接使用）
    print("正在复制最终数据文件...")
    import shutil
    data_folder = data_dir / 'data'
    data_folder.mkdir(exist_ok=True)
    final_data_output = data_folder / 'download_final_data.txt'
    shutil.copy(final_file, final_data_output)
    print(f"  ✓ 分析数据已复制到: {final_data_output}")

    # 保存代码副本
    code_copy = output_dir / 'plot_document_types.py'
    shutil.copy(__file__, code_copy)
    print(f"  ✓ 脚本副本: {code_copy.name}")

    # 最后总结
    print("\n" + "=" * 80)
    print("📊 文档类型分析完成！")
    print("=" * 80)
    print(f"\n图表输出目录: {output_dir}")
    print("\n生成的文件:")
    print(f"  图表文件夹 ({output_dir.name}):")
    print("    - document_types.tiff           - 高清图表（投稿用）")
    print("    - document_types.png            - PNG图表（预览用）")
    print("    - document_types_data.csv       - 统计数据（Excel可读）")
    print("    - plot_document_types.py        - 绘图脚本副本")
    print(f"\n  data 文件夹 ({data_dir / 'data'}):")
    print("    - download_final_data.txt       - 🆕 最终数据（可直接用于VOSviewer/CiteSpace）")
    print("\n✓ 图表已保存到: {}".format(output_dir))
    print("✓ 分析数据已保存到: {}\n".format(data_dir / 'data' / 'download_final_data.txt'))

    return True


def generate_all_figures(data_dir: str, min_year: int = None, max_year: int = None, final_file: Optional[str] = None):
    """生成所有图表（文档类型 + 年度发文及引用量）

    Args:
        data_dir: 数据目录
        min_year: 最小年份（可选）
        max_year: 最大年份（可选）
        final_file: 可选，显式指定最终分析文件路径

    Returns:
        bool: 是否成功
    """
    print("\n" + "=" * 80)
    print("开始生成所有图表...")
    print("=" * 80)

    success_count = 0
    total_count = 2

    # 1. 生成文档类型分析图
    print("\n[1/2] 文档类型分析")
    if generate_document_type_analysis(data_dir, min_year, max_year, final_file=final_file):
        success_count += 1

    # 2. 生成年度发文及引用量图
    print("\n[2/2] 年度发文及引用量分析")
    try:
        from .plot_citations import generate_publications_citations_analysis
        if generate_publications_citations_analysis(data_dir, final_file=final_file):
            success_count += 1
    except ImportError as e:
        print(f"⚠ 无法导入年度发文及引用量分析模块: {e}")
    except Exception as e:
        print(f"✗ 年度发文及引用量分析失败: {e}")

    # 总结
    print("\n" + "=" * 80)
    print(f"完成！成功生成 {success_count}/{total_count} 组图表")
    print("=" * 80)

    if success_count == total_count:
        data_path = Path(data_dir)
        print("\n✓ 所有图表已生成：")
        print(f"\n  01 文档类型 ({data_path / 'Figures and Tables' / '01 文档类型'}):")
        print("    - document_types.tiff/png")
        print("    - document_types_data.csv")
        print(f"\n  02 各年发文及引文量 ({data_path / 'Figures and Tables' / '02 各年发文及引文量'}):")
        print("    - 各年发文量.tiff/png")
        print("    - 各年引用量.tiff/png")
        print("    - 各年发文量及引用量.tiff/png")
        print("    - publications_citations_data.csv")
        print(f"\n  data 文件夹 ({data_path / 'data'}):")
        print("    - download_final_data.txt")
        print()

    return success_count == total_count


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        # 默认生成所有图表
        generate_all_figures(sys.argv[1])
    else:
        print("Usage: python3 plot_document_types.py <data_dir>")
