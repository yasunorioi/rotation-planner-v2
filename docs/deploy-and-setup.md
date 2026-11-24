# デプロイ & セットアップ手順

本番: **rtk.toiso.fit**（さくらのクラウド, 153.127.46.167）。[[architecture.md]] の構成を
HTMX+FastAPI+Jinja2 + SQLite + Basic 認証でホストする。

## サーバ構成（2026-11 時点）

| 項目 | 値 |
|---|---|
| SSH | `ssh debian@rtk.toiso.fit`（公開鍵・passwordless sudo） |
| アプリ配置 | `/var/www/rotation-planner-v2-htmx`（github clone, 所有 `webapp:webapp`） |
| Python | system python3（venv は `<app>/venv`） |
| systemd | `rotation-planner-v2.service` → `uvicorn app.main:app --host 127.0.0.1 --port 8001` |
| DB | `Environment=ROTATION_DB=<app>/data/rotation_planner.db` |
| nginx | `/etc/nginx/sites-available/rotation-planner-v2` → 全経路 `/` を 127.0.0.1:8001 へ proxy |
| 旧構成 | 旧 React 版 `/var/www/rotation-planner-v2/app`（停止・温存）、unit/vhost は `.bak-*` |

## 更新デプロイ（コード変更の反映）

```bash
ssh debian@rtk.toiso.fit
NEW=/var/www/rotation-planner-v2-htmx
sudo -u webapp git -C $NEW pull --ff-only
# pyproject.toml の依存を変えた時だけ:
#   cd $NEW && sudo -u webapp $NEW/venv/bin/pip install -e ".[dev]"
sudo systemctl restart rotation-planner-v2.service
sudo systemctl is-active rotation-planner-v2.service   # → active
```

ロールバックは旧コミットへ `git -C $NEW reset --hard <sha>` → restart。

## 初期セットアップ（新規 DB から）

```bash
NEW=/var/www/rotation-planner-v2-htmx
export ROTATION_DB=$NEW/data/rotation_planner.db
# スキーマ + 管理ユーザー作成
sudo -u webapp ROTATION_DB=$ROTATION_DB $NEW/venv/bin/python -m scripts.init_db \
    --username <ユーザー名> --password '<パスワード>' --display-name '表示名' --role admin
# FAMIC 取込（作物名の原点）: data/famic/{basic,usage1,usage2}.xls を置いてから
sudo -u webapp ROTATION_DB=$ROTATION_DB $NEW/venv/bin/python -m scripts.import_famic
sudo chown -R webapp:webapp $NEW
```

## 運用タスク

### ログインパスワードの変更

```bash
NEW=/var/www/rotation-planner-v2-htmx
sudo -u webapp $NEW/venv/bin/python -c "
import sqlite3, hashlib
c = sqlite3.connect('$NEW/data/rotation_planner.db')
c.execute('UPDATE users SET password_hash=? WHERE username=?',
          (hashlib.sha256(b'新しいパスワード').hexdigest(), 'yasu'))
c.commit(); print('updated')
"
```
認証は `users.password_hash = sha256(password)` の HTTP Basic（`app/auth.py`）。

### 筆ポリゴン（農水省）データの配置

地図からの圃場登録・筆ポリゴン採用を使うには、市町村ごとの GeoJSON を置く。

1. https://open.fude.maff.go.jp/ で利用規約に同意（アンケート回答が必要なため自動DL不可）
2. 対象市町村の **GeoJSON** をダウンロード
3. `{市町村コード}.geojson` にリネームして `<app>/data/fude_cache/` に配置
   - 例: 恵庭 = `01231.geojson`、千歳 = `01224.geojson`、北広島 = `01234.geojson`
   - 複数市町村を置いてよい（ビュー内を全ファイル横断検索）
4. 所有を webapp に: `sudo chown webapp:webapp <app>/data/fude_cache/*.geojson`

配置前は UI に「筆ポリゴンデータ未配置」と案内が出るだけ（機能自体は正常）。
詳細は `data/fude_cache/README.md`。

### FAMIC（農薬登録データ）の更新

最新版が出たら `data/famic/` の xls を差し替えて再取込:
```bash
sudo -u webapp ROTATION_DB=$NEW/data/rotation_planner.db \
    $NEW/venv/bin/python -m scripts.import_famic
```
公開元: https://www.acis.famic.go.jp/ddownload/

### バックアップ

アプリ内 `/backup/`（SQLite backup API でメモリ経由の一貫スナップショット）。
または `cp <app>/data/rotation_planner.db <退避先>`（サービス停止不要、WAL なしなら可）。

## 検証メモ

- サーバ側 API は `curl -u <user>:<pass> http://127.0.0.1:8001/...` で確認できる。
- 地図まわりの fetch は Basic 認証を使う。**ヘッドレス Chrome は URL 埋め込み認証を
  XHR に引き継がない**ため「取得に失敗」と出るが、これはヘッドレス特有のアーティファクト。
  実ブラウザ（ログイン済み）では fetch にも認証が乗り正常動作する。
