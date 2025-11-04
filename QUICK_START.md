# 快速开始指南

## 🚀 一行命令完成所有处理

### 最简单的使用方式

如果你的数据文件夹中有 `wos.txt` 和 `scopus.csv`，只需要运行：

```bash
python3 run_complete_workflow.py --data-dir "/完整路径/到/你的数据文件夹"
```

例如：
```bash
python3 run_complete_workflow.py --data-dir "/Users/menglinghan/Library/CloudStorage/OneDrive-共享的库-Onedrive/文献计量学/Nano_NSCLC_Immune"
```

**就这么简单！** 脚本会自动完成：
1. ✅ 转换 Scopus 到 WOS 格式
2. ✅ 合并 WOS 和 Scopus 数据
3. ✅ 去除重复文献
4. ✅ 筛选英文文献
5. ✅ 生成详细统计报告

---

## 📂 准备工作

### 1. 确保你的数据文件夹中有这两个文件：

```
/你的数据文件夹/
├── wos.txt        # 从 Web of Science 导出的文件
└── scopus.csv     # 从 Scopus 导出的文件（选择"所有字段"）
```

### 2. 将脚本工具放在合适的位置

确保以下脚本在同一个文件夹中：
- `run_complete_workflow.py` （主脚本）
- `scopus_to_wos_converter.py`
- `merge_deduplicate.py`
- `filter_language.py`

---

## 🎯 你的具体情况

### 数据位置
```
/Users/menglinghan/Library/CloudStorage/OneDrive-共享的库-Onedrive/文献计量学/Nano_NSCLC_Immune/
├── wos.txt
└── scopus.csv
```

### 运行命令

**方式1：在脚本文件夹中运行**
```bash
cd /Users/menglinghan/Desktop/scopus-wos-tools

python3 run_complete_workflow.py --data-dir "/Users/menglinghan/Library/CloudStorage/OneDrive-共享的库-Onedrive/文献计量学/Nano_NSCLC_Immune"
```

**方式2：使用绝对路径运行**
```bash
python3 /Users/menglinghan/Desktop/scopus-wos-tools/run_complete_workflow.py \
  --data-dir "/Users/menglinghan/Library/CloudStorage/OneDrive-共享的库-Onedrive/文献计量学/Nano_NSCLC_Immune"
```

---

## 📊 处理完成后会得到什么？

### 在你的数据文件夹中会生成以下文件：

#### 1. `scopus_converted_to_wos.txt`
- Scopus 转换为 WOS 格式的中间文件
- 可以删除（如果不需要保留）

#### 2. `merged_deduplicated.txt` ⭐
- **WOS + Scopus 合并去重后的完整数据集**
- 包含所有语言的文献
- 可用于完整数据分析

#### 3. `english_only.txt` ⭐⭐⭐ **推荐使用**
- **仅包含英文文献的最终数据集**
- 推荐用于文献计量分析
- 可直接导入 VOSviewer、CiteSpace、Bibliometrix

#### 4. `workflow_complete_report.txt` ⭐⭐⭐ **论文写作必读**
- **详细的统计报告**，包含：
  - WOS 原始数据统计（总数、Article、Review）
  - Scopus 原始数据统计（总数、Article、Review）
  - 合并去重结果（去除了多少重复）
  - 语言分布统计
  - 英文筛选结果（最终多少篇）
  - 论文 Methods 部分的写作参考

---

## 📝 报告示例

运行完成后，你会得到类似这样的报告：

