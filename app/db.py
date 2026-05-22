"""SQLite 接続ヘルパー。

ドメインライブラリ `rotation_planner.common.db` の DB_PATH を環境変数
ROTATION_DB から差し替えて使う。アプリ起動時に `configure_db()` を呼ぶ。
"""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from rotation_planner.common import db as _domain_db
from rotation_planner.common import db_access as _domain_db_access

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "rotation_planner.db"

# DB パスごとにマイグレーション済みかどうかを記録する。
# Why: マイグレーションは schema.sql を毎回 executescript するので、
# INSERT OR IGNORE の seed がリクエスト毎に再投入されて、削除が
# 巻き戻る (= ユーザ視点で "削除が保存されない") バグになっていた。
# プロセス内で 1 度だけ走らせる。テストは ROTATION_DB を変えて
# 違うキャッシュ entry を確実に migrate する。
_migrated_paths: set[str] = set()


def configure_db() -> Path:
    db_path = Path(os.environ.get("ROTATION_DB", DEFAULT_DB_PATH)).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _domain_db.DB_PATH = db_path
    _domain_db_access.DB_PATH = db_path
    key = str(db_path)
    if key not in _migrated_paths:
        _migrate(db_path)
        _migrated_paths.add(key)
    return db_path


def _migrate(db_path: Path) -> None:
    """既存 DB に対する手動マイグレーション (プロセス起動につき 1 回)。
    Why: SQLite は ADD COLUMN IF NOT EXISTS を持たないため、
    db_schema.sql に列追加した時は PRAGMA で確認して個別に ALTER する。
    新規テーブル + seed は db_schema.sql の CREATE/INSERT OR IGNORE
    そのままで idempotent なので、最後に schema を流して追従させる。
    """
    if not db_path.exists():
        return  # 新規 DB はスキーマがそのまま反映される
    conn = sqlite3.connect(str(db_path))
    try:
        # 列追加 (idempotent ではないので個別チェック)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(fields)")}
        if cols and "fixed_crop" not in cols:
            conn.execute("ALTER TABLE fields ADD COLUMN fixed_crop TEXT")
            conn.commit()
        # 新規テーブル + seed は schema を流す (CREATE TABLE IF NOT EXISTS と
        # INSERT OR IGNORE で構成されているので idempotent)
        schema = Path(__file__).resolve().parent.parent / "db_schema.sql"
        if schema.exists():
            conn.executescript(schema.read_text(encoding="utf-8"))
            conn.commit()
    finally:
        conn.close()


@contextmanager
def connect():
    db_path = configure_db()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
