# 项目结构说明

**当前定位**：以 WOS 为主标准的 Scopus→WOS 转换与整合系统  
**当前文档状态**：5.2.0  
**更新日期**：2026-09-01

## 项目概览

本项目的目标不是做“泛化清洗”，而是围绕以下主线持续迭代：

- 尽可能把 Scopus 转成 WOS 风格
- 用当前输入的 `wos.txt` 作为主要参考标准
- 通过重复 WOS/Scopus 记录校准转换规则
- 做好去重与合并
- 输出统一、可直接用于文献计量分析的最终数据库

## 根目录结构

```text
.
├── README.md
├── README.zh-CN.md
├── README.ja.md
├── QUICK_START.md
├── QUICK_START.zh-CN.md
├── QUICK_START.ja.md
├── CHANGELOG.md
├── PROJECT_STRUCTURE.md
├── pyproject.toml
├── run_ai_workflow.py
├── gui_app.py
├── 启动GUI.command
├── Example/
├── scripts/
│   └── run_workflow.py
├── src/
│   └── bibliometrics/
│       ├── application/
│       ├── presentation/
│       ├── converters/
│       ├── pipeline/
│       ├── standardizers/
│       ├── filters/
│       ├── analysis/
│       └── utils/
├── config/
├── tests/
├── docs/
└── archive/
```

## 核心入口

- `run_ai_workflow.py`：兼容入口，推荐直接复制命令时使用
- `scripts/run_workflow.py`：兼容脚本入口
- `python3 -m bibliometrics ...`：安装后可用的包入口
- `gui_app.py`：兼容图形界面入口
- `bibliometrics-gui`：安装 `[gui]` 额外依赖后可用的 GUI 入口
- `启动GUI.command`：macOS 下的 GUI 快捷入口

兼容入口保留在根目录，真正的实现代码已收口到 `src/bibliometrics/` 包内。

## 示例与验证目录

- `Example/`：仓库自带可复现实例，包含 `wos.txt` 与 `scopus.csv`
- `tmp_review_round*/`：本地迭代验证输出目录，用于对照每一轮规则调整后的结果
- `tmp_review_probe_*/`：局部探针验证目录，用于快速验证特定规则或异常案例

这些 `tmp_review_*` 目录属于**本地审阅产物**，不是面向最终用户的稳定接口文档。

## 源码目录

核心代码位于 `src/bibliometrics/`。

### `src/bibliometrics/application/`

- 工作流编排
- 工作流配置模型
- 结果报告生成
- CLI 所调用的应用层入口

这层负责“怎么把各模块串起来”，不再和兼容脚本或 GUI 壳代码混在一起。

### `src/bibliometrics/presentation/`

- GUI 启动器
- GUI 界面实现

这层只处理用户交互，不承担业务编排职责。

### `src/bibliometrics/converters/`

与当前项目定位最相关的目录。

- `src/bibliometrics/converters/scopus.py`：Scopus → WOS 风格转换主流程（`ScopusToWosConverter`）
- `src/bibliometrics/converters/batch.py`：批处理转换逻辑
- `src/bibliometrics/converters/author_database.py`：作者标准化辅助数据库逻辑

转换过程中与实例状态无关的纯规则，已按领域拆成独立模块（下划线前缀表示包内实现细节）：

| 模块 | 职责 |
| --- | --- |
| `_normalization.py` | 文本归一化原语：重音折叠、查找键、机构相似度、地址分词（带 `lru_cache`） |
| `_authors.py` | 作者姓名解析、缩写、复合姓氏修复、东亚姓名拆分、人名查找键 |
| `_c3_names.py` | C3 机构名的分类判定（组织级 / 下级单位 / 街道地址）与层级关系判断 |
| `_correspondence.py` | 通讯作者（RP）识别，邮箱证据消歧 |
| `_references.py` | 参考文献（CR）解析与 WOS 格式化 |
| `_fields.py` | 国家名、机构名、页码、ISSN 的 WOS 写法规范化 |

`scopus.py` 中保留的是**依赖实例状态的部分**：配置加载、WOS 参考语料校准、
各类 `reference_*` 映射的构建与查询，以及记录级转换编排。当前 round 迭代最关键的
`C3` 选择与 companion 恢复仍在 `scopus.py` 内，因为它们依赖校准得到的实例状态。

### `src/bibliometrics/pipeline/`

- WOS / Scopus 合并与去重调度
- 与旧导入路径兼容的桥接模块

