# Bibliometric Data Consolidation Tool

[English](README.md) | 中文 | [日本語](README.ja.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3](https://img.shields.io/badge/python-3-blue.svg)](https://www.python.org/)
[![Version](https://img.shields.io/badge/version-5.2.0-green.svg)](CHANGELOG.md)

一个**以 WOS 为主标准的 Scopus→WOS 转换与整合系统**，用于把 WOS 与 Scopus 整理为统一、可直接用于文献计量分析的最终数据库。

本项目不把自己定位成“普通数据清洗工具”。它的核心任务是：尽量把 Scopus 推向 **Web of Science (WOS)** 风格，再把 WOS 与 Scopus 合并成一个统一语料。

## 核心目标

1. 尽可能把 Scopus 转成 WOS 风格
2. 以 WOS 作为主要对齐标准
3. 做好 WOS / Scopus 去重与合并
4. 让 Scopus 独有记录在转换后也能自然混入 WOS 语料
5. 输出适合 **VOSviewer**、**CiteSpace**、**Bibliometrix** 直接使用的统一数据库

## 系统思路

当前流程结合了**本地规则**、**当前输入 WOS 语料校准**和可选的 AI 步骤。

- **本地结构转换**：把 `scopus.csv` 转为 WOS 风格纯文本结构
- **WOS 语料校准**：以当前 `wos.txt` 作为主参考风格，尤其用于机构与组织字段对齐
- **保守的 `C3` 恢复**：利用 WOS/Scopus 重复文献做规则校准，但只有当原始 Scopus affiliation 证据支持时才补 companion / parent 级组织
- **WOS 优先合并**：WOS 与 Scopus 重复时优先保留信息更完整的 WOS 记录
- **可选 AI 分支**：启用后补充期刊、国家等标准化和机构补全

## 设计边界

本项目刻意**不做**以下事情：

- 不按 DOI 直接把 WOS 的 `C3` 字段拷贝到 Scopus 转换结果里
- 不依赖外部机构权威数据库作为主真值来源
- 不把重复对当成“逐字段偷用 WOS”的捷径
- 不回到全局共现乱补 companion 的激进策略

也就是说，WOS/Scopus 重复文献只用于**规则校准与验证**，不是直接覆盖 Scopus 字段。

## 入口方式

项目提供两个等价 CLI 入口：

- `python3 run_ai_workflow.py ...`：兼容入口，最适合直接复制
- `python3 scripts/run_workflow.py ...`：兼容脚本入口

如果你已经执行过：

```bash
pip install -e .
```

也可以直接使用包入口：

```bash
bibliometrics --data-dir Example --no-ai
```

如果你更喜欢图形界面：

- `python3 gui_app.py`
- 或双击 `启动GUI.command`

如果你安装了 GUI 依赖：

```bash
pip install -e .[gui]
```

也可以直接运行：

```bash
bibliometrics-gui
```

## 可复现实例

仓库自带一个示例数据目录 `Example/`：

```text
Example/
├── wos.txt
└── scopus.csv
```

如果你想做**可复现的本地规则审阅**，建议运行：

```bash
python3 run_ai_workflow.py --data-dir Example --no-ai
```

如果要跑默认完整流程：

```bash
python3 run_ai_workflow.py --data-dir Example
```

## 输入目录要求

你的数据目录中必须包含：

```text
/path/to/your-data/
├── wos.txt
└── scopus.csv
```

## `--no-ai` 的真实含义

`--no-ai` 关闭的是**AI 分支**，但不会关闭本地的 WOS 对齐转换逻辑。

使用 `--no-ai` 时，仍然会保留：

- 本地 Scopus → WOS 风格转换
- 本地 WOS 语料校准
- 本地基于重复对的 `C3` 恢复与合理性保护
- 合并去重
- 语言筛选
- 机构清洗
- 统计分析与报告生成

它会跳过：

- AI WOS 风格标准化
- AI 机构补全

## 主要输出文件

根据参数不同，常见输出包括：

- `scopus_converted_to_wos.txt`
- `scopus_enriched.txt`
- `merged_deduplicated.txt`
- `english_only.txt` 或其他语言筛选结果
- `Final_Version.txt`
- `*_analysis_report.txt`
- `ai_workflow_report.txt`
- `Figures and Tables/`

## 当前验证快照

仓库自带示例已经重新跑过完整流程，并且实际用 WOS/Scopus 重复文献做了对照。

- 输入数据：`Example/wos.txt` + `Example/scopus.csv`
- 重点：保守的 `C3` 对齐与 companion 恢复
- 当前本地 round11 快照：100 组重复对中的 `C3` 差异已从 `24` 降到 `12`

这些结果用于继续优化 `src/bibliometrics/converters/scopus.py` 中的泛化规则，而不是把 WOS 字段硬套回 Scopus 输出。

## 文档入口

建议从以下文档开始：

- `QUICK_START.zh-CN.md`
- `QUICK_START.md`
- `QUICK_START.ja.md`
- `PROJECT_STRUCTURE.md`
- `docs/README.md`
- `docs/WOS标准化说明.md`
- `docs/Scopus数据质量问题分析.md`

`docs/changelogs/`、`docs/release/`、`docs/security/` 主要保留历史上下文，可能包含旧术语、旧流程或旧命令。

## 导入分析工具

### VOSviewer

导入 `Final_Version.txt` 这类最终 WOS 风格纯文本文件。

### CiteSpace

选择 WOS 纯文本导入模式，再选择最终输出文件。

### Bibliometrix

```r
library(bibliometrix)
M <- convert2df("Final_Version.txt", dbsource = "wos", format = "plaintext")
results <- biblioAnalysis(M)
```

## 备注

- 如果启用 AI，请先配置 `GEMINI_API_KEY`
- 如果你要做可复现的本地转换审阅，优先用 `--no-ai`
- 默认机构清洗规则文件是 `config/institution_cleaning_rules_ultimate.json`

## 开发说明

本项目 2026-07 的深度升级由 Anthropic 最先进的 **Claude Fable 5**（Mythos 级模型，能力位于 Claude Opus 之上）通过 Claude Code 完成：

- 多智能体并行代码审查，40+ 项发现，多处**数据丢失 bug** 经实测复现后修复（每个文件丢首条记录、合并输出丢 WC/SC/FU 字段、机构名破坏性截断等）
- 核心转换流程提速约 **15 倍**（Example 全流程约 1 分钟 → 约 4 秒），输出经 md5 逐字节对比确认零回归
- 全套工程化升级：`pyproject.toml` 打包、GitHub Actions CI、lint 清零、回归测试 5 → 19

Fable 5 的深度审查与自我验证工作流，是这轮"零回归"升级的关键。

## 许可证

MIT
