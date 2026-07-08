# Bibliometric Data Consolidation Tool

English | [中文](README.zh-CN.md) | [日本語](README.ja.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3](https://img.shields.io/badge/python-3-blue.svg)](https://www.python.org/)
[![Version](https://img.shields.io/badge/version-5.1.0%2Blocal-green.svg)](CHANGELOG.md)

A **WOS-guided Scopus→WOS conversion and consolidation system** for bibliometric analysis.

This repository is not positioned as a generic data-cleaning project. Its main job is to push Scopus records as close as possible to **Web of Science (WOS)** style, then merge WOS and Scopus into one unified, analysis-ready corpus.

## Core goals

1. Convert Scopus toward WOS style as far as the source data allows
2. Use WOS as the primary alignment standard
3. Deduplicate and merge WOS and Scopus consistently
4. Let Scopus-only records blend naturally into a WOS-oriented corpus
5. Output a unified database ready for tools such as **VOSviewer**, **CiteSpace**, and **Bibliometrix**

## How the system works

The pipeline combines **local rules**, **current-input WOS corpus calibration**, and optional AI steps.

- **Local structural conversion**: converts `scopus.csv` into WOS-style plain text records
- **WOS-corpus calibration**: uses the current `wos.txt` as the reference style, especially for affiliation and organization alignment
- **Conservative `C3` recovery**: calibrates missing companion / parent organizations from duplicate WOS/Scopus pairs, but only when the raw Scopus affiliation evidence supports the recovery
- **WOS-first merge**: keeps the richer WOS record when WOS and Scopus duplicates are merged
- **Optional AI branch**: adds journal / country normalization and institution enrichment when enabled

## Important boundaries

This project intentionally does **not** do the following:

- It does **not** copy a matched WOS `C3` field directly into the converted Scopus record
- It does **not** depend on an external institution authority database as the primary source of truth
- It does **not** use duplicate pairs as a shortcut to overwrite Scopus record fields one by one
- It does **not** reintroduce aggressive global co-occurrence filling that adds noisy companions everywhere

Duplicate WOS/Scopus pairs are used for **rule calibration and validation**, not for direct record-level field theft.

## Entry points

Two equivalent CLI entry points are available:

- `python3 run_ai_workflow.py ...` — compatibility entry, easiest to copy
- `python3 scripts/run_workflow.py ...` — compatibility script entry

After an editable install:

```bash
pip install -e .
```

you can also use the packaged entry point:

```bash
bibliometrics --data-dir Example --no-ai
```

If you prefer a GUI:

- `python3 gui_app.py`
- or double-click `启动GUI.command`

After installing the GUI extra:

```bash
pip install -e .[gui]
```

you can also launch:

```bash
bibliometrics-gui
```

## Reproducible example

A bundled example dataset is included in `Example/`:

```text
Example/
├── wos.txt
└── scopus.csv
```

For a deterministic local review of the WOS-guided conversion and merge logic, run:

```bash
python3 run_ai_workflow.py --data-dir Example --no-ai
```

For the default workflow with the AI branch enabled:

```bash
python3 run_ai_workflow.py --data-dir Example
```

## Required input layout

Your data directory must contain:

```text
/path/to/your-data/
├── wos.txt
└── scopus.csv
```

## What `--no-ai` really means

`--no-ai` disables the **AI branch**, but it does **not** disable the local WOS-guided conversion logic.

With `--no-ai`, the workflow still keeps:

- local Scopus → WOS-style conversion
- local WOS-corpus calibration
- local duplicate-aware `C3` recovery and plausibility guards
- merge and deduplication
- language filtering
- institution cleaning
- analysis and report generation

It skips:

- AI-based WOS-style normalization
- AI-based institution enrichment

## Main outputs

Depending on options, the workflow typically produces:

- `scopus_converted_to_wos.txt`
- `scopus_enriched.txt`
- `merged_deduplicated.txt`
- `english_only.txt` or another language-filtered file
- `Final_Version.txt`
- `*_analysis_report.txt`
- `ai_workflow_report.txt`
- `Figures and Tables/`

## Current validation snapshot

The bundled example has been rerun locally through the full workflow and reviewed on duplicate WOS/Scopus pairs.

- Input pair: `Example/wos.txt` + `Example/scopus.csv`
- Focus: conservative `C3` alignment and companion recovery
- Current local review snapshot: duplicate-pair `C3` differences on 100 overlapping pairs improved from `24` to `12` by round11 iteration

This validation is used to refine general rules in `src/bibliometrics/converters/scopus.py`, not to hard-copy WOS fields into Scopus outputs.

## Documentation map

Start here for current usage:

- `QUICK_START.md`
- `QUICK_START.zh-CN.md`
- `QUICK_START.ja.md`
- `PROJECT_STRUCTURE.md`
- `docs/README.md`
- `docs/WOS标准化说明.md`
- `docs/Scopus数据质量问题分析.md`

Historical notes under `docs/changelogs/`, `docs/release/`, and `docs/security/` are kept for context but may contain older wording or workflow details.

## Import into analysis tools

### VOSviewer

Import the final WOS-style plain text file such as `Final_Version.txt`.

### CiteSpace

Use the WOS plain text import mode and select the final output file.

### Bibliometrix

```r
library(bibliometrix)
M <- convert2df("Final_Version.txt", dbsource = "wos", format = "plaintext")
results <- biblioAnalysis(M)
```

## Notes

- If AI is enabled, configure `GEMINI_API_KEY` first
- If you want reproducible local conversion review, prefer `--no-ai`
- The default institution-cleaning rules file is `config/institution_cleaning_rules_ultimate.json`

## License

MIT
