# rotation-planner v2

HTMX + FastAPI + Jinja2 で再設計した輪作計画アプリ。

## セットアップ

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
python -m scripts.init_db --username admin --password <好きなパスワード>
uvicorn app.main:app --reload
```

ブラウザで `http://localhost:8000/` を開くと Basic auth ダイアログ。

### FAMIC 作物データの取込 (任意だが推奨)

作物名の原点は農薬登録 (FAMIC) の作物名。`/my-crops` で FAMIC から作物を検索・採用できる。

FAMIC の公開データ (https://www.acis.famic.go.jp/ddownload/index.htm) から
`登録基本部.xls` / `登録適用部一.xls` / `登録適用部二.xls` を取得し、
`data/famic/` に `basic.xls` / `usage1.xls` / `usage2.xls` として置いてから:

```bash
python -m scripts.import_famic
```

未取込でも動作する (その場合 `/my-crops` は「マスタから追加」のみ)。
`data/famic/` は git 管理外。

## 構成

- `db_schema.sql` — v1 から流用したスキーマ (ブループリント)
- `rotation_planner/` — v1 から持ち越したドメインライブラリ (最適化・KML 解析等)
- `app/` — HTMX + FastAPI Web 層 (新規)
- `tests/` — pytest

## v1 との違い

- JWT 廃止 → HTTP Basic auth
- React 廃止 → HTMX (サーバレンダリング)
- ほ場ポリゴン描画のみ Leaflet を独立島として残す

## ドキュメント

詳細は `docs/`:

- [`docs/architecture.md`](docs/architecture.md) — スタック / 設計判断 / ガッチャ集
- [`docs/features.md`](docs/features.md) — 全機能の URL と概要
- [`docs/schema.md`](docs/schema.md) — DB テーブルと値の形式
- [`docs/csv-formats.md`](docs/csv-formats.md) — CSV / KML の列仕様

## PDF にロゴを入れる

`data/logo.png` (もしくは `.jpg` / `.gif`) を置けば、計画 PDF と防除記録 PDF
のヘッダに自動で表示されます。22mm×22mm に縦横比保持で収まります。
ファイルがなければロゴなしで出力。`data/` は gitignore 対象なのでリポジトリに
コミットされません。