```
================================================================================
文献处理完整工作流统计报告
Literature Processing Workflow - Complete Report
================================================================================

生成时间: 2025-11-04 15:30:25
数据目录: /Users/menglinghan/.../Nano_NSCLC_Immune
目标语言: English

--------------------------------------------------------------------------------
1. WOS原始数据统计
--------------------------------------------------------------------------------
数据来源: wos.txt
总文献数:    500
  - Article (研究论文):     450 ( 90.0%)
  - Review (综述):           50 ( 10.0%)
  - 其他类型:                 0 (  0.0%)

--------------------------------------------------------------------------------
2. Scopus原始数据统计
--------------------------------------------------------------------------------
数据来源: scopus.csv
总文献数:    300
  - Article (研究论文):     270 ( 90.0%)
  - Review (综述):           30 ( 10.0%)
  - 其他类型:                 0 (  0.0%)

--------------------------------------------------------------------------------
3. 合并去重结果
--------------------------------------------------------------------------------
合并前总数:    800 (WOS: 500, Scopus: 300)
识别重复:      150 ( 18.8%)
合并后总数:    650
  - Article (研究论文):     585 ( 90.0%)
  - Review (综述):           65 ( 10.0%)
  - 其他类型:                 0 (  0.0%)

--------------------------------------------------------------------------------
4. 语言分布统计（合并后）
--------------------------------------------------------------------------------
  English             :    600 ( 92.3%) ✓
  Chinese             :     30 (  4.6%)
  German              :     15 (  2.3%)
  French              :      5 (  0.8%)

--------------------------------------------------------------------------------
5. English文献筛选结果
--------------------------------------------------------------------------------
筛选前总数:    650
过滤文献数:     50 (  7.7%)
筛选后总数:    600 ( 92.3%)
  - Article (研究论文):     540 ( 90.0%)
  - Review (综述):           60 ( 10.0%)
  - 其他类型:                 0 (  0.0%)

--------------------------------------------------------------------------------
8. 论文写作参考（Methods部分建议描述）
--------------------------------------------------------------------------------

数据来源与检索策略:
  本研究从Web of Science (WOS)和Scopus两大数据库检索文献。
  WOS检索得到500篇文献，Scopus检索得到300篇文献。

数据整合与去重:
  将两个数据库的文献进行整合，通过DOI和标题匹配识别重复文献。
  共识别150篇重复文献，去重后获得650篇独立文献。

纳入排除标准:
  仅纳入English语言文献，排除其他语言文献50篇。
  最终纳入600篇English文献进行分析，
  其中研究论文(Article)540篇，
  综述(Review)60篇。
```

---

## 🔧 高级选项

### 筛选其他语言

如果你想筛选中文文献：
```bash
python3 run_complete_workflow.py \
  --data-dir "/path/to/data" \
  --language Chinese
```

### 调整日志级别

如果想看更少的输出信息：
```bash
python3 run_complete_workflow.py \
  --data-dir "/path/to/data" \
  --log-level WARNING
```

---

## ⏱️ 预计运行时间

- 小数据集（<500篇）：1-2 分钟
- 中等数据集（500-2000篇）：3-5 分钟
- 大数据集（2000-5000篇）：5-10 分钟

---

## ❓ 常见问题

### Q: 运行失败提示找不到脚本怎么办？

**A:** 确保你在 `scopus-wos-tools` 文件夹中运行命令，或使用完整路径：
```bash
cd /Users/menglinghan/Desktop/scopus-wos-tools
python3 run_complete_workflow.py --data-dir "/你的数据路径"
```

### Q: 提示文件不存在怎么办？

**A:** 检查以下几点：
1. 数据文件夹路径是否正确（注意空格和特殊字符）
2. 文件名是否正确（必须是 `wos.txt` 和 `scopus.csv`）
3. 文件是否真的在那个文件夹中

### Q: 想只转换不筛选语言怎么办？

**A:** 使用旧的分步运行方式：
```bash
# 只转换和合并，不筛选语言
python3 scopus_to_wos_converter.py scopus.csv scopus_converted.txt
python3 merge_deduplicate.py wos.txt scopus_converted.txt merged.txt
```

---

## 📧 需要帮助？

如果遇到问题：
1. 查看生成的日志信息
2. 检查数据文件格式是否正确
3. 确认所有脚本文件在同一目录

---

**祝你的文献计量分析顺利！** 🎉
