"""
認証モジュール - Gradio標準認証 + SQLite DB

使用方法:
    from rotation_planner.common.auth import authenticate, get_user_info, can_access_user_data

    # Gradio launchで使用
    demo.launch(auth=authenticate)

    # ユーザー情報取得
    user = get_user_info(request.username)

    # アクセス権限チェック
    if can_access_user_data(username, target_user_id):
        # データにアクセス
        pass
"""

import hashlib
import logging
from typing import List, Dict, Optional, Any
from datetime import datetime

from .db import get_db, row_to_dict, rows_to_list

logger = logging.getLogger("rotation_planner.auth")


# =============================================================================
# 設定
# =============================================================================

# ロール定義
ROLE_ADMIN = "admin"
ROLE_JA_STAFF = "ja_staff"
ROLE_FARMER = "farmer"

# 管理者ロール（全農家データにアクセス可能）
ADMIN_ROLES = {ROLE_ADMIN, ROLE_JA_STAFF}


# =============================================================================
# ユーザー管理（DB版）
# =============================================================================

def load_users() -> List[Dict[str, Any]]:
    """
    ユーザー一覧をDBから読み込み

    Returns:
        ユーザー情報のリスト
    """
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT id, username, password_hash, display_name, role, org_id, is_active "
            "FROM users WHERE is_active = 1 ORDER BY id"
        )
        return rows_to_list(cursor.fetchall())


def save_users(users: List[Dict[str, Any]]) -> None:
    """
    ユーザー一覧をDBに保存（後方互換用 - 個別操作を推奨）

    Args:
        users: ユーザー情報のリスト
    """
    with get_db() as conn:
        for user in users:
            # usernameで既存チェック
            cursor = conn.execute(
                "SELECT id FROM users WHERE username = ?",
                (user.get("username"),)
            )
            existing = cursor.fetchone()

            if existing:
                # 更新
                conn.execute(
                    """UPDATE users SET
                        password_hash = ?,
                        display_name = ?,
                        role = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE username = ?""",
                    (
                        user.get("password_hash"),
                        user.get("display_name", user.get("username")),
                        user.get("role"),
                        user.get("username"),
                    )
                )
            else:
                # 新規
                conn.execute(
                    """INSERT INTO users (username, password_hash, display_name, role, org_id)
                    VALUES (?, ?, ?, ?, ?)""",
                    (
                        user.get("username"),
                        user.get("password_hash"),
                        user.get("display_name", user.get("username")),
                        user.get("role"),
                        user.get("org_id", 2),  # デフォルト: 個人農家
                    )
                )


def hash_password(password: str) -> str:
    """
    パスワードをSHA256でハッシュ化

    Args:
        password: 平文パスワード

    Returns:
        ハッシュ化されたパスワード
    """
    return hashlib.sha256(password.encode()).hexdigest()


# =============================================================================
# 認証
# =============================================================================

def authenticate(username: str, password: str) -> bool:
    """
    Gradio auth関数 - ユーザー認証（DB版）

    Args:
        username: ユーザー名
        password: パスワード

    Returns:
        認証成功ならTrue。DBエラー時はFalse（fail closed）
    """
    pw_hash = hash_password(password)

    try:
        with get_db() as conn:
            cursor = conn.execute(
                "SELECT id FROM users WHERE username = ? AND password_hash = ? AND is_active = 1",
                (username, pw_hash)
            )
            return cursor.fetchone() is not None
    except Exception as e:
        logger.error("認証DB問い合わせエラー: %s", e, exc_info=True)
        return False


def get_user_info(username: str) -> Optional[Dict[str, Any]]:
    """
    ユーザー情報を取得（DB版）

    Args:
        username: ユーザー名

    Returns:
        ユーザー情報（見つからない場合はNone）
    """
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT id, username, display_name, role, org_id FROM users "
            "WHERE username = ? AND is_active = 1",
            (username,)
        )
        row = cursor.fetchone()

    if not row:
        return None

    return {
        "id": row["id"],
        "user_id": row["id"],  # 明示的にuser_idも返す
        "username": row["username"],
        "role": row["role"],
        "display_name": row["display_name"],
        "org_id": row["org_id"],
    }


# =============================================================================
# アクセス制御
# =============================================================================

def can_access_user_data(username: str, target_user_id: int) -> bool:
    """
    特定ユーザーのデータへのアクセス権限をチェック

    Args:
        username: ログインユーザー名
        target_user_id: アクセス対象のユーザーID

    Returns:
        アクセス可能ならTrue
    """
    user = get_user_info(username)
    if not user:
        return False

    role = user.get("role")

    # 管理者・JA職員は全ユーザーにアクセス可能
    if role in ADMIN_ROLES:
        return True

    # 一般ユーザーは自分のデータのみ
    return user.get("id") == target_user_id


