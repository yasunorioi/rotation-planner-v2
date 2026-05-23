# Features

ナビ順に、各機能の URL と概要。

## ダッシュボード (`/`)
- 4 指標タイル (ほ場数 / 計画数 / 履歴数 / 今年の防除数) — クリック可
- 「次のアクション」: ポリゴン未登録のほ場 / 履歴ゼロのほ場を黄バナーで提示
- 最近編集したほ場 / 最近の計画 / 最近の防除記録 (3カラム)

## ほ場 (`/fields/`)
### CRUD
- 一覧 + 行単位 inline add / edit / delete (HTMX)
- フィルタ: 地区 (DISTINCT で動的) / ポリゴン有無
- 列: 圃場コード / 地区 / 名称 / 面積(ha) / てんさい禁忌 / 図 / 固定作物 / 備考

### ポリゴン編集 (`/fields/{id}/polygon`)
- 全画面 Leaflet + Leaflet.draw
- 保存時の測地線面積を表示、`area_ha` への同期ボタン
- 単一ポリゴンのみ (描画追加で上書き)

### マップ表示 (`/fields/map`)
- 登録済みポリゴン全件を Leaflet で重畳
- popup でほ場詳細リンク

### 詳細ページ (`/fields/{id}/detail`)
- メタデータ + ポリゴン状態
- 作付履歴 全件
- 防除記録 最新 20 件

### I/O
- CSV テンプレ / 取込 / エクスポート (履歴も同時に持つ)
- KML テンプレ要否なし / 取込 / エクスポート (Placemark name = field_code)
- KMZ エクスポート (ZIP)
- GeoJSON エクスポート (`/fields/polygons.geojson`)

## 作付履歴 (`/history/`)
- ほ場 × 年度 のピボット表
- セルクリックで HTMX inline edit (datalist で作物候補)
- ✓ / ✗ ボタン + Enter / Esc キー両対応
- 年度範囲フィルタ (`?from=R5&to=R10`)
- CSV テンプレ / 取込 (既存ほ場のみ対象) / エクスポート

## 輪作計画 (`/plans/`)
### CRUD
- 一覧 + inline add / edit / delete
- メタデータのみ (name / start_year / end_year)

### 詳細 (`/plans/{id}`)
- 「計画を生成」ボタン → OR-Tools 最適化を同期実行 (timeout 5s)
- 結果: ほ場×年ピボット + 年×作物サマリ + 警告
- 「履歴に反映」: 選んだ将来年を crop_history に upsert
- 「スナップショット保存」: 結果を plan_snapshots に記録 (ラベル付与可)

### 制約エディタ (`/plans/{id}/constraints`)
- 作物別 `min_ha` / `cap_ha` / `min_gap_years` / `min_fields` / `max_fields`
- 作物の追加 / 削除
- `constraints_json` に JSON で保存

### スナップショット履歴 (`/plans/{id}/snapshots`)
- 複数保存・各々ラベル
- 個別比較 / PDF / 削除

### 比較 (`/plans/{id}/compare?snap_id=N`)
- スナップショット vs 現在の crop_history を 4 色セルで表示
  - 緑 = 一致 / 黄 = 差分 / 青 = 計画のみ / 灰 = 計画外実績
- PDF 出力 (同じ色分けで reportlab)

### 出力
- CSV 結果 (`/plans/{id}/result.csv`)
- PDF 結果 (`/plans/{id}/result.pdf`)
- 比較 PDF (`/plans/{id}/compare.pdf?snap_id=N`)

## 防除記録 (`/pesticide-records/`)
- 一覧 + inline CRUD (散布日 DESC)
- フィルタ: 年 / ほ場
- 農薬名は datalist (pesticide_masters + 過去記録から候補)
- CSV テンプレ / 取込 (INSERT only, UPSERT ではない) / エクスポート
- PDF エクスポート (フィルタ条件を継承)

## 作物マスタ (`/crop-masters/`)
- 名前 / 分類 / 科 / display_order / is_active
- seed 10 作物 (北海道主要作物)
- CSV 取込 / エクスポート (`upsert by name`)
- 履歴・ほ場フォーム・計画制約 の datalist 一次ソース
- `is_active=0` のものは候補から除外

## 農薬マスタ (`/pesticide-masters/`)
- 農薬名 / 対象作物 / 希釈倍率 / 用途 / 使用時期 / 備考
- CSV 取込 / エクスポート (`upsert by name+crop`)
- 防除記録 form の datalist ソース

## 集計 (`/aggregation/`)
- 年 × 作物 の合計面積 (履歴データから)
- ホバーで該当ほ場数
- 年範囲フィルタ
- CSV / PDF エクスポート

## 輪作チェック (`/rotation-check/`)
- 作物マスタの `family` 分類で連作 / 短期再作付を検出
- 🔴 連作 (前年と同 family)
- 🟡 短期再作付 (指定ギャップ以内に同 family)
- 📝 科分類未設定の作物リスト

## バックアップ (`/backup/`)
- `sqlite3.backup()` で書込中でも一貫した DB ファイル取得
- 復元はファイル置換のみ
- 関連 CSV / KML / GeoJSON への一覧リンク
