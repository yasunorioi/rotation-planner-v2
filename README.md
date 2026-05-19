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

## 構成

- `db_schema.sql` — v1 から流用したスキーマ (ブループリント)
- `rotation_planner/` — v1 から持ち越したドメインライブラリ (最適化・KML 解析等)
- `app/` — HTMX + FastAPI Web 層 (新規)
- `tests/` — pytest

## v1 との違い

- JWT 廃止 → HTTP Basic auth
- React 廃止 → HTMX (サーバレンダリング)
- ほ場ポリゴン描画のみ Leaflet を独立島として残す

## PDF にロゴを入れる

`data/logo.png` (もしくは `.jpg` / `.gif`) を置けば、計画 PDF と防除記録 PDF
のヘッダに自動で表示されます。22mm×22mm に縦横比保持で収まります。
ファイルがなければロゴなしで出力。`data/` は gitignore 対象なのでリポジトリに
コミットされません。