# 後方互換エイリアス
def can_access_farmer(username: str, farmer_id: str) -> bool:
    """後方互換用エイリアス。can_access_user_data() を使用してください。"""
    try:
        return can_access_user_data(username, int(farmer_id))
    except (ValueError, TypeError):
        return False


def get_accessible_user_ids(username: str) -> List[int]:
    """
    アクセス可能なユーザーIDのリストを取得

    Args:
        username: ユーザー名

    Returns:
        アクセス可能なユーザーIDのリスト
        管理者・JA職員の場合は空リスト（全ユーザー = フィルタなし）
    """
    user = get_user_info(username)
    if not user:
        return []

    role = user.get("role")

    # 管理者・JA職員は全ユーザー（フィルタなし）
    if role in ADMIN_ROLES:
        return []  # 空 = 全員

    # 一般ユーザーは自分のみ
    user_id = user.get("id")
    if user_id:
        return [user_id]

    return []


# 後方互換エイリアス
def get_accessible_farmers(username: str) -> List[str]:
    """後方互換用エイリアス。get_accessible_user_ids() を使用してください。"""
    user = get_user_info(username)
    if not user:
        return []
    if user.get("role") in ADMIN_ROLES:
        return ["*"]
    user_id = user.get("id")
    return [str(user_id)] if user_id else []


def is_admin_role(username: str) -> bool:
    """
    管理者ロール（admin または ja_staff）かどうかをチェック

    Args:
        username: ユーザー名

    Returns:
        管理者ロールならTrue
    """
    user = get_user_info(username)
    if not user:
        return False

    return user.get("role") in ADMIN_ROLES


def get_user_role(username: str) -> Optional[str]:
    """
    ユーザーのロールを取得

    Args:
        username: ユーザー名

    Returns:
        ロール（見つからない場合はNone）
    """
    user = get_user_info(username)
    if not user:
        return None

    return user.get("role")


# =============================================================================
# ユーザー管理（管理者用）
# =============================================================================

def add_user(
    username: str,
    password: str,
    role: str,
    display_name: Optional[str] = None,
    org_id: int = 2
) -> bool:
    """
    新規ユーザーを追加（DB版）

    Args:
        username: ユーザー名
        password: パスワード
        role: ロール（admin, ja_staff, farmer）
        display_name: 表示名
        org_id: 組織ID（デフォルト: 2=個人農家）

    Returns:
        追加成功ならTrue

    Raises:
        ValueError: ユーザー名が既に存在する場合
    """
    with get_db() as conn:
        # 既存ユーザーチェック
        cursor = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (username,)
        )
        if cursor.fetchone():
            raise ValueError(f"ユーザー名 '{username}' は既に使用されています")

        # 新規追加
        conn.execute(
            """INSERT INTO users (username, password_hash, display_name, role, org_id)
            VALUES (?, ?, ?, ?, ?)""",
            (
                username,
                hash_password(password),
                display_name or username,
                role,
                org_id,
            )
        )

    return True


def update_password(username: str, new_password: str) -> bool:
    """
    パスワードを更新（DB版）

    Args:
        username: ユーザー名
        new_password: 新しいパスワード

    Returns:
        更新成功ならTrue
    """
    with get_db() as conn:
        cursor = conn.execute(
            """UPDATE users SET password_hash = ?, updated_at = CURRENT_TIMESTAMP
            WHERE username = ? AND is_active = 1""",
            (hash_password(new_password), username)
        )
        return cursor.rowcount > 0


def update_user_role(username: str, new_role: str) -> bool:
    """
    ユーザーのロールを更新（DB版）

    Args:
        username: ユーザー名
        new_role: 新しいロール

    Returns:
        更新成功ならTrue
    """
    if new_role not in (ROLE_ADMIN, ROLE_JA_STAFF, ROLE_FARMER):
        return False

    with get_db() as conn:
        cursor = conn.execute(
            """UPDATE users SET role = ?, updated_at = CURRENT_TIMESTAMP
            WHERE username = ? AND is_active = 1""",
            (new_role, username)
        )
        return cursor.rowcount > 0


def delete_user(username: str) -> bool:
    """
    ユーザーを削除（論理削除）（DB版）

    Args:
        username: ユーザー名

    Returns:
        削除成功ならTrue
    """
    with get_db() as conn:
        cursor = conn.execute(
            """UPDATE users SET is_active = 0, updated_at = CURRENT_TIMESTAMP
            WHERE username = ? AND is_active = 1""",
            (username,)
        )
        return cursor.rowcount > 0


def get_admin_count() -> int:
    """
    アクティブな管理者の数を取得

    Returns:
        管理者の数
    """
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1"
        )
        return cursor.fetchone()[0]
