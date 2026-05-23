# Database Schema

`db_schema.sql` がスキーマの唯一ソース。`CREATE TABLE IF NOT EXISTS` と `INSERT OR IGNORE` のみで構成され、idempotent。

## マイグレーション

`app/db.py::_migrate()` がプロセス起動時 1 回だけ実行:

1. `PRAGMA table_info(fields)` で `fixed_crop` 列の有無を確認、無ければ `ALTER TABLE ADD COLUMN`
2. `db_schema.sql` を `executescript` (新規テーブル / seed の追従)

新規 DB (`scripts/init_db.py` 経由) は schema 全体がそのまま流れる。

**重要**: `INSERT OR IGNORE` の seed (crop_master 10件, organizations 2件) は schema 内で書かれる。これを毎リクエスト走らせると削除を巻き戻すので、`_migrated_paths` set でプロセス内 1 回限りに。

## テーブル一覧

### 認証系
- **users** — username, password_hash (sha256), display_name, role (admin/ja_staff/farmer), org_id, is_active
- **organizations** — id, name, type, settings_json (seed: id=1 admin org, id=2 JA org)

### ほ場系
- **fields** — user_id FK, field_code, district, name, area_ha, area_a (GENERATED), beet_forbidden, land_category, **coordinates_json** (GeoJSON), **fixed_crop**, notes
  - UNIQUE(user_id, field_code)
  - `fixed_crop` は v2 拡張 (`ALTER TABLE` でマイグレーション)

### 作付履歴
- **crop_history** — field_id FK CASCADE, year (TEXT "R6" 等), crop, is_inferred
  - UNIQUE(field_id, year)

### 輪作計画
- **rotation_plans** — user_id FK CASCADE, name, start_year, end_year, **constraints_json**, **metadata_json**
- **plan_details** — plan_id FK CASCADE, field_id FK CASCADE, year, crop (UNIQUE(plan_id, field_id, year))
  - 現状は未使用 (snapshot に置き換わった)
- **plan_snapshots** (v2 拡張) — plan_id FK CASCADE, taken_at, score, **data_json**, label
  - data_json には past_years/future_years/field_codes/grid を JSON 化して保存
  - grid のキーは tuple なので `"code|year"` 文字列キーに変換

### 作物マスタ
- **crop_master** — name UNIQUE, category, family, display_order, is_active
  - seed 10 件 (小麦 春播/秋播, だいず, てんさい, ばれいしょ, あずき, にんじん, かぼちゃ, キャベツ, だいこん)
- **user_crops** — user_id FK, parent_crop_id FK crop_master, custom_name
  - 現状未使用 (v2 では crop_master を直接管理)

### 農薬系
- **pesticide_masters** — org_id FK, name, crop, category, manufacturer, active_ingredient, usage_timing, dilution_rate, application_method, safety_interval, notes
- **pesticide_records** — user_id FK CASCADE, field_id FK CASCADE, spray_date, pesticide_name, pesticide_id FK pesticide_registry SET NULL, dilution_rate, spray_amount, spray_unit, photo_path, notes
- **pesticide_registry** — registration_number UNIQUE, name, category, type, active_ingredient, manufacturer, formulation
  - FAMIC 由来のグローバル農薬登録情報 (v2 では未使用)
- **pesticide_usage** — FAMIC 適用情報 (v2 では未使用)

## FK の CASCADE ポリシー

- ユーザー削除 → fields / rotation_plans / pesticide_records が CASCADE 削除
- ほ場削除 → crop_history / pesticide_records / plan_details が CASCADE 削除
- 計画削除 → plan_details / plan_snapshots が CASCADE 削除

ユーザー自身は app から削除する手段がない (admin が直接 DB を編集する想定)。

## 値の形式メモ

- 年: `TEXT` 型で `"R6"` 形式 (令和年) を採用。`rotation_planner.common.year_utils` で変換
- 面積: `area_ha` を canonical、CSV インポート時に `area_a` (アール) なら `/100`
- ポリゴン: `coordinates_json` は GeoJSON Feature (`{"type":"Feature","geometry":{"type":"Polygon","coordinates":[[[lng,lat],...]]}}`)
- 制約 (`constraints_json`): `{crop_name: {min_ha, cap_ha, min_gap_years, min_fields, max_fields}, ...}`
- スナップショット (`data_json`): `{past_years, future_years, field_codes, grid: {"code|year": crop, ...}}`
