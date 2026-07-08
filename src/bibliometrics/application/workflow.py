import csv
import logging
import shutil
import time
from typing import Optional

logger = logging.getLogger(__name__)

# 导入各个模块
from ..converters.batch import EnhancedConverterBatchV2
from ..standardizers.enrichment import InstitutionEnricherV2
from ..gemini_config import GeminiConfig
from ..pipeline.merge import MergeDeduplicateTool
from ..filters.language import LanguageFilter
from ..analysis.records import RecordAnalyzer
from ..standardizers.institutions import InstitutionCleaner
from ..filters.year import YearFilter
from .models import StepRecord, WorkflowOptions
from .reporting import build_workflow_report, write_workflow_report


def load_generate_all_figures():
    """按需加载绘图模块，避免 CLI 启动时额外初始化 matplotlib。"""
    try:
        from ..analysis.plot_types import generate_all_figures
        return generate_all_figures
    except ImportError as exc:
        logger.warning(f"plot_types 模块未找到，图表生成功能将被禁用: {exc}")
        return None


class AIWorkflow:
    """AI增强的完整工作流"""

    def __init__(self, data_dir: str, language: str = 'English', enable_ai: bool = True,
                 enable_cleaning: bool = True, cleaning_config: str = 'config/institution_cleaning_rules_ultimate.json',
                 year_range: Optional[str] = None, enable_plot: bool = True, progress_callback=None):
        """
        初始化工作流

        Args:
            data_dir: 数据目录（包含wos.txt和scopus.csv）
            language: 目标语言（默认English）
            enable_ai: 是否启用AI补全（默认True）
            enable_cleaning: 是否启用机构清洗（默认True）
            cleaning_config: 清洗规则配置文件（默认使用终极版规则）
            year_range: 年份范围过滤（格式: YYYY-YYYY，如2015-2024）
            enable_plot: 是否生成图表（默认True）
            progress_callback: 进度回调函数，接收(step_name: str, progress: float)参数
        """
        self.options = WorkflowOptions(
            data_dir=data_dir,
            language=language,
            enable_ai=enable_ai,
            enable_cleaning=enable_cleaning,
            cleaning_config=cleaning_config,
            year_range=year_range,
            enable_plot=enable_plot,
            progress_callback=progress_callback,
        )
        self.paths = self.options.build_paths()

        # 兼容现有调用方，保留原有属性名
        self.data_dir = self.options.data_dir
        self.language = self.options.language
        self.enable_ai = self.options.enable_ai
        self.enable_cleaning = self.options.enable_cleaning
        self.enable_plot = self.options.enable_plot
        self.cleaning_config = self.options.cleaning_config
        self.year_range = self.options.year_range
        self.progress_callback = self.options.progress_callback

        self.wos_file = self.paths.wos_file
        self.scopus_file = self.paths.scopus_file
        self.wos_year_filtered = self.paths.wos_year_filtered
        self.scopus_year_filtered = self.paths.scopus_year_filtered
        self.scopus_converted = self.paths.scopus_converted
        self.scopus_enriched = self.paths.scopus_enriched
        self.merged_file = self.paths.merged_file
        self.filtered_file = self.paths.filtered_file
        self.cleaned_file = self.paths.cleaned_file
        self.report_file = self.paths.report_file

        # 统计信息
        self.stats = {
            'start_time': time.time(),
            'steps': []
        }

    def _record_step(
        self,
        step: int,
        name: str,
        status: str,
        *,
        output: Optional[str] = None,
        error: Optional[str] = None,
        **details,
    ) -> None:
        self.stats['steps'].append(
            StepRecord(
                step=step,
                name=name,
                status=status,
                output=output,
                error=error,
                details=details,
            ).as_dict()
        )

    def _year_range_bounds(self) -> Optional[tuple[int, int]]:
        return self.options.parse_year_range()

    def _update_progress(self, step_name: str, progress: float):
        """更新进度（如果提供了回调函数）"""
        if self.progress_callback:
            try:
                self.progress_callback(step_name, progress)
            except Exception as e:
                logger.warning(f"进度回调失败: {e}")

    def check_files(self) -> bool:
        """检查必需文件是否存在"""
        logger.info("=" * 80)
        logger.info("步骤0: 检查输入文件")
        logger.info("=" * 80)

        if not self.wos_file.exists():
            logger.error(f"✗ WOS文件不存在: {self.wos_file}")
            return False

        if not self.scopus_file.exists():
            logger.error(f"✗ Scopus文件不存在: {self.scopus_file}")
            return False

        logger.info(f"✓ WOS文件: {self.wos_file}")
        logger.info(f"✓ Scopus文件: {self.scopus_file}")
        logger.info("")

        return True

    def step1_filter_wos_by_year(self) -> bool:
        """步骤1: 年份范围过滤WOS数据（如果启用）"""
        logger.info("=" * 80)
        logger.info("步骤1: 年份范围过滤WOS数据")
        logger.info("=" * 80)

        try:
            min_year, max_year = self._year_range_bounds() or (None, None)
            if min_year is None or max_year is None:
                raise ValueError("未提供年份过滤范围")

            logger.info(f"年份范围: {min_year}-{max_year}")

            # 创建年份过滤器
            year_filter = YearFilter(min_year=min_year, max_year=max_year)

            # 生成报告文件名
            report_file = str(self.wos_year_filtered).replace('.txt', '_year_filter_report.txt')

            # 执行过滤
            year_filter.filter_file(str(self.wos_file), str(self.wos_year_filtered), report_file)

            # 获取统计信息
            year_stats = {
                'total_records': year_filter.stats['total_records'],
                'filtered_records': year_filter.stats['filtered_records'],
                'kept_records': year_filter.stats['total_records'] - year_filter.stats['filtered_records'],
                'filter_rate': year_filter.stats['filtered_records'] / year_filter.stats['total_records'] * 100
                              if year_filter.stats['total_records'] > 0 else 0,
                'filtered_years': dict(year_filter.stats['filtered_years'])
            }

            logger.info(f"✓ WOS年份过滤完成: {self.wos_year_filtered}")
            logger.info("")

            self._record_step(
                1,
                'WOS年份范围过滤',
                'success',
                output=str(self.wos_year_filtered),
                year_stats=year_stats,
            )

            return True

        except Exception as e:
            logger.error(f"✗ WOS年份过滤失败: {e}")
            self._record_step(1, 'WOS年份范围过滤', 'failed', error=str(e))
            return False

    def step2_filter_scopus_by_year(self) -> bool:
        """步骤2: 年份范围过滤Scopus CSV数据（如果启用）"""
        logger.info("=" * 80)
        logger.info("步骤2: 年份范围过滤Scopus数据")
        logger.info("=" * 80)

        try:
            min_year, max_year = self._year_range_bounds() or (None, None)
            if min_year is None or max_year is None:
                raise ValueError("未提供年份过滤范围")

            logger.info(f"年份范围: {min_year}-{max_year}")

            # 读取Scopus CSV
            filtered_rows = []
            header = None
            total_records = 0
            filtered_records = 0
            filtered_years = {}

            with open(self.scopus_file, encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                header = reader.fieldnames

                for row in reader:
                    total_records += 1
                    year_str = row.get('Year', '')

                    # 检查年份
                    if year_str and year_str.isdigit():
                        year = int(year_str)
                        if min_year <= year <= max_year:
                            filtered_rows.append(row)
                        else:
                            filtered_records += 1
                            filtered_years[year_str] = filtered_years.get(year_str, 0) + 1
                    else:
                        # 没有年份信息，保留
                        filtered_rows.append(row)

            # 写入过滤后的CSV
            with open(self.scopus_year_filtered, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=header)
                writer.writeheader()
                writer.writerows(filtered_rows)

            kept_records = total_records - filtered_records

            logger.info(f"✓ Scopus年份过滤完成: {self.scopus_year_filtered}")
            logger.info(f"  原始记录: {total_records}")
            logger.info(f"  保留记录: {kept_records}")
            logger.info(f"  过滤掉: {filtered_records}")
            logger.info("")

            # 统计信息
            year_stats = {
                'total_records': total_records,
                'filtered_records': filtered_records,
                'kept_records': kept_records,
                'filter_rate': filtered_records / total_records * 100 if total_records > 0 else 0,
                'filtered_years': filtered_years
            }

            self._record_step(
                2,
                'Scopus年份范围过滤',
                'success',
                output=str(self.scopus_year_filtered),
                year_stats=year_stats,
            )

            return True

        except Exception as e:
            logger.error(f"✗ Scopus年份过滤失败: {e}")
            self._record_step(2, 'Scopus年份范围过滤', 'failed', error=str(e))
            return False

    def step3_convert_scopus(self) -> bool:
        """步骤3: 转换Scopus到WOS格式（含WOS标准化）"""
        logger.info("=" * 80)
        logger.info("步骤3: 转换Scopus到WOS格式（含WOS标准化）")
        logger.info("=" * 80)

        try:
            # 如果启用了年份过滤，使用过滤后的文件；否则使用原始文件
            input_file = self.scopus_year_filtered if self.year_range else self.scopus_file

            reference_wos_file = self.wos_year_filtered if self.year_range else self.wos_file

            converter = EnhancedConverterBatchV2(
                str(input_file),
                str(self.scopus_converted),
                enable_standardization=self.enable_ai,
                max_workers=20,
                batch_size=50,
                reference_wos_file=str(reference_wos_file)
            )
            converter.convert()

            if self.enable_ai:
                logger.info(f"✓ 转换完成（已WOS标准化）: {self.scopus_converted}")
            else:
                logger.info(f"✓ 转换完成（未启用AI标准化）: {self.scopus_converted}")
            logger.info("")

            self._record_step(
                3,
                'Scopus格式转换+WOS标准化',
                'success',
                output=str(self.scopus_converted),
            )

            return True

        except Exception as e:
            logger.error(f"✗ 转换失败: {e}")
            self._record_step(3, 'Scopus格式转换+WOS标准化', 'failed', error=str(e))
            return False

    def step4_ai_enrich(self) -> bool:
        """步骤4: AI智能补全机构信息"""
        if not self.enable_ai:
            logger.info("跳过AI补全步骤（未启用）")
            # 直接复制文件
            shutil.copy(self.scopus_converted, self.scopus_enriched)
            return True

        logger.info("=" * 80)
        logger.info("步骤4: AI智能补全机构信息")
        logger.info("=" * 80)

        try:
            # 创建Gemini配置（API key/URL/model 均取环境变量，默认官方端点）
            config = GeminiConfig()

            if not config.validate():
                logger.error("✗ Gemini API配置无效")
                return False

            logger.info(f"API模型: {config.model}")
            logger.info(f"Max tokens: {config.max_tokens}")
            logger.info(f"重试次数: {config.max_retries}")
            logger.info("")

            # 创建补全器
            enricher = InstitutionEnricherV2(config)

            # 补全文件
            stats = enricher.enrich_file(str(self.scopus_converted), str(self.scopus_enriched))

            logger.info(f"✓ AI补全完成: {self.scopus_enriched}")
            logger.info("")

            # 打印统计
            enricher.print_statistics()

            self._record_step(
                4,
                'AI智能补全',
                'success',
                output=str(self.scopus_enriched),
                enrichment_stats=stats,
            )

            return True

        except Exception as e:
            logger.error(f"✗ AI补全失败: {e}")
            self._record_step(4, 'AI智能补全', 'failed', error=str(e))
            return False

    def step5_merge_deduplicate(self) -> bool:
        """步骤5: 合并与去重"""
        logger.info("=" * 80)
        logger.info("步骤5: 合并与去重")
        logger.info("=" * 80)

        try:
            # 使用AI补全后的文件（如果启用）或原始转换文件
            scopus_input = self.scopus_enriched if self.enable_ai else self.scopus_converted

            # 如果启用了年份过滤，使用过滤后的WOS文件；否则使用原始WOS文件
            wos_input = self.wos_year_filtered if self.year_range else self.wos_file

            tool = MergeDeduplicateTool(
                str(wos_input),
                str(scopus_input),
                str(self.merged_file)
            )

            tool.run()  # 执行合并去重

            # 获取统计信息
            stats = {
                'wos_count': tool.stats['wos_count'],
                'scopus_count': tool.stats['scopus_count'],
                'duplicates': tool.stats['scopus_duplicates'],
                'final_count': tool.stats['final_count']
            }

            logger.info(f"✓ 合并去重完成: {self.merged_file}")
            logger.info("")

            self._record_step(
                5,
                '合并与去重',
                'success',
                output=str(self.merged_file),
                merge_stats=stats,
            )

            return True

        except Exception as e:
            logger.error(f"✗ 合并去重失败: {e}")
            self._record_step(5, '合并与去重', 'failed', error=str(e))
            return False

    def step6_filter_language(self) -> bool:
        """步骤6: 语言筛选"""
        logger.info("=" * 80)
        logger.info(f"步骤6: 语言筛选（{self.language}）")
        logger.info("=" * 80)

        try:
            filter_tool = LanguageFilter(
                str(self.merged_file),
                str(self.filtered_file),
                self.language
            )
            filter_tool.run()  # 执行筛选
            stats = filter_tool.stats

            logger.info(f"✓ 语言筛选完成: {self.filtered_file}")
            logger.info("")

            self._record_step(
                6,
                f'语言筛选（{self.language}）',
                'success',
                output=str(self.filtered_file),
                filter_stats=stats,
            )

            return True

        except Exception as e:
            logger.error(f"✗ 语言筛选失败: {e}")
            self._record_step(6, f'语言筛选（{self.language}）', 'failed', error=str(e))
            return False

    def step7_clean_institutions(self) -> bool:
        """步骤7: 机构名称清洗（可选）"""
        if not self.enable_cleaning:
            logger.info("跳过机构清洗步骤（未启用）")
            logger.info("")
            return True

        logger.info("=" * 80)
        logger.info("步骤7: 机构名称清洗")
        logger.info("=" * 80)

        try:
            cleaner = InstitutionCleaner(self.cleaning_config)
            cleaner.run(str(self.filtered_file), str(self.cleaned_file))

            # 获取清洗统计
            cleaning_stats = {
                'total_records': cleaner.stats['total_records'],
                'institutions_before': cleaner.stats['total_institutions_before'],
                'institutions_after': cleaner.stats['total_institutions_after'],
                'unique_before': cleaner.stats['unique_before'],
                'unique_after': cleaner.stats['unique_after'],
                'removed_noise': cleaner.stats['removed_noise'],
                'merged': cleaner.stats['merged_parent_child'],
                'removed_departments': cleaner.stats['removed_departments']
            }

            logger.info(f"✓ 机构清洗完成: {self.cleaned_file}")
            logger.info("")

            self._record_step(
                7,
                '机构名称清洗',
                'success',
                output=str(self.cleaned_file),
                cleaning_stats=cleaning_stats,
            )

            return True

        except Exception as e:
            logger.error(f"✗ 机构清洗失败: {e}")
            self._record_step(7, '机构名称清洗', 'failed', error=str(e))
            return False

    def step8_analyze(self) -> bool:
        """步骤8: 统计分析（只分析一次，分析最终文件）"""
        logger.info("=" * 80)
        logger.info("步骤8: 统计分析")
        logger.info("=" * 80)

        try:
            # 确定最终分析文件：优先使用清洗后的文件，否则使用筛选后的文件
            analysis_file = self.cleaned_file if self.enable_cleaning else self.filtered_file

            analyzer = RecordAnalyzer(str(analysis_file))
            analyzer.analyze()

            # 分析报告文件由 save_detailed_report() 自动生成
            analysis_report_file = str(analysis_file).replace('.txt', '_analysis_report.txt')

            logger.info(f"✓ 统计分析完成: {analysis_report_file}")
            logger.info("")

            self._record_step(8, '统计分析', 'success', output=analysis_report_file)

            return True

        except Exception as e:
            logger.error(f"✗ 统计分析失败: {e}")
            self._record_step(8, '统计分析', 'failed', error=str(e))
            return False

    def generate_report(self):
        """生成工作流报告"""
        logger.info("=" * 80)
        logger.info("生成工作流报告")
        logger.info("=" * 80)

        elapsed_time = time.time() - self.stats['start_time']
        report_text = build_workflow_report(
            options=self.options,
            paths=self.paths,
            steps=self.stats['steps'],
            elapsed_time=elapsed_time,
        )
        write_workflow_report(self.report_file, report_text)

        logger.info(f"✓ 工作流报告已保存: {self.report_file}")
        logger.info("")

        # 打印到控制台
        print(report_text)

    def create_project_structure(self) -> bool:
        """创建项目文件夹结构"""
        logger.info("=" * 80)
        logger.info("步骤7: 创建项目文件夹结构")
        logger.info("=" * 80)

        try:
            # 创建主文件夹
            folders = {
                'Figures and Tables': [
                    '01 文档类型',
                    '02 各年发文及引文量',
                ],
                'data': [],
                'project': []
            }

            for main_folder, subfolders in folders.items():
                main_path = self.data_dir / main_folder
                main_path.mkdir(exist_ok=True)
                logger.info(f"✓ 创建文件夹: {main_folder}")

                for subfolder in subfolders:
                    sub_path = main_path / subfolder
                    sub_path.mkdir(exist_ok=True)
                    logger.info(f"  ✓ 创建子文件夹: {subfolder}")

            logger.info("✓ 项目文件夹结构创建完成")
            logger.info("")
            return True

        except Exception as e:
            logger.error(f"✗ 创建文件夹结构失败: {e}")
            return False

    def step10_generate_document_type_plot(self) -> bool:
        """生成所有图表（文档类型 + 年度发文及引用量）"""
        logger.info("=" * 80)
        logger.info("步骤10: 生成所有图表")
        logger.info("=" * 80)

        generate_all_figures = load_generate_all_figures()
        if generate_all_figures is None:
            logger.warning("⚠ 图表生成功能不可用（缺少依赖）")
            return True

        try:
            # 提取年份范围参数
            min_year = None
            max_year = None
            if self.year_range:
                parsed_range = self._year_range_bounds()
                if parsed_range:
                    min_year, max_year = parsed_range

            # 传递数据目录和年份参数，生成所有图表
            success = generate_all_figures(
                str(self.data_dir),
                min_year,
                max_year,
                final_file=str(self.cleaned_file if self.enable_cleaning else self.filtered_file),
            )
            if success:
                logger.info("✓ 所有图表生成完成")
                logger.info("")
            return success
        except Exception as e:
            logger.error(f"✗ 图表生成失败: {e}")
            return False

    def run(self) -> bool:
        """运行完整工作流"""
        logger.info("")
        logger.info("=" * 80)
        logger.info("AI增强工作流启动")
        logger.info("=" * 80)
        logger.info("")

        # 计算总步骤数
        total_steps = 8  # 基础步骤：3转换 + 4AI + 5合并 + 6语言 + 7清洗 + 8分析 + 9结构 + 10图表
        if self.options.has_year_filter:
            total_steps += 2  # 增加步骤1和2（年份过滤）
        current_step = 0

        # 检查文件
        self._update_progress("正在检查输入文件...", 0.0)
        if not self.check_files():
            return False

        # 步骤1: 年份范围过滤WOS数据（如果启用）⭐ 最优先
        if self.options.has_year_filter:
            current_step += 1
            self._update_progress(f"步骤{current_step}/{total_steps}: 年份过滤WOS数据...", current_step / total_steps)
            if not self.step1_filter_wos_by_year():
                return False

        # 步骤2: 年份范围过滤Scopus数据（如果启用）⭐ 第二优先
        if self.options.has_year_filter:
            current_step += 1
            self._update_progress(f"步骤{current_step}/{total_steps}: 年份过滤Scopus数据...", current_step / total_steps)
            if not self.step2_filter_scopus_by_year():
                return False

        # 步骤3: 转换Scopus（使用过滤后的文件）
        current_step += 1
        self._update_progress(f"步骤{current_step}/{total_steps}: 转换Scopus到WOS格式...", current_step / total_steps)
        if not self.step3_convert_scopus():
            return False

        # 步骤4: AI补全
        current_step += 1
        if self.enable_ai:
            self._update_progress(f"步骤{current_step}/{total_steps}: AI智能补全机构信息...", current_step / total_steps)
        else:
            self._update_progress(f"步骤{current_step}/{total_steps}: 跳过AI补全...", current_step / total_steps)
        if not self.step4_ai_enrich():
            return False

        # 步骤5: 合并去重
        current_step += 1
        self._update_progress(f"步骤{current_step}/{total_steps}: 合并与去重...", current_step / total_steps)
        if not self.step5_merge_deduplicate():
            return False

        # 步骤6: 语言筛选
        current_step += 1
        self._update_progress(f"步骤{current_step}/{total_steps}: 语言筛选（{self.language}）...", current_step / total_steps)
        if not self.step6_filter_language():
            return False

        # 步骤7: 机构清洗（可选）
        current_step += 1
        if self.enable_cleaning:
            self._update_progress(f"步骤{current_step}/{total_steps}: 机构名称清洗...", current_step / total_steps)
        else:
            self._update_progress(f"步骤{current_step}/{total_steps}: 跳过机构清洗...", current_step / total_steps)
        if not self.step7_clean_institutions():
            return False

        # 步骤8: 统计分析（只分析一次，分析最终文件）
        current_step += 1
        self._update_progress(f"步骤{current_step}/{total_steps}: 统计分析...", current_step / total_steps)
        if not self.step8_analyze():
            return False

        # 步骤9: 创建项目文件夹结构
        current_step += 1
        self._update_progress(f"步骤{current_step}/{total_steps}: 创建项目结构...", current_step / total_steps)
        if not self.create_project_structure():
            return False

        # 步骤10: 生成文档类型分析（可选，失败不影响整体流程）
        current_step += 1
        if self.enable_plot:
            self._update_progress(f"步骤{current_step}/{total_steps}: 生成图表...", current_step / total_steps)
            try:
                self.step10_generate_document_type_plot()
            except Exception as e:
                logger.warning(f"⚠ 文档类型分析跳过: {e}")
                logger.info("提示: 如需生成图表，请安装 matplotlib: pip3 install matplotlib")
        else:
            self._update_progress(f"步骤{current_step}/{total_steps}: 跳过图表生成...", current_step / total_steps)
            logger.info("跳过图表生成（未启用）")

        # 生成报告
        self.generate_report()

        self._update_progress("✓ 处理完成！", 1.0)
        logger.info("=" * 80)
        logger.info("✓ 工作流全部完成！")
        logger.info("=" * 80)
        logger.info("")

        return True
