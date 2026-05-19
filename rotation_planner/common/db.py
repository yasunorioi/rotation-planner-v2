"""
データベース接続モジュール - SQLite接続管理

使用方法:
    from rotation_planner.common.db import get_db, row_to_dict, rows_to_list

    with get_db() as conn:
        cursor = conn.execute("SELECT * FROM fields WHERE user_id = ?", (user_id,))
        fields = rows_to_list(cursor.fetchall())
"""

import sqlite3
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from contextlib import contextmanager

from rotation_planner.common.exceptions import (
    DatabaseError, DatabaseConnectionError,
    DuplicateKeyError, NotNullViolationError, ForeignKeyViolationError
)

logger = logging.getLogger(__name__)

# =============================================================================
# 設定
# =============================================================================

# DBファイルパス（rotation_planner_ui/data/rotation_planner.db）
DB_DIR = Path(__file__).parent.parent.parent / "data"
DB_PATH = DB_DIR / "rotation_planner.db"


# =============================================================================
# 接続管理
# =============================================================================

def get_connection() -> sqlite3.Connection:
    """
    DB接続を取得

    Returns:
        sqlite3.Connection: データベース接続

    Raises:
        DatabaseConnectionError: 接続失敗時
    """
    # ディレクトリが存在しない場合は作成
    DB_DIR.mkdir(parents=True, exist_ok=True)

    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
        conn.row_factory = sqlite3.Row  # 辞書形式でアクセス可能
        conn.execute("PRAGMA foreign_keys = ON")  # 外部キー制約有効化
        conn.execute("PRAGMA journal_mode = WAL")  # WALモード（書き込み性能向上）
        return conn
    except sqlite3.OperationalError as e:
        logger.error(f"DB connection failed: {e}")
        raise DatabaseConnectionError(f"Failed to connect to database: {e}")


@contextmanager
def get_db():
    """
    コンテキストマネージャでDB接続を管理

    Usage:
        with get_db() as conn:
            cursor = conn.execute(...)
            # 自動コミット・ロールバック
    """
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.warning(f"Transaction rollback due to error: {e}")
        raise e
    finally:
        conn.close()


@contextmanager
def transaction():
    """
    明示的なトランザクション管理（エラー分類つき）

    Usage:
        with transaction() as conn:
            conn.execute(...)
            # 自動コミット・分類されたエラー

    Raises:
        DuplicateKeyError: UNIQUE制約違反
        NotNullViolationError: NOT NULL制約違反
        ForeignKeyViolationError: 外部キー制約違反
        DatabaseError: その他のDBエラー
    """
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except sqlite3.IntegrityError as e:
        conn.rollback()
        error_msg = str(e).lower()
        if "unique" in error_msg:
            raise DuplicateKeyError(str(e))
        elif "not null" in error_msg:
            raise NotNullViolationError(str(e))
        elif "foreign key" in error_msg:
            raise ForeignKeyViolationError(str(e))
        else:
            raise DatabaseError(str(e))
    except sqlite3.OperationalError as e:
        conn.rollback()
        logger.error(f"DB operational error: {e}")
        raise DatabaseError(str(e))
    except sqlite3.Error as e:
        conn.rollback()
        logger.error(f"DB error: {e}")
        raise DatabaseError(str(e))
    finally:
        conn.close()


# =============================================================================
# ユーティリティ関数
# =============================================================================

def row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    """
    sqlite3.Rowを辞書に変換

    Args:
        row: SQLiteの行データ

    Returns:
        辞書形式のデータ（rowがNoneの場合はNone）
    """
    return dict(row) if row else None


def rows_to_list(rows: List[sqlite3.Row]) -> List[Dict[str, Any]]:
    """
    sqlite3.Rowのリストを辞書のリストに変換

    Args:
        rows: SQLiteの行データのリスト

    Returns:
        辞書のリスト
    """
    return [dict(row) for row in rows]


# =============================================================================
# データベース初期化
# =============================================================================

def init_db(schema_path: Optional[Path] = None) -> None:
    """
    データベースを初期化（スキーマを適用 + 初期ユーザー作成）

    Args:
        schema_path: スキーマファイルのパス（省略時はデフォルト）
    """
    import hashlib

    if schema_path is None:
        schema_path = Path(__file__).parent.parent.parent / "db_schema.sql"

    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")

    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    with get_db() as conn:
        conn.executescript(schema_sql)

        # 初期ユーザーを作成（存在しない場合のみ）
        initial_users = [
            ("admin", "admin123", "管理者", "admin", 1),
            ("ja_staff", "ja123", "JA職員", "ja_staff", 1),
            ("farmer_demo", "demo123", "デモ農家", "farmer", 2),
        ]

        for username, password, display_name, role, org_id in initial_users:
            # 既存チェック
            cursor = conn.execute(
                "SELECT id FROM users WHERE username = ?",
                (username,)
            )
            if cursor.fetchone() is None:
                password_hash = hashlib.sha256(password.encode()).hexdigest()
                conn.execute(
                    """INSERT INTO users (username, password_hash, display_name, role, org_id)
                    VALUES (?, ?, ?, ?, ?)""",
                    (username, password_hash, display_name, role, org_id)
                )


def check_db_exists() -> bool:
    """
    データベースファイルが存在するかチェック

    Returns:
        存在すればTrue
    """
    return DB_PATH.exists()


def get_db_info() -> Dict[str, Any]:
    """
    データベース情報を取得

    Returns:
        データベース情報の辞書
    """
    info = {
        "path": str(DB_PATH),
        "exists": DB_PATH.exists(),
        "size_bytes": DB_PATH.stat().st_size if DB_PATH.exists() else 0,
    }

    if DB_PATH.exists():
        with get_db() as conn:
            # テーブル一覧
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            info["tables"] = [row["name"] for row in cursor.fetchall()]

    return info