其中 `pipeline/workflow.py` 现在是兼容层，真正的工作流实现已迁移到 `application/workflow.py`。

### `src/bibliometrics/standardizers/`

- WOS 风格标准化
- AI / Gemini 相关标准化与补全
- 机构名称清洗与标准化

### `src/bibliometrics/filters/`

- 语言筛选
- 年份范围筛选

### `src/bibliometrics/analysis/`

- 文献统计分析
- 图表生成
- 分析报告

### `src/bibliometrics/utils/`

- 路径工具
- 限流与辅助函数
- 其他通用工具

## 配置目录

`config/` 中主要包含：

- `institution_cleaning_rules_ultimate.json`：默认机构清洗规则
- `country_mapping.json`：国家名称映射
- `journal_abbrev.json`：期刊缩写映射
- `biomedical_institutions.json`：机构知识数据
- 各类缓存文件：AI 或标准化阶段生成并复用

## 工程化补充

- `pyproject.toml`：项目打包元数据、依赖声明与 console scripts
- `tests/`：
  - `test_smoke.py`：CLI 解析、工作流模型与兼容导入路径
  - `test_regressions.py`：锁定历史数据丢失 bug 的单元回归
  - `test_golden_output.py`：**输出回归网**——在临时目录跑一遍 `Example --no-ai`
    全流程，比对 `tests/golden/expected.json` 中的产物基线
- `scripts/update_golden.py`：重建输出基线（先打印差异，确认后加 `--yes` 写入）

### 输出基线（golden file）

`tests/golden/expected.json` 为每个产物记录两类指纹：

- **WOS 风格数据产物**：整份文件的 sha256，外加记录条数与每个 WOS 字段标签的出现
  记录数。哈希发现"变了"，字段计数指出"变在哪"——历史上的两类静默数据丢失
  （每个文件丢首条记录、合并输出丢 WC/SC/FU 字段）正是这种形态。
- **报告类产物**：规范化掉数据目录路径与运行耗时后的 sha256。

核心代码改动后跑 `python3 -m unittest discover tests` 即可确认输出零回归。若输出变化
是预期的，用 `scripts/update_golden.py` 重建基线，并在提交信息里说明输出为什么变。

## 当前使用文档

### 根目录入口

- `README.md`
- `README.zh-CN.md`
- `README.ja.md`
- `QUICK_START.md`
- `QUICK_START.zh-CN.md`
- `QUICK_START.ja.md`
- `CHANGELOG.md`
- `PROJECT_STRUCTURE.md`

### `docs/` 当前建议阅读

- `docs/README.md`
- `docs/快速使用指南.md`
- `docs/使用指南.md`
- `docs/数据准备说明.md`
- `docs/WOS标准化说明.md`
- `docs/Scopus数据质量问题分析.md`
- `docs/年份过滤使用指南.md`
- `docs/机构清洗使用指南.md`

### `docs/` 历史或背景材料

- `docs/AI补全系统完整总结.md`
- `docs/changelogs/`
- `docs/release/`
- `docs/security/`
- `docs/internal/`

这些目录和文档保留原始上下文，可能出现旧版本术语、旧流程或旧命令，不应和“当前使用文档”混用。

## 推荐阅读顺序

1. `README.zh-CN.md` / `README.md` / `README.ja.md`
2. `QUICK_START.zh-CN.md` / `QUICK_START.md` / `QUICK_START.ja.md`
3. `docs/README.md`
4. `docs/WOS标准化说明.md`
5. `docs/Scopus数据质量问题分析.md`
6. `docs/使用指南.md`

## 方法边界

为避免误解，当前系统明确遵循以下边界：

- 不是普通“机构清洗项目”
- 不是纯靠外部数据库查表
- 不是按重复 DOI 直接复制 WOS 字段
- 是基于**本地规则 + 当前 WOS 输入校准 + 原始 Scopus affiliation 证据**的保守转换与整合流程

## 仓库整洁约定

- `__pycache__/`、`*.pyc` 不应纳入版本控制
- macOS 资源分叉文件 `._*` 不应纳入版本控制
- `tmp_review_*` 属于本地验证输出，应与源码和正式文档区分管理
- 当前最稳妥的本地入口仍是 `run_ai_workflow.py` 和 `gui_app.py`
- 如需专业化安装方式，优先使用 `pip install -e .` 后的 `bibliometrics` / `bibliometrics-gui`
