# Bibliometric Data Consolidation Tool

[English](README.md) | [中文](README.zh-CN.md) | 日本語

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3](https://img.shields.io/badge/python-3-blue.svg)](https://www.python.org/)
[![Version](https://img.shields.io/badge/version-5.1.0%2Blocal-green.svg)](CHANGELOG.md)

**WOS を主標準にした Scopus→WOS 変換・統合システム**です。Scopus をできるだけ **Web of Science (WOS)** 風に寄せ、WOS と Scopus を 1 つの解析用コーパスへ統合します。

このプロジェクトは、一般的なデータクリーニング用ツールとしてではなく、**WOS 準拠の変換と統合**を主目的として設計されています。

## 主な目標

1. Scopus を可能な限り WOS 風に変換する
2. WOS を主な整合基準として使う
3. WOS / Scopus の重複除去と統合を安定させる
4. Scopus のみのレコードも WOS 指向コーパスに自然に混ぜる
5. **VOSviewer**、**CiteSpace**、**Bibliometrix** にそのまま渡せる統一データを出力する

## 処理の考え方

現在のワークフローは、**ローカル規則**、**入力された WOS コーパスによる校正**、そして任意の AI ステップを組み合わせています。

- **ローカル構造変換**：`scopus.csv` を WOS 風プレーンテキストに変換
- **WOS コーパス校正**：現在の `wos.txt` を参照スタイルとして使い、特に所属・組織の整合に利用
- **保守的な `C3` 補完**：重複 WOS/Scopus ペアを使って companion / parent 組織の補完規則を校正。ただし元の Scopus affiliation 根拠がある場合に限定
- **WOS 優先マージ**：重複時は情報量の多い WOS を優先
- **任意の AI 分岐**：有効時は国名・誌名の標準化や所属補完を追加

## 明確な境界

このプロジェクトは次のことを意図的に行いません。

- DOI 一致を使って WOS の `C3` をそのまま Scopus 側へコピーしない
- 外部の機関権威データベースに主依存しない
- 重複ペアを使ってレコード単位で WOS フィールドを上書きしない
- ノイズを増やす全体共起ベースの過剰補完へ戻らない

重複ペアは**規則の校正と検証**に使われ、直接的なフィールド流用には使われません。

## エントリー

- `python3 run_ai_workflow.py ...` — 互換エントリー
- `python3 scripts/run_workflow.py ...` — 実際の CLI エントリー

GUI を使う場合：

- `python3 gui_app.py`
- または `启动GUI.command`

## 再現用サンプル

`Example/` に再現用データがあります。

```text
Example/
├── wos.txt
└── scopus.csv
```

ローカル規則中心で再現したい場合：

```bash
python3 run_ai_workflow.py --data-dir Example --no-ai
```

通常の既定ワークフロー：

```bash
python3 run_ai_workflow.py --data-dir Example
```

## `--no-ai` の意味

`--no-ai` は **AI 分岐のみ**を無効化します。ローカルの WOS 指向変換は残ります。

継続して実行されるもの：

- ローカル Scopus → WOS 風変換
- ローカル WOS コーパス校正
- 重複ペアを踏まえた `C3` 補完と妥当性ガード
- マージと重複除去
- 言語フィルタ
- 所属クリーニング
- 解析とレポート生成

無効化されるもの：

- AI による WOS 風標準化
- AI による所属補完

## 主な出力

- `scopus_converted_to_wos.txt`
- `scopus_enriched.txt`
- `merged_deduplicated.txt`
- `english_only.txt` などの言語別ファイル
- `Final_Version.txt`
- `*_analysis_report.txt`
- `ai_workflow_report.txt`
- `Figures and Tables/`

## 現在の検証スナップショット

同梱サンプル `Example/wos.txt` と `Example/scopus.csv` でフルワークフローを再実行し、重複 WOS/Scopus ペアで確認済みです。

- 注力点：保守的な `C3` 整合と companion 補完
- 現在の local round11 では、100 件の重複ペアにおける `C3` 差分が `24` から `12` に改善

これは `src/bibliometrics/converters/scopus.py` の一般規則改善に使われており、WOS フィールドの丸写しではありません。

## ドキュメント案内

- `QUICK_START.ja.md`
- `QUICK_START.md`
- `QUICK_START.zh-CN.md`
- `PROJECT_STRUCTURE.md`
- `docs/README.md`
- `docs/WOS标准化说明.md`
- `docs/Scopus数据质量问题分析.md`

`docs/changelogs/`、`docs/release/`、`docs/security/` は履歴資料です。

## 開発ノート

2026年7月の大規模アップグレードは、Anthropic の最上位モデル **Claude Fable 5**（Mythos クラス、Claude Opus の上位に位置）が Claude Code を通じて実施しました：

- マルチエージェント並列コードレビュー：40件超の指摘、実測で再現した**データ損失バグ**を修正（各ファイル先頭レコードの欠落、マージ時の WC/SC/FU フィールド消失、機関名の破壊的切り詰めなど）
- コア変換パイプラインを約 **15倍** 高速化（Example 実行：約1分 → 約4秒）、md5 比較で出力のバイト単位一致を確認
- エンジニアリング全般の刷新：`pyproject.toml` パッケージング、GitHub Actions CI、lint エラーゼロ、回帰テスト 5 → 19

Fable 5 の深いレビューと自己検証ワークフローが、リグレッションゼロのアップグレードを支えました。

## ライセンス

MIT
