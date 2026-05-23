# CSV / KML フォーマット

全 CSV は UTF-8 BOM 付き出力、入力は UTF-8 BOM または CP932 を許容。
ヘッダは別名対応 (日本語/英語両方)。

## ほ場 + 作付履歴 (`/fields/*`)

### 必須列
- 「ほ場ID」または `field_code` / 圃場コード / field_id
- 面積: 「area」/area_a/面積_a (アール) または `area_ha`/面積_ha (ヘクタール)

### 任意列
- 地区 / district
- ほ場名 / 圃場名 / name
- beet_forbidden / てんさい禁忌 (0/1)
- 固定作物 / fixed_crop
- 備考 / notes / メモ
- 年列: `R\d+` パターン (R5, R6, ...) — 作付履歴も同時投入

### サンプル
```csv
ほ場ID,地区,ほ場名,area,beet_forbidden,固定作物,R5,R6,R7,R8
F001,北地区,北1号,280,0,,春小麦,大豆,秋小麦,てんさい
F002,北地区,北2号,320,0,,大豆,秋小麦,デントコーン,春小麦
F003,南地区,南1号,250,1,,てんさい,春小麦,大豆,秋小麦
PERM1,東地区,牧草地,150,0,牧草,,,,
```

- area は アール (1/100 ha)。`area_ha` 列があればそちらを優先
- `field_code` でユーザー内 UNIQUE。同名は UPDATE (upsert)
- 年列が空欄なら履歴を変更しない (削除はしない)

## 作付履歴のみ (`/history/*`)

### ヘッダ
- `ほ場ID` (必須)
- 年列 `R\d+` (1 つ以上)

### サンプル
```csv
ほ場ID,ほ場名,R5,R6,R7
F001,北1号,春小麦,大豆,てんさい
F002,北2号,てんさい,小麦(秋播),大豆
```

- 既存ほ場のみ対象 (`field_code` 一致)。未登録は エラー報告
- 空セルで保存すると履歴を**削除** (fields/import との違い)

## 防除記録 (`/pesticide-records/*`)

### 必須列
- `散布日` / spray_date / date (YYYY-MM-DD)
- `ほ場ID` (既存 field_code 一致)
- `農薬名` / pesticide_name / name

### 任意列
- `希釈倍率` / dilution_rate
- `量` / spray_amount / amount
- `単位` / spray_unit / unit
- `備考` / notes / メモ

### サンプル
```csv
散布日,ほ場ID,農薬名,希釈倍率,量,単位,備考
2026-05-10,F001,ベンレート水和剤,1000倍,0.3,L/10a,褐斑病対策
2026-06-15,F002,グリホサート,200倍,2.5,L/10a,
```

- **常に INSERT** (UPSERT ではない)。同じ CSV を 2 回上げると重複行が増える
- 未登録ほ場・必須欠落はエラー報告して該当行スキップ

## 農薬マスタ (`/pesticide-masters/*`)

```csv
農薬名,対象作物,希釈倍率,用途,使用時期,備考
ベンレート水和剤,てんさい,1000倍,殺菌,5月,褐斑病対策
グリホサート,共通,200倍,除草,休閑期,
```

- (name, crop) で UPSERT

## 作物マスタ (`/crop-masters/*`)

```csv
作物名,分類,科,display_order,is_active
そば,雑穀,タデ科,11,1
オーツ麦,穀物,イネ科,12,0
```

- `name` で UPSERT
- `is_active=0` のものは history/fields/plans の datalist 候補から除外される

## KML / KMZ (`/fields/import_kml`, `/fields/polygons.kml*`)

### インポート
- KML ファイルまたは KMZ (KML を含む ZIP) をアップロード
- 各 `<Placemark>` の `<name>` が `field_code` として upsert
- ポリゴン座標から測地線面積を自動計算して `area_ha` にセット
- 既存 field_code 一致 = 更新、それ以外は新規追加

### エクスポート
- `/fields/polygons.kml` — KML XML
- `/fields/polygons.kmz` — KML を ZIP した KMZ
- `/fields/polygons.geojson` — GeoJSON FeatureCollection (properties: id/field_code/name/district/area_ha)

### 座標順注意
- KML 内: `経度,緯度,高度`
- GeoJSON: `[lng, lat]`
- ライブラリの KML パーサは `[lat, lng]` を返すので、`app/routes/fields.py` で swap している
