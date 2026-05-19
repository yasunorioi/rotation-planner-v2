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


def configure_db() -> Path:
    db_path = Path(os.environ.get("ROTATION_DB", DEFAULT_DB_PATH)).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _domain_db.DB_PATH = db_path
    _domain_db_access.DB_PATH = db_path
    _migrate(db_path)
    return db_path


def _migrate(db_path: Path) -> None:
    """既存 DB に対する手動マイグレーション。
    Why: SQLite は ADD COLUMN IF NOT EXISTS を持たないため、
    db_schema.sql に列追加した時は PRAGMA で確認して個別に ALTER する。
    """
    if not db_path.exists():
        return  # 新規 DB はスキーマがそのまま反映される
    conn = sqlite3.connect(str(db_path))
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(fields)")}
        if cols and "fixed_crop" not in cols:
            conn.execute("ALTER TABLE fields ADD COLUMN fixed_crop TEXT")
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
