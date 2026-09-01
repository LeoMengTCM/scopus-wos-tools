#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bibliometric Data Consolidation Tool - 现代化GUI v5.2.0

功能特点：
- 🎨 现代化卡片式设计（支持滚动、窗口调整）
- 📊 实时进度追踪
- 🎯 智能参数配置
- 📝 详细日志输出
- ⚡ 高性能处理
- 📅 年份优先过滤（在源头过滤异常年份）
- ⭐ WOS格式对齐（Scopus独有记录自动对齐WOS标准）
- ✅ API速率限制修复（彻底解决429错误）
- ✅ 关键Bug修复（AI补全C1格式、C3人名过滤）

作者：Meng Linghan
开发工具：Claude Code
日期：2026-01-15
版本：v5.2.0 (Stable Release)
"""

import threading
import logging
from pathlib import Path
from datetime import datetime
import customtkinter as ctk
from tkinter import filedialog, messagebox
import queue

from .. import __version__
from ..application.workflow import AIWorkflow


class ModernCard(ctk.CTkFrame):
    """现代化卡片组件"""

    def __init__(self, master, title, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(
            fg_color=("gray92", "gray17"),
            corner_radius=12,
            border_width=2,
            border_color=("gray80", "gray25")
        )

        # 卡片标题
        self.title_label = ctk.CTkLabel(
            self,
            text=title,
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=("gray10", "gray90")
        )
        self.title_label.pack(padx=18, pady=(12, 8), anchor="w")

        # 分隔线
        separator = ctk.CTkFrame(self, height=2, fg_color=("gray70", "gray30"))
        separator.pack(fill="x", padx=18, pady=(0, 8))


class TextHandler(logging.Handler):
    """自定义日志处理器"""

    def __init__(self, text_widget, queue):
        super().__init__()
        self.text_widget = text_widget
        self.queue = queue

    def emit(self, record):
        msg = self.format(record)
        self.queue.put(msg)


class MultiDatabaseGUI:
    """MultiDatabase 现代化GUI主类"""

    def __init__(self):
        # 设置主题
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # 创建主窗口
        self.root = ctk.CTk()
        self.root.title(f"Bibliometric Data Consolidation Tool v{__version__}")

        # 获取屏幕尺寸并设置合适的窗口大小
        screen_height = self.root.winfo_screenheight()

        # 使用屏幕的80%高度，最小900px
        window_height = max(900, int(screen_height * 0.85))
        window_width = 1300

        self.root.geometry(f"{window_width}x{window_height}")

        # 允许窗口调整大小
        self.root.resizable(True, True)

        # 设置最小窗口大小
        self.root.minsize(1100, 800)

        # 窗口居中
        self.center_window()

        # 配置网格
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        # 日志队列
        self.log_queue = queue.Queue()

        # 变量
        self.input_dir = ctk.StringVar(value="")
        self.output_dir = ctk.StringVar(value="")
        self.year_start = ctk.StringVar(value="2015")
        self.year_end = ctk.StringVar(value="2024")
        self.language = ctk.StringVar(value="English")
        self.enable_ai = ctk.BooleanVar(value=True)
        self.enable_cleaning = ctk.BooleanVar(value=True)
        self.enable_plot = ctk.BooleanVar(value=True)
        self.cleaning_level = ctk.StringVar(value="ultimate")

        # 处理状态
        self.processing = False
        self.current_step = ctk.StringVar(value="就绪")
        self.progress_value = ctk.DoubleVar(value=0)

        # 创建界面
        self.create_widgets()

        # 启动日志更新
        self.update_log()

    def center_window(self):
        """窗口居中显示"""
        self.root.update_idletasks()
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()

        # 获取当前窗口大小
        self.root.update()
        window_width = self.root.winfo_width()
        window_height = self.root.winfo_height()

        # 计算居中位置
        x = (screen_width - window_width) // 2
        y = max(20, (screen_height - window_height) // 2)  # 最小留20px上边距
        self.root.geometry(f"+{x}+{y}")

    def create_widgets(self):
        """创建所有GUI组件"""

        # 创建可滚动的主容器
        scrollable_frame = ctk.CTkScrollableFrame(
            self.root,
            fg_color="transparent",
            scrollbar_button_color=("gray70", "gray30"),
            scrollbar_button_hover_color=("gray60", "gray40")
        )
        scrollable_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        scrollable_frame.grid_columnconfigure(0, weight=1)

        # 内容容器
        main_container = ctk.CTkFrame(scrollable_frame, fg_color="transparent")
        main_container.pack(fill="both", expand=True, padx=10, pady=10)
        main_container.grid_columnconfigure(0, weight=1)

        # ==================== 顶部标题栏 ====================
        self.create_header(main_container)

        # ==================== 文件选择卡片 ====================
        self.create_file_card(main_container)

        # ==================== 参数配置卡片 ====================
        self.create_config_card(main_container)

        # ==================== 进度显示 ====================
        self.create_progress_section(main_container)

        # ==================== 日志输出卡片 ====================
        self.create_log_card(main_container)

        # ==================== 底部控制栏 ====================
        self.create_control_bar(main_container)

    def create_header(self, parent):
        """创建顶部标题栏"""
        header_frame = ctk.CTkFrame(parent, fg_color="transparent")
        header_frame.grid(row=0, column=0, sticky="ew", pady=(0, 12))

        # 主标题
        title = ctk.CTkLabel(
            header_frame,
            text="📊 Bibliometric Data Consolidation Tool",
            font=ctk.CTkFont(size=28, weight="bold"),
            text_color=("#2E86AB", "#4DA8DA")
        )
        title.pack(side="left", padx=5)

        # 版本标签
        version_badge = ctk.CTkLabel(
            header_frame,
            text=f"v{__version__}",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=("#2E86AB", "#1A5F7A"),
            corner_radius=8,
            padx=12,
            pady=4
        )
        version_badge.pack(side="left", padx=8)

        # 特性标签
        features = ctk.CTkLabel(
            header_frame,
            text="✨ AI增强 | 🐛 关键修复 | ⚡ 批量处理 | 📈 专业输出",
            font=ctk.CTkFont(size=12),
            text_color="gray"
        )
        features.pack(side="left", padx=15)

    def create_file_card(self, parent):
        """创建文件选择卡片"""
        card = ModernCard(parent, "📁 文件选择")
        card.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        content = ctk.CTkFrame(card, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=18, pady=(0, 12))
        content.grid_columnconfigure(1, weight=1)

        # 输入文件夹
        ctk.CTkLabel(
            content,
            text="输入文件夹",
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w"
        ).grid(row=0, column=0, padx=(0, 12), pady=6, sticky="w")

        input_frame = ctk.CTkFrame(content, fg_color="transparent")
        input_frame.grid(row=0, column=1, columnspan=2, sticky="ew", pady=6)
        input_frame.grid_columnconfigure(0, weight=1)

        self.input_entry = ctk.CTkEntry(
            input_frame,
            textvariable=self.input_dir,
            placeholder_text="选择包含 wos.txt 和 scopus.csv 的文件夹",
            height=36,
            font=ctk.CTkFont(size=11)
        )
        self.input_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        ctk.CTkButton(
            input_frame,
            text="浏览",
            command=self.browse_input_dir,
            width=90,
            height=36,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=("#2E86AB", "#1A5F7A"),
            hover_color=("#1A5F7A", "#0E3A4A")
        ).grid(row=0, column=1)

        # 输出文件夹
        ctk.CTkLabel(
            content,
            text="输出文件夹",
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w"
        ).grid(row=1, column=0, padx=(0, 12), pady=6, sticky="w")

        output_frame = ctk.CTkFrame(content, fg_color="transparent")
        output_frame.grid(row=1, column=1, columnspan=2, sticky="ew", pady=6)
        output_frame.grid_columnconfigure(0, weight=1)

        self.output_entry = ctk.CTkEntry(
            output_frame,
            textvariable=self.output_dir,
            placeholder_text="留空则输出到输入文件夹",
            height=36,
            font=ctk.CTkFont(size=11)
        )
        self.output_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        ctk.CTkButton(
            output_frame,
            text="浏览",
            command=self.browse_output_dir,
            width=90,
            height=36,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=("#2E86AB", "#1A5F7A"),
            hover_color=("#1A5F7A", "#0E3A4A")
        ).grid(row=0, column=1)

    def create_config_card(self, parent):
        """创建参数配置卡片"""
        card = ModernCard(parent, "⚙️ 处理参数")
        card.grid(row=2, column=0, sticky="ew", pady=(0, 10))

        content = ctk.CTkFrame(card, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=18, pady=(0, 12))

        # 创建两列布局
        left_col = ctk.CTkFrame(content, fg_color="transparent")
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 10))

        right_col = ctk.CTkFrame(content, fg_color="transparent")
        right_col.pack(side="left", fill="both", expand=True, padx=(10, 0))

        # 左列：年份和语言
        self.create_param_section(left_col, "📅 年份范围", [
            ("起始年份", self.year_start, "2015"),
            ("结束年份", self.year_end, "2024")
        ])

        self.create_language_section(left_col)
        self.create_cleaning_section(left_col)

        # 右列：功能开关
        self.create_switches_section(right_col)

    def create_param_section(self, parent, title, params):
        """创建参数输入区域"""
        section = ctk.CTkFrame(parent, fg_color=("gray85", "gray20"), corner_radius=8)
        section.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            section,
            text=title,
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w"
        ).pack(padx=12, pady=(10, 6), anchor="w")

        for label, variable, placeholder in params:
            param_frame = ctk.CTkFrame(section, fg_color="transparent")
            param_frame.pack(fill="x", padx=12, pady=4)

            ctk.CTkLabel(
                param_frame,
                text=label,
                font=ctk.CTkFont(size=11),
                width=70,
                anchor="w"
            ).pack(side="left", padx=(0, 8))

            ctk.CTkEntry(
                param_frame,
                textvariable=variable,
                placeholder_text=placeholder,
                width=110,
                height=32
            ).pack(side="left")

        # 底部padding
        ctk.CTkLabel(section, text="", height=4).pack()

    def create_language_section(self, parent):
        """创建语言选择区域"""
        section = ctk.CTkFrame(parent, fg_color=("gray85", "gray20"), corner_radius=8)
        section.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            section,
            text="🌐 目标语言",
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w"
        ).pack(padx=12, pady=(10, 6), anchor="w")

        lang_frame = ctk.CTkFrame(section, fg_color="transparent")
        lang_frame.pack(fill="x", padx=12, pady=(0, 10))

        ctk.CTkOptionMenu(
            lang_frame,
            variable=self.language,
            values=["English", "Chinese", "German", "French", "Spanish", "Japanese"],
            width=200,
            height=32,
            font=ctk.CTkFont(size=11),
            fg_color=("#2E86AB", "#1A5F7A"),
            button_color=("#1A5F7A", "#0E3A4A"),
            button_hover_color=("#0E3A4A", "#051F2A")
        ).pack()

    def create_cleaning_section(self, parent):
        """创建清洗规则区域"""
        section = ctk.CTkFrame(parent, fg_color=("gray85", "gray20"), corner_radius=8)
        section.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            section,
            text="🧹 清洗规则",
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w"
        ).pack(padx=12, pady=(10, 6), anchor="w")

        clean_frame = ctk.CTkFrame(section, fg_color="transparent")
        clean_frame.pack(fill="x", padx=12, pady=(0, 10))

        ctk.CTkOptionMenu(
            clean_frame,
            variable=self.cleaning_level,
            values=["ultimate (终极)", "enhanced (增强)", "basic (基础)"],
            width=200,
            height=32,
            font=ctk.CTkFont(size=11),
            fg_color=("#2E86AB", "#1A5F7A"),
            button_color=("#1A5F7A", "#0E3A4A"),
            button_hover_color=("#0E3A4A", "#051F2A")
        ).pack()

    def create_switches_section(self, parent):
        """创建功能开关区域"""
        section = ctk.CTkFrame(parent, fg_color=("gray85", "gray20"), corner_radius=8)
        section.pack(fill="both", expand=True)

        ctk.CTkLabel(
            section,
            text="🔧 功能开关",
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w"
        ).pack(padx=12, pady=(10, 8), anchor="w")

        switches = [
            ("✨ AI智能补全机构信息", self.enable_ai,
             "使用Gemini AI自动补全州/省代码、邮编、部门信息"),
            ("🧹 机构名称智能清洗", self.enable_cleaning,
             "合并重复机构、移除噪音词、标准化格式"),
            ("📊 生成专业分析图表", self.enable_plot,
             "自动生成文档类型、年度发文及引用量等图表")
        ]

        for text, variable, desc in switches:
            switch_container = ctk.CTkFrame(section, fg_color="transparent")
            switch_container.pack(fill="x", padx=12, pady=6)

            switch = ctk.CTkSwitch(
                switch_container,
                text=text,
                variable=variable,
                font=ctk.CTkFont(size=11, weight="bold"),
                progress_color=("#2E86AB", "#4DA8DA"),
                button_color=("#2E86AB", "#1A5F7A"),
                button_hover_color=("#1A5F7A", "#0E3A4A")
            )
            switch.pack(anchor="w")

            ctk.CTkLabel(
                switch_container,
                text=desc,
                font=ctk.CTkFont(size=9),
                text_color="gray",
                anchor="w"
            ).pack(anchor="w", padx=(30, 0))

        # 底部padding
        ctk.CTkLabel(section, text="", height=8).pack()

    def create_progress_section(self, parent):
        """创建进度显示区域"""
        progress_frame = ctk.CTkFrame(parent, fg_color="transparent")
        progress_frame.grid(row=3, column=0, sticky="ew", pady=(0, 10))

        # 当前步骤标签
        self.step_label = ctk.CTkLabel(
            progress_frame,
            textvariable=self.current_step,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#2E86AB", "#4DA8DA"),
            anchor="w"
        )
        self.step_label.pack(fill="x", pady=(0, 6))

        # 进度条
        self.progress_bar = ctk.CTkProgressBar(
            progress_frame,
            height=16,
            progress_color=("#2E86AB", "#4DA8DA"),
            variable=self.progress_value
        )
        self.progress_bar.pack(fill="x")
        self.progress_bar.set(0)

    def create_log_card(self, parent):
        """创建日志输出卡片"""
        card = ModernCard(parent, "📋 处理日志")
        card.grid(row=4, column=0, sticky="ew", pady=(0, 10))

        # 日志工具栏
        toolbar = ctk.CTkFrame(card, fg_color="transparent")
        toolbar.pack(fill="x", padx=20, pady=(0, 8))

        ctk.CTkButton(
            toolbar,
            text="🗑️ 清空日志",
            command=self.clear_log,
            width=100,
            height=28,
            font=ctk.CTkFont(size=10),
            fg_color=("gray70", "gray30"),
            hover_color=("gray60", "gray25")
        ).pack(side="right")

        # 日志文本框 - 固定高度
        log_container = ctk.CTkFrame(card, fg_color="transparent")
        log_container.pack(fill="x", padx=20, pady=(0, 15))

        self.log_text = ctk.CTkTextbox(
            log_container,
            height=300,  # 固定高度
            font=ctk.CTkFont(family="Monaco", size=10),
            wrap="word",
            fg_color=("gray90", "gray12"),
            border_width=2,
            border_color=("gray70", "gray25")
        )
        self.log_text.pack(fill="both")

    def create_control_bar(self, parent):
        """创建底部控制栏"""
        control_frame = ctk.CTkFrame(parent, fg_color="transparent")
        control_frame.grid(row=5, column=0, sticky="ew")

        # 开始处理按钮
        self.start_button = ctk.CTkButton(
            control_frame,
            text="🚀 开始处理",
            command=self.start_processing,
            width=180,
            height=45,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color=("#27AE60", "#229954"),
            hover_color=("#229954", "#1D8348")
        )
        self.start_button.pack(side="left", padx=(0, 12))

        # 退出按钮
        ctk.CTkButton(
            control_frame,
            text="❌ 退出",
            command=self.root.quit,
            width=110,
            height=45,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=("#E74C3C", "#C0392B"),
            hover_color=("#C0392B", "#A93226")
        ).pack(side="left")

        # 右侧状态显示
        status_frame = ctk.CTkFrame(control_frame, fg_color="transparent")
        status_frame.pack(side="right")

        self.status_badge = ctk.CTkLabel(
            status_frame,
            text="● 就绪",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#27AE60", "#229954"),
            fg_color=("gray85", "gray20"),
            corner_radius=8,
            padx=18,
            pady=8
        )
        self.status_badge.pack()

    def browse_input_dir(self):
        """浏览输入文件夹"""
        directory = filedialog.askdirectory(title="选择输入文件夹")
        if directory:
            self.input_dir.set(directory)
            if not self.output_dir.get():
                self.output_dir.set(directory)
            self.log_message(f"✓ 已选择输入文件夹: {directory}")

    def browse_output_dir(self):
        """浏览输出文件夹"""
        directory = filedialog.askdirectory(title="选择输出文件夹")
        if directory:
            self.output_dir.set(directory)
            self.log_message(f"✓ 已选择输出文件夹: {directory}")

    def clear_log(self):
        """清空日志"""
        self.log_text.delete("1.0", "end")
        self.log_message("日志已清空")

    def log_message(self, message):
        """添加日志消息"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{timestamp}] {message}\n")
        self.log_text.see("end")

    def update_log(self):
        """定期更新日志"""
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log_message(msg)
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self.update_log)

    def update_progress(self, step_name, progress):
        """更新进度"""
        self.current_step.set(step_name)
        self.progress_value.set(progress)

    def update_status(self, text, color):
        """更新状态标签"""
        self.status_badge.configure(text=f"● {text}", text_color=color)

    def validate_inputs(self):
        """验证输入参数"""
        if not self.input_dir.get():
            messagebox.showerror("错误", "请选择输入文件夹！")
            return False

        input_path = Path(self.input_dir.get())
        if not input_path.exists():
            messagebox.showerror("错误", f"输入文件夹不存在：{input_path}")
            return False

        # 检查必需文件
        wos_file = input_path / "wos.txt"
        scopus_file = input_path / "scopus.csv"

        if not wos_file.exists():
            messagebox.showerror("错误", f"未找到 wos.txt 文件！\n路径：{wos_file}")
            return False

        if not scopus_file.exists():
            messagebox.showerror("错误", f"未找到 scopus.csv 文件！\n路径：{scopus_file}")
            return False

        # 验证年份
        try:
            start_year = int(self.year_start.get())
            end_year = int(self.year_end.get())
            if start_year > end_year:
                messagebox.showerror("错误", "起始年份不能大于结束年份！")
                return False
            if start_year < 1900 or end_year > 2100:
                messagebox.showerror("错误", "年份范围无效！请输入1900-2100之间的年份")
                return False
        except ValueError:
            messagebox.showerror("错误", "年份必须是有效的数字！")
            return False

        return True

    def start_processing(self):
        """开始处理"""
        if self.processing:
            messagebox.showwarning("警告", "正在处理中，请稍候...")
            return

        if not self.validate_inputs():
            return

        # 确认对话框
        year_range = f"{self.year_start.get()}-{self.year_end.get()}"
        message = f"""即将开始处理文献数据：

📁 输入文件夹: {self.input_dir.get()}
📁 输出文件夹: {self.output_dir.get() or '(同输入文件夹)'}
📅 年份范围: {year_range}
🌐 目标语言: {self.language.get()}
✨ AI补全: {'启用' if self.enable_ai.get() else '禁用'}
🧹 机构清洗: {'启用' if self.enable_cleaning.get() else '禁用'}
📊 生成图表: {'是' if self.enable_plot.get() else '否'}

确认开始处理吗？"""

        if not messagebox.askyesno("确认处理", message):
            return

        # 清空日志
        self.clear_log()

        # 禁用开始按钮
        self.processing = True
        self.start_button.configure(
            state="disabled",
            text="⏳ 处理中...",
            fg_color="gray"
        )
        self.update_status("处理中", ("#F39C12", "#E67E22"))
        self.update_progress("正在初始化...", 0.0)

        # 在主线程中快照全部 Tk 变量——Tkinter 变量禁止在工作线程中访问，
        # 后台线程只使用这份普通 dict
        settings = {
            'input_dir': self.input_dir.get(),
            'output_dir': self.output_dir.get(),
            'language': self.language.get(),
            'enable_ai': self.enable_ai.get(),
            'enable_cleaning': self.enable_cleaning.get(),
            'enable_plot': self.enable_plot.get(),
            'cleaning_level': self.cleaning_level.get(),
            'year_range': year_range,
        }

        # 在新线程中执行处理
        thread = threading.Thread(target=self.run_workflow, args=(settings,), daemon=True)
        thread.start()

    def run_workflow(self, settings):
        """在后台线程中运行工作流（settings 为主线程快照的普通 dict）"""
        try:
            # 配置日志
            logger = logging.getLogger()
            logger.setLevel(logging.INFO)

            # 清除现有处理器
            for handler in logger.handlers[:]:
                logger.removeHandler(handler)

            # 添加GUI处理器
            gui_handler = TextHandler(self.log_text, self.log_queue)
            gui_handler.setFormatter(logging.Formatter('%(message)s'))
            logger.addHandler(gui_handler)

            # 确定数据目录
            data_dir = settings['output_dir'] if settings['output_dir'] else settings['input_dir']

            # 如果输入和输出不同，需要先复制文件
            if settings['output_dir'] and settings['output_dir'] != settings['input_dir']:
                import shutil
                output_path = Path(settings['output_dir'])
                output_path.mkdir(parents=True, exist_ok=True)

                self.root.after(0, lambda: self.update_progress("复制输入文件...", 0.05))
                shutil.copy2(Path(settings['input_dir']) / "wos.txt", output_path / "wos.txt")
                shutil.copy2(Path(settings['input_dir']) / "scopus.csv", output_path / "scopus.csv")

                self.log_queue.put("✓ 已复制输入文件到输出文件夹")

            # 确定清洗配置文件
            cleaning_level = settings['cleaning_level'].split()[0]
            cleaning_config = f"config/institution_cleaning_rules_{cleaning_level}.json"

            # 创建工作流（带进度回调）
            year_range = settings['year_range']

            # 定义进度回调函数
            def progress_callback(step_name, progress):
                # 在主线程中更新UI
                self.root.after(0, lambda: self.update_progress(step_name, progress))

            workflow = AIWorkflow(
                data_dir=data_dir,
                language=settings['language'],
                enable_ai=settings['enable_ai'],
                enable_cleaning=settings['enable_cleaning'],
                enable_plot=settings['enable_plot'],  # ⭐ 传入图表开关
                cleaning_config=cleaning_config,
                year_range=year_range,
                progress_callback=progress_callback  # ⭐ 传入进度回调
            )

            # 运行工作流（带实时进度更新，包含图表生成）
            success = workflow.run()

            if success:
                self.log_queue.put("\n" + "=" * 80)
                self.log_queue.put("🎉 处理完成！")
                self.log_queue.put("=" * 80)
                self.log_queue.put(f"\n输出文件位置: {data_dir}")
                self.log_queue.put("\n推荐使用文件:")

                # 根据实际工作流结果确定最终文件
                analysis_file = workflow.cleaned_file if settings['enable_cleaning'] else workflow.filtered_file
                final_file = analysis_file.name
                report_file = f"{analysis_file.stem}_analysis_report.txt"

                self.log_queue.put(f"  ⭐ {final_file} - 导入VOSviewer/CiteSpace")
                if year_range:
                    self.log_queue.put("     （已在源头过滤年份，数据更准确）")
                self.log_queue.put(f"  ⭐ {report_file} - 论文写作参考")
                self.log_queue.put("  ⭐ data/download_final_data.txt - 最终分析数据")
                if settings['enable_plot']:
                    self.log_queue.put("  ⭐ Figures and Tables/ - 所有图表文件")

                self.root.after(0, lambda: self.update_status("完成", ("#27AE60", "#229954")))

                self.root.after(0, lambda: messagebox.showinfo(
                    "处理完成",
                    f"所有数据处理完成！\n\n输出位置:\n{data_dir}\n\n推荐使用:\n{final_file}\n\n✅ 已修复: AI补全C1格式、C3人名过滤\n{'✅ 已过滤年份: ' + year_range if year_range else ''}"
                ))
            else:
                self.log_queue.put("\n❌ 处理失败，请查看日志")
                self.root.after(0, lambda: self.update_status("失败", ("#E74C3C", "#C0392B")))
                self.root.after(0, lambda: self.update_progress("✗ 处理失败", 0.0))
                self.root.after(0, lambda: messagebox.showerror("错误", "处理失败，请查看日志"))

        except Exception as e:
            import traceback
            error_msg = f"错误: {str(e)}\n\n{traceback.format_exc()}"
            self.log_queue.put(f"\n❌ 发生错误:\n{error_msg}")
            # except 块退出后 e 即被删除，而 after() 回调在主线程稍后执行，必须先绑定错误消息
            detail = str(e)
            self.root.after(0, lambda: self.update_status("错误", ("#E74C3C", "#C0392B")))
            self.root.after(0, lambda: self.update_progress("✗ 发生错误", 0.0))
            self.root.after(0, lambda msg=detail: messagebox.showerror("错误", f"处理失败:\n{msg}"))

        finally:
            # 恢复开始按钮
            self.processing = False
            self.root.after(0, lambda: self.start_button.configure(
                state="normal",
                text="🚀 开始处理",
                fg_color=("#27AE60", "#229954")
            ))

    def run(self):
        """运行GUI应用"""
        self.root.mainloop()
