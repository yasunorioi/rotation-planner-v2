# Architecture

## スタック

| 層 | 採用 | 理由 |
|---|---|---|
| Web framework | FastAPI 0.115+ | Pydantic 統合・型ヒント・依存注入が小規模アプリに馴染む |
| 認証 | HTTP Basic (sha256, `secrets.compare_digest`) | JWT 不要、ブラウザネイティブダイアログで済む |
| テンプレ | Jinja2 (server-rendered) | autoescape デフォルト、HTMX と相性◎ |
| クライアント拡張 | HTMX 2.0.4 | JS ビルドなし、`hx-*` 属性で部分置換 |
| 地図 | Leaflet 1.9.4 + Leaflet.draw 1.0.4 (CDN) | ポリゴン編集だけ JS 島として隔離 |
| PDF | reportlab 4 + NotoSansCJK | 日本語フォント自動検出 |
| ストレージ | SQLite (`data/rotation_planner.db`) | 単一ファイル、`sqlite3.backup()` でフルバックアップ可 |
| 最適化 | rotation_planner.app (v1 持ち越し) | OR-Tools CP-SAT、486 テストごと残置 |

## ディレクトリ構成

```
rotation-planner-v2/
├── app/                    # 新規 Web 層
│   ├── main.py             # FastAPI app, lifespan, router 登録
│   ├── auth.py             # Basic auth (CurrentUser = Depends)
│   ├── db.py               # SQLite 接続 + 1回限りマイグレーション
│   ├── optimizer_service.py # ライブラリと DB の橋渡し
│   ├── pdf_service.py      # reportlab ラッパ
│   ├── routes/             # 機能別ルーター
│   ├── templates/          # Jinja2 (HTMX 属性込み)
│   └── static/             # CSS, JS, htmx.min.js
├── rotation_planner/       # v1 持ち越しドメインライブラリ (read-only 扱い)
│   ├── app/                # optimizer / constraints / utils
│   ├── common/             # db / models / year_utils など
│   └── field/              # KML parser / spatial (面積計算)
├── db_schema.sql           # 唯一のスキーマ定義 (idempotent)
├── scripts/init_db.py      # 新規 DB + 初期ユーザー作成
├── tests/                  # pytest (93 件)
└── data/                   # gitignore: DB / logo.png 等の運用データ
```

## 主要な設計判断

### 1. ドメイン層 (rotation_planner/) は触らない
v1 から持ち越したライブラリは 486 テストごと残置。最適化ソルバ・KML パーサ・面積計算など実績済みのコードを `app/*_service.py` 経由で利用。Web 層は薄く保ち、ロジックはライブラリに任せる。

### 2. HTMX で SPA を回避
React は v1 で React Compiler 違反まみれになった反省から不採用。HTMX で部分 HTML を返す方式に。JS は Leaflet 島のみ。

### 3. SQLite 接続は per-request、マイグレーションは per-process
`connect()` 内で `sqlite3.connect()` を毎回開く (軽量)。`_migrated_paths` set でマイグレーションだけ初回のみ。**(過去: 毎リクエスト schema を `executescript` していて INSERT OR IGNORE seed が削除を巻き戻すバグがあった)**。

### 4. 認証はリクエスト毎の DB 照合
JWT のような長寿セッションを持たず、Basic auth ヘッダから毎リクエスト DB で確認 (`secrets.compare_digest` でタイミング攻撃回避)。

### 5. 座標系の規約
- DB 内 `coordinates_json`: 標準 GeoJSON `[lng, lat]` 順
- ライブラリの KML パーサ: `[lat, lng]` 順を返す
- → `app/routes/fields.py` のインポート時に必ず swap、エクスポート時にも逆 swap

### 6. 固定作物 (fixed_crop) の取り扱い
optimizer 本体は触らず、`optimizer_service.py` の post-process で plan dict を上書き。「ここは何があっても牧草」という意思を、ライブラリへの侵襲なく反映。

## マイグレーション戦略

```python
# app/db.py
_migrated_paths: set[str] = set()  # プロセス起動 1 回限り

def _migrate(db_path):
    if not db_path.exists():
        return  # 新規 DB は init_db.py が schema を流す
    # 1. ALTER TABLE 系 (列追加など、idempotent でない手続き)
    if 'fixed_crop' not in fields_cols:
        ALTER TABLE fields ADD COLUMN fixed_crop TEXT
    # 2. CREATE TABLE IF NOT EXISTS + INSERT OR IGNORE seed は schema を flow
    executescript(db_schema.sql)
```

スキーマ変更時は `db_schema.sql` を更新 + 必要なら ALTER 行を `_migrate()` に追加。

## ガッチャ集

- **HTMX swap が見えない**: hx-target の DOM が存在するか確認。`htmx-request` クラスが残ったまま = swap 失敗。
- **Form のボタン**: type="submit" を明示 + 緑強調 (`form button[type='submit']`)。「保存ボタンがない」と誤認されないため。
- **追加ボタンは table の上**: テーブルが長くなると下に隠れるため、`#X-form-slot` を table より前に。
- **httpx data=list-of-tuples は要注意**: DeprecationWarning でフォーム送信されない。dict-of-lists を使う。
- **route 順序**: 同 path-prefix で literal path は `/{param}` より先に declare。
- **GeoJSON 座標順**: 取り込み時に `[lat,lng]` → `[lng,lat]` スワップ必須。
