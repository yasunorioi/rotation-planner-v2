"""
DBアクセス層 - SQLiteデータベースへのCRUD操作モジュール

使用方法:
    from db_access import FieldRepository, PlanRepository, JAStaffRepository

    # ほ場操作
    fields = FieldRepository.get_fields(user_id=1)
    FieldRepository.create_field(user_id=1, data={...})

    # 輪作計画操作
    plans = PlanRepository.get_plans(user_id=1)
    PlanRepository.create_plan(user_id=1, data={...})

    # JA職員用
    all_fields = JAStaffRepository.get_all_fields(org_id=1)
"""

import sqlite3
import json
import os
import logging
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime
from contextlib import contextmanager

from rotation_planner.common.exceptions import (
    DatabaseError, DuplicateKeyError, NotNullViolationError,
    ForeignKeyViolationError, RecordNotFoundError
)

logger = logging.getLogger(__name__)

# =============================================================================
# 設定
# =============================================================================

# rotation_planner_ui/data/ を参照（common/からの相対パス）
DB_DIR = Path(__file__).parent.parent.parent / "data"
DB_PATH = DB_DIR / "rotation_planner.db"
JSON_DATA_DIR = DB_DIR


# =============================================================================
# 接続管理
# =============================================================================

def get_connection() -> sqlite3.Connection:
    """
    DB接続を取得

    Returns:
        sqlite3.Connection: データベース接続
    """
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    conn.row_factory = sqlite3.Row  # 辞書形式でアクセス可能
    conn.execute("PRAGMA foreign_keys = ON")  # 外部キー制約有効化
    conn.execute("PRAGMA journal_mode = WAL")  # WALモード（書き込み性能向上）
    return conn


@contextmanager
def get_db():
    """
    コンテキストマネージャでDB接続を管理

    Usage:
        with get_db() as conn:
            cursor = conn.execute(...)
    """
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


@contextmanager
def transaction():
    """
    明示的なトランザクション管理（エラー分類つき）

    Usage:
        with transaction() as conn:
            conn.execute("BEGIN IMMEDIATE")
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
        conn.execute("BEGIN IMMEDIATE")
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


def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """sqlite3.Rowを辞書に変換"""
    return dict(row) if row else None


def rows_to_list(rows: List[sqlite3.Row]) -> List[Dict[str, Any]]:
    """sqlite3.Rowのリストを辞書のリストに変換"""
    return [dict(row) for row in rows]


# =============================================================================
# ほ場（Fields）リポジトリ
# =============================================================================

class FieldRepository:
    """ほ場データのCRUD操作"""

    @staticmethod
    def get_fields(user_id: int) -> List[Dict[str, Any]]:
        """
        ユーザーのほ場一覧を取得

        Args:
            user_id: ユーザーID

        Returns:
            ほ場データのリスト
        """
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT id, field_code, district, name, area_ha, area_a,
                       beet_forbidden, coordinates_json, notes, created_at, updated_at
                FROM fields
                WHERE user_id = ?
                ORDER BY field_code
            """, (user_id,))
            return rows_to_list(cursor.fetchall())

    @staticmethod
    def get_field(field_id: int) -> Optional[Dict[str, Any]]:
        """
        ほ場詳細を取得

        Args:
            field_id: ほ場ID

        Returns:
            ほ場データ（見つからない場合はNone）
        """
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT f.*, u.username as owner_username, u.display_name as owner_name
                FROM fields f
                JOIN users u ON f.user_id = u.id
                WHERE f.id = ?
            """, (field_id,))
            row = cursor.fetchone()
            return row_to_dict(row)

    @staticmethod
    def get_field_by_code(user_id: int, field_code: str) -> Optional[Dict[str, Any]]:
        """ほ場コードでほ場を取得"""
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT * FROM fields WHERE user_id = ? AND field_code = ?
            """, (user_id, field_code))
            row = cursor.fetchone()
            return row_to_dict(row)

    @staticmethod
    def create_field(user_id: int, data: Dict[str, Any]) -> int:
        """
        ほ場を作成

        Args:
            user_id: ユーザーID
            data: ほ場データ
                - field_code: ほ場コード（必須）
                - district: 地区
                - name: ほ場名
                - area_ha: 面積（ha）（必須）
                - beet_forbidden: てんさい禁止フラグ
                - coordinates_json: 座標JSON
                - notes: 備考

        Returns:
            作成されたほ場のID
        """
        try:
            with get_db() as conn:
                cursor = conn.execute("""
                    INSERT INTO fields (user_id, field_code, district, name, area_ha,
                                       beet_forbidden, coordinates_json, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_id,
                    data['field_code'],
                    data.get('district'),
                    data.get('name'),
                    data['area_ha'],
                    data.get('beet_forbidden', 0),
                    data.get('coordinates_json'),
                    data.get('notes')
                ))
                field_id = cursor.lastrowid
                logger.info(f"作成成功: ほ場 field_code={data.get('field_code')} id={field_id}")
                return field_id
        except sqlite3.IntegrityError as e:
            error_msg = str(e).lower()
            if "unique" in error_msg:
                raise DuplicateKeyError(f"重複データです: {e}")
            elif "not null" in error_msg:
                raise NotNullViolationError(f"必須項目が未入力です: {e}")
            elif "foreign key" in error_msg:
                raise ForeignKeyViolationError(f"参照先が存在しません: {e}")
            else:
                raise DatabaseError(f"データベースエラー: {e}")
        except sqlite3.Error as e:
            logger.error(f"操作失敗: ほ場作成 - {e}")
            raise DatabaseError(f"データベースエラーが発生しました: {e}")

    @staticmethod
    def update_field(field_id: int, data: Dict[str, Any]) -> bool:
        """
        ほ場を更新

        Args:
            field_id: ほ場ID
            data: 更新データ

        Returns:
            更新成功ならTrue
        """
        try:
            with get_db() as conn:
                # 更新対象カラムを動的に構築
                updates = []
                values = []
                for key in ['field_code', 'district', 'name', 'area_ha',
                           'beet_forbidden', 'coordinates_json', 'notes']:
                    if key in data:
                        updates.append(f"{key} = ?")
                        values.append(data[key])

                if not updates:
                    return False

                updates.append("updated_at = CURRENT_TIMESTAMP")
                values.append(field_id)

                sql = f"UPDATE fields SET {', '.join(updates)} WHERE id = ?"
                cursor = conn.execute(sql, values)
                success = cursor.rowcount > 0
                if success:
                    logger.info(f"更新成功: ほ場 id={field_id}")
                return success
        except sqlite3.IntegrityError as e:
            error_msg = str(e).lower()
            if "unique" in error_msg:
                raise DuplicateKeyError(f"重複データです: {e}")
            elif "not null" in error_msg:
                raise NotNullViolationError(f"必須項目が未入力です: {e}")
            elif "foreign key" in error_msg:
                raise ForeignKeyViolationError(f"参照先が存在しません: {e}")
            else:
                raise DatabaseError(f"データベースエラー: {e}")
        except sqlite3.Error as e:
            logger.error(f"操作失敗: ほ場更新 id={field_id} - {e}")
            raise DatabaseError(f"データベースエラーが発生しました: {e}")

    @staticmethod
    def delete_field(field_id: int) -> bool:
        """
        ほ場を削除

        Args:
            field_id: ほ場ID

        Returns:
            削除成功ならTrue
        """
        try:
            with get_db() as conn:
                cursor = conn.execute("DELETE FROM fields WHERE id = ?", (field_id,))
                success = cursor.rowcount > 0
                if success:
                    logger.info(f"削除成功: ほ場 id={field_id}")
                return success
        except sqlite3.IntegrityError as e:
            error_msg = str(e).lower()
            if "foreign key" in error_msg:
                raise ForeignKeyViolationError(f"参照先が存在します。削除できません: {e}")
            else:
                raise DatabaseError(f"データベースエラー: {e}")
        except sqlite3.Error as e:
            logger.error(f"操作失敗: ほ場削除 id={field_id} - {e}")
            raise DatabaseError(f"データベースエラーが発生しました: {e}")

    @staticmethod
    def get_field_with_history(field_id: int) -> Optional[Dict[str, Any]]:
        """ほ場と作付履歴を取得"""
        with get_db() as conn:
            # ほ場情報
            cursor = conn.execute("SELECT * FROM fields WHERE id = ?", (field_id,))
            field = row_to_dict(cursor.fetchone())
            if not field:
                return None

            # 作付履歴
            cursor = conn.execute("""
                SELECT year, crop, is_inferred
                FROM crop_history
                WHERE field_id = ?
                ORDER BY year
            """, (field_id,))
            field['history'] = rows_to_list(cursor.fetchall())

            return field


# =============================================================================
# 作付履歴リポジトリ
# =============================================================================

class CropHistoryRepository:
    """作付履歴のCRUD操作"""

    @staticmethod
    def get_history(field_id: int) -> List[Dict[str, Any]]:
        """ほ場の作付履歴を取得"""
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT * FROM crop_history
                WHERE field_id = ?
                ORDER BY year
            """, (field_id,))
            return rows_to_list(cursor.fetchall())

    @staticmethod
    def get_all_history_for_user(user_id: int) -> List[Dict[str, Any]]:
        """
        ユーザーの全ほ場の履歴を取得（マトリックス表示用）

        Args:
            user_id: ユーザーID

        Returns:
            履歴データのリスト。各要素は:
            - field_id: ほ場ID（DB主キー）
            - field_code: ほ場コード（表示用）
            - field_name: ほ場名
            - year: 年度（R7, R8など）
            - crop: 作物名
            - is_inferred: 推論フラグ（1なら推論で補完）
        """
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT
                    ch.field_id,
                    f.field_code,
                    f.name as field_name,
                    ch.year,
                    ch.crop,
                    ch.is_inferred
                FROM crop_history ch
                INNER JOIN fields f ON f.id = ch.field_id
                WHERE f.user_id = ?
                ORDER BY f.field_code, ch.year
            """, (user_id,))
            return rows_to_list(cursor.fetchall())

    @staticmethod
    def get_history_by_id(history_id: int) -> Optional[Dict[str, Any]]:
        """
        履歴IDで作付履歴を取得

        Args:
            history_id: 履歴ID

        Returns:
            履歴データ（id, field_id, year, crop, is_inferred）、存在しなければNone
        """
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT * FROM crop_history WHERE id = ?
            """, (history_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    @staticmethod
    def delete_history(field_id: int, year: str) -> bool:
        """
        特定ほ場・年度の履歴を削除

        Args:
            field_id: ほ場ID
            year: 年度（R7, R8など）

        Returns:
            削除成功ならTrue
        """
        try:
            with get_db() as conn:
                cursor = conn.execute("""
                    DELETE FROM crop_history
                    WHERE field_id = ? AND year = ?
                """, (field_id, year))
                success = cursor.rowcount > 0
                if success:
                    logger.info(f"削除成功: 作付履歴 field_id={field_id} year={year}")
                return success
        except sqlite3.Error as e:
            logger.error(f"操作失敗: 作付履歴削除 field_id={field_id} year={year} - {e}")
            raise DatabaseError(f"データベースエラーが発生しました: {e}")

    @staticmethod
    def delete_history_by_id(history_id: int) -> bool:
        """
        履歴IDで作付履歴を削除

        Args:
            history_id: 履歴ID

        Returns:
            削除成功ならTrue
        """
        with get_db() as conn:
            cursor = conn.execute("""
                DELETE FROM crop_history WHERE id = ?
            """, (history_id,))
            return cursor.rowcount > 0

    @staticmethod
    def bulk_update_history(updates: List[Dict[str, Any]]) -> int:
        """
        複数レコードの一括更新（トランザクション内で実行）

        Args:
            updates: 更新データのリスト。各要素は:
                - field_id: ほ場ID
                - year: 年度
                - crop: 作物名（空文字の場合は削除）

        Returns:
            更新・挿入された件数
        """
        try:
            count = 0
            with get_db() as conn:
                for update in updates:
                    field_id = update.get('field_id')
                    year = update.get('year')
                    crop = update.get('crop', '').strip()

                    if not field_id or not year:
                        continue

                    if not crop:
                        # 空の場合は削除
                        conn.execute("""
                            DELETE FROM crop_history
                            WHERE field_id = ? AND year = ?
                        """, (field_id, year))
                    else:
                        # INSERT OR REPLACE で追加/更新
                        conn.execute("""
                            INSERT OR REPLACE INTO crop_history (field_id, year, crop, is_inferred)
                            VALUES (?, ?, ?, 0)
                        """, (field_id, year, crop))
                    count += 1
            logger.info(f"作成成功: 作付履歴一括更新 {count}件")
            return count
        except sqlite3.IntegrityError as e:
            error_msg = str(e).lower()
            if "foreign key" in error_msg:
                raise ForeignKeyViolationError(f"参照先が存在しません: {e}")
            else:
                raise DatabaseError(f"データベースエラー: {e}")
        except sqlite3.Error as e:
            logger.error(f"操作失敗: 作付履歴一括更新 - {e}")
            raise DatabaseError(f"データベースエラーが発生しました: {e}")

    @staticmethod
    def add_history(field_id: int, year: str, crop: str, is_inferred: bool = False) -> int:
        """作付履歴を追加"""
        try:
            with get_db() as conn:
                cursor = conn.execute("""
                    INSERT OR REPLACE INTO crop_history (field_id, year, crop, is_inferred)
                    VALUES (?, ?, ?, ?)
                """, (field_id, year, crop, 1 if is_inferred else 0))
                history_id = cursor.lastrowid
                logger.info(f"作成成功: 作付履歴 field_id={field_id} year={year} crop={crop}")
                return history_id
        except sqlite3.IntegrityError as e:
            error_msg = str(e).lower()
            if "foreign key" in error_msg:
                raise ForeignKeyViolationError(f"参照先が存在しません: {e}")
            else:
                raise DatabaseError(f"データベースエラー: {e}")
        except sqlite3.Error as e:
            logger.error(f"操作失敗: 作付履歴追加 field_id={field_id} - {e}")
            raise DatabaseError(f"データベースエラーが発生しました: {e}")

    @staticmethod
    def bulk_add_history(field_id: int, history: Dict[str, str]) -> int:
        """作付履歴を一括追加（年: 作物の辞書）"""
        try:
            count = 0
            with get_db() as conn:
                for year, crop in history.items():
                    conn.execute("""
                        INSERT OR REPLACE INTO crop_history (field_id, year, crop, is_inferred)
                        VALUES (?, ?, ?, 0)
                    """, (field_id, year, crop))
                    count += 1
            logger.info(f"作成成功: 作付履歴一括追加 field_id={field_id} {count}件")
            return count
        except sqlite3.IntegrityError as e:
            error_msg = str(e).lower()
            if "foreign key" in error_msg:
                raise ForeignKeyViolationError(f"参照先が存在しません: {e}")
            else:
                raise DatabaseError(f"データベースエラー: {e}")
        except sqlite3.Error as e:
            logger.error(f"操作失敗: 作付履歴一括追加 field_id={field_id} - {e}")
            raise DatabaseError(f"データベースエラーが発生しました: {e}")


# =============================================================================
# 輪作計画（Rotation Plans）リポジトリ
# =============================================================================

class PlanRepository:
    """輪作計画のCRUD操作"""

    @staticmethod
    def get_plans(user_id: int) -> List[Dict[str, Any]]:
        """
        ユーザーの輪作計画一覧を取得

        Args:
            user_id: ユーザーID

        Returns:
            計画データのリスト
        """
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT id, name, start_year, end_year, created_at, updated_at
                FROM rotation_plans
                WHERE user_id = ?
                ORDER BY updated_at DESC
            """, (user_id,))
            return rows_to_list(cursor.fetchall())

    @staticmethod
    def get_plan(plan_id: int) -> Optional[Dict[str, Any]]:
        """
        輪作計画詳細を取得（詳細データ含む）

        Args:
            plan_id: 計画ID

        Returns:
            計画データ（見つからない場合はNone）
        """
        with get_db() as conn:
            # 計画メタデータ
            cursor = conn.execute("""
                SELECT * FROM rotation_plans WHERE id = ?
            """, (plan_id,))
            plan = row_to_dict(cursor.fetchone())
            if not plan:
                return None

            # 計画詳細（ほ場×年の作付）
            cursor = conn.execute("""
                SELECT pd.*, f.field_code, f.name as field_name, f.district
                FROM plan_details pd
                JOIN fields f ON pd.field_id = f.id
                WHERE pd.plan_id = ?
                ORDER BY f.field_code, pd.year
            """, (plan_id,))
            plan['details'] = rows_to_list(cursor.fetchall())

            # 制約をパース
            if plan.get('constraints_json'):
                plan['constraints'] = json.loads(plan['constraints_json'])

            return plan

    @staticmethod
    def create_plan(user_id: int, data: Dict[str, Any]) -> int:
        """
        輪作計画を作成

        Args:
            user_id: ユーザーID
            data: 計画データ
                - name: 計画名（必須）
                - start_year: 開始年（必須）
                - end_year: 終了年（必須）
                - constraints: 制約設定（dict）
                - details: 計画詳細リスト [{field_id, year, crop}, ...]

        Returns:
            作成された計画のID
        """
        try:
            with get_db() as conn:
                # 計画メタデータ
                constraints_json = json.dumps(data.get('constraints', {}), ensure_ascii=False)
                metadata_json = json.dumps(data.get('metadata', {}), ensure_ascii=False)

                cursor = conn.execute("""
                    INSERT INTO rotation_plans (user_id, name, start_year, end_year,
                                               constraints_json, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    user_id,
                    data['name'],
                    data['start_year'],
                    data['end_year'],
                    constraints_json,
                    metadata_json
                ))
                plan_id = cursor.lastrowid

                # 計画詳細
                for detail in data.get('details', []):
                    conn.execute("""
                        INSERT INTO plan_details (plan_id, field_id, year, crop)
                        VALUES (?, ?, ?, ?)
                    """, (plan_id, detail['field_id'], detail['year'], detail['crop']))

                logger.info(f"作成成功: 輪作計画 name={data.get('name')} id={plan_id}")
                return plan_id
        except sqlite3.IntegrityError as e:
            error_msg = str(e).lower()
            if "unique" in error_msg:
                raise DuplicateKeyError(f"重複データです: {e}")
            elif "not null" in error_msg:
                raise NotNullViolationError(f"必須項目が未入力です: {e}")
            elif "foreign key" in error_msg:
                raise ForeignKeyViolationError(f"参照先が存在しません: {e}")
            else:
                raise DatabaseError(f"データベースエラー: {e}")
        except sqlite3.Error as e:
            logger.error(f"操作失敗: 輪作計画作成 - {e}")
            raise DatabaseError(f"データベースエラーが発生しました: {e}")

    @staticmethod
    def update_plan(plan_id: int, data: Dict[str, Any]) -> bool:
        """
        輪作計画を更新

        Args:
            plan_id: 計画ID
            data: 更新データ

        Returns:
            更新成功ならTrue
        """
        try:
            with get_db() as conn:
                # メタデータ更新
                updates = []
                values = []
                for key in ['name', 'start_year', 'end_year']:
                    if key in data:
                        updates.append(f"{key} = ?")
                        values.append(data[key])

                if 'constraints' in data:
                    updates.append("constraints_json = ?")
                    values.append(json.dumps(data['constraints'], ensure_ascii=False))

                if updates:
                    updates.append("updated_at = CURRENT_TIMESTAMP")
                    values.append(plan_id)
                    sql = f"UPDATE rotation_plans SET {', '.join(updates)} WHERE id = ?"
                    conn.execute(sql, values)

                # 詳細更新（全削除して再作成）
                if 'details' in data:
                    conn.execute("DELETE FROM plan_details WHERE plan_id = ?", (plan_id,))
                    for detail in data['details']:
                        conn.execute("""
                            INSERT INTO plan_details (plan_id, field_id, year, crop)
                            VALUES (?, ?, ?, ?)
                        """, (plan_id, detail['field_id'], detail['year'], detail['crop']))

                logger.info(f"更新成功: 輪作計画 id={plan_id}")
                return True
        except sqlite3.IntegrityError as e:
            error_msg = str(e).lower()
            if "unique" in error_msg:
                raise DuplicateKeyError(f"重複データです: {e}")
            elif "not null" in error_msg:
                raise NotNullViolationError(f"必須項目が未入力です: {e}")
            elif "foreign key" in error_msg:
                raise ForeignKeyViolationError(f"参照先が存在しません: {e}")
            else:
                raise DatabaseError(f"データベースエラー: {e}")
        except sqlite3.Error as e:
            logger.error(f"操作失敗: 輪作計画更新 id={plan_id} - {e}")
            raise DatabaseError(f"データベースエラーが発生しました: {e}")

    @staticmethod
    def delete_plan(plan_id: int) -> bool:
        """
        輪作計画を削除

        Args:
            plan_id: 計画ID

        Returns:
            削除成功ならTrue
        """
        try:
            with get_db() as conn:
                cursor = conn.execute("DELETE FROM rotation_plans WHERE id = ?", (plan_id,))
                success = cursor.rowcount > 0
                if success:
                    logger.info(f"削除成功: 輪作計画 id={plan_id}")
                return success
        except sqlite3.IntegrityError as e:
            error_msg = str(e).lower()
            if "foreign key" in error_msg:
                raise ForeignKeyViolationError(f"参照先が存在します。削除できません: {e}")
            else:
                raise DatabaseError(f"データベースエラー: {e}")
        except sqlite3.Error as e:
            logger.error(f"操作失敗: 輪作計画削除 id={plan_id} - {e}")
            raise DatabaseError(f"データベースエラーが発生しました: {e}")


# =============================================================================
# JA職員用リポジトリ（組織内全データアクセス）
# =============================================================================

class JAStaffRepository:
    """JA職員用のデータアクセス（組織内全農家のデータ参照）"""

    @staticmethod
    def get_all_fields(org_id: int) -> List[Dict[str, Any]]:
        """
        組織内の全ほ場を取得

        Args:
            org_id: 組織ID

        Returns:
            ほ場データのリスト（農家情報付き）
        """
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT f.*, u.username, u.display_name as farmer_name
                FROM fields f
                JOIN users u ON f.user_id = u.id
                WHERE u.org_id = ?
                ORDER BY u.display_name, f.field_code
            """, (org_id,))
            return rows_to_list(cursor.fetchall())

    @staticmethod
    def get_all_farmers(org_id: int) -> List[Dict[str, Any]]:
        """
        組織内の農家一覧を取得

        Args:
            org_id: 組織ID

        Returns:
            農家データのリスト（ほ場数付き）
        """
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT u.id, u.username, u.display_name, u.email, u.created_at,
                       COUNT(f.id) as field_count,
                       COALESCE(SUM(f.area_ha), 0) as total_area_ha
                FROM users u
                LEFT JOIN fields f ON u.id = f.user_id
                WHERE u.org_id = ? AND u.role = 'farmer'
                GROUP BY u.id
                ORDER BY u.display_name
            """, (org_id,))
            return rows_to_list(cursor.fetchall())

    @staticmethod
    def get_aggregate_stats(org_id: int) -> Dict[str, Any]:
        """
        組織の集計データを取得

        Args:
            org_id: 組織ID

        Returns:
            集計データ
        """
        with get_db() as conn:
            stats = {}

            # 農家数
            cursor = conn.execute("""
                SELECT COUNT(*) as count FROM users
                WHERE org_id = ? AND role = 'farmer'
            """, (org_id,))
            stats['farmer_count'] = cursor.fetchone()['count']

            # ほ場数・総面積
            cursor = conn.execute("""
                SELECT COUNT(*) as count, COALESCE(SUM(area_ha), 0) as total_area
                FROM fields f
                JOIN users u ON f.user_id = u.id
                WHERE u.org_id = ?
            """, (org_id,))
            row = cursor.fetchone()
            stats['field_count'] = row['count']
            stats['total_area_ha'] = row['total_area']

            # 作物別面積（最新年）
            cursor = conn.execute("""
                SELECT ch.crop, SUM(f.area_ha) as area_ha, COUNT(*) as field_count
                FROM crop_history ch
                JOIN fields f ON ch.field_id = f.id
                JOIN users u ON f.user_id = u.id
                WHERE u.org_id = ?
                AND ch.year = (SELECT MAX(year) FROM crop_history)
                GROUP BY ch.crop
                ORDER BY area_ha DESC
            """, (org_id,))
            stats['crop_areas'] = rows_to_list(cursor.fetchall())

            return stats

    @staticmethod
    def get_orders_by_org(org_id: int, start_date: str = None, end_date: str = None) -> List[Dict[str, Any]]:
        """
        組織内の全農家の発注データを取得

        Args:
            org_id: 組織ID
            start_date: 開始日（YYYY-MM-DD形式、任意）
            end_date: 終了日（YYYY-MM-DD形式、任意）

        Returns:
            発注データのリスト
        """
        with get_db() as conn:
            query = """
                SELECT
                    po.id,
                    po.name as order_name,
                    po.target_year,
                    po.status,
                    po.created_at,
                    po.order_data_json,
                    u.id as user_id,
                    u.username,
                    u.display_name as farmer_name
                FROM pesticide_orders po
                JOIN users u ON po.user_id = u.id
                WHERE u.org_id = ?
            """
            params = [org_id]

            if start_date:
                query += " AND date(po.created_at) >= ?"
                params.append(start_date)
            if end_date:
                query += " AND date(po.created_at) <= ?"
                params.append(end_date)

            query += " ORDER BY po.created_at DESC"

            cursor = conn.execute(query, params)
            results = rows_to_list(cursor.fetchall())

            # order_data_json をパース
            for r in results:
                if r.get('order_data_json'):
                    try:
                        r['order_data'] = json.loads(r['order_data_json'])
                    except (ValueError, json.JSONDecodeError):
                        r['order_data'] = {}
                else:
                    r['order_data'] = {}

            return results

    @staticmethod
    def get_aggregate_orders_by_org(org_id: int, target_year: str = None) -> List[Dict[str, Any]]:
        """
        組織全体の農薬別発注集計

        Args:
            org_id: 組織ID
            target_year: 対象年（任意）

        Returns:
            農薬別集計リスト
            [{pesticide_name, total_quantity, unit, farmer_count}, ...]
        """
        with get_db() as conn:
            query = """
                SELECT po.order_data_json, u.id as user_id
                FROM pesticide_orders po
                JOIN users u ON po.user_id = u.id
                WHERE u.org_id = ?
            """
            params = [org_id]

            if target_year:
                query += " AND po.target_year = ?"
                params.append(target_year)

            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

            # 農薬別に集計
            pesticide_totals = {}  # {pesticide_name: {quantity, unit, farmers: set}}

            for row in rows:
                user_id = row['user_id']
                order_data_json = row['order_data_json']
                if not order_data_json:
                    continue

                try:
                    order_data = json.loads(order_data_json)
                except (ValueError, json.JSONDecodeError):
                    continue

                summary = order_data.get('summary', [])
                for item in summary:
                    name = item.get('pesticide_name') or item.get('農薬名')
                    if not name:
                        continue

                    amount = item.get('amount') or item.get('必要量') or 0
                    unit = item.get('unit') or item.get('単位') or ''

                    if name not in pesticide_totals:
                        pesticide_totals[name] = {
                            'quantity': 0,
                            'unit': unit,
                            'farmers': set()
                        }

                    try:
                        pesticide_totals[name]['quantity'] += float(amount)
                    except (ValueError, TypeError):
                        pass
                    pesticide_totals[name]['farmers'].add(user_id)

            # 結果をリスト化
            results = []
            for name, data in sorted(pesticide_totals.items()):
                results.append({
                    'pesticide_name': name,
                    'total_quantity': round(data['quantity'], 2),
                    'unit': data['unit'],
                    'farmer_count': len(data['farmers'])
                })

            return results


# =============================================================================
# ユーザーリポジトリ
# =============================================================================

class UserRepository:
    """ユーザーのCRUD操作"""

    @staticmethod
    def get_user(user_id: int) -> Optional[Dict[str, Any]]:
        """ユーザー情報を取得"""
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT u.*, o.name as org_name
                FROM users u
                LEFT JOIN organizations o ON u.org_id = o.id
                WHERE u.id = ?
            """, (user_id,))
            return row_to_dict(cursor.fetchone())

    @staticmethod
    def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
        """ユーザー名でユーザーを取得"""
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT * FROM users WHERE username = ?
            """, (username,))
            return row_to_dict(cursor.fetchone())

    @staticmethod
    def create_user(data: Dict[str, Any]) -> int:
        """ユーザーを作成"""
        try:
            with get_db() as conn:
                cursor = conn.execute("""
                    INSERT INTO users (username, password_hash, display_name, email, role, org_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    data['username'],
                    data['password_hash'],
                    data['display_name'],
                    data.get('email'),
                    data.get('role', 'farmer'),
                    data.get('org_id')
                ))
                user_id = cursor.lastrowid
                logger.info(f"作成成功: ユーザー username={data.get('username')} id={user_id}")
                return user_id
        except sqlite3.IntegrityError as e:
            error_msg = str(e).lower()
            if "unique" in error_msg:
                raise DuplicateKeyError(f"重複データです: {e}")
            elif "not null" in error_msg:
                raise NotNullViolationError(f"必須項目が未入力です: {e}")
            elif "foreign key" in error_msg:
                raise ForeignKeyViolationError(f"参照先が存在しません: {e}")
            else:
                raise DatabaseError(f"データベースエラー: {e}")
        except sqlite3.Error as e:
            logger.error(f"操作失敗: ユーザー作成 - {e}")
            raise DatabaseError(f"データベースエラーが発生しました: {e}")

    @staticmethod
    def authenticate(username: str, password_hash: str) -> Optional[Dict[str, Any]]:
        """認証（パスワードハッシュで照合）"""
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT * FROM users
                WHERE username = ? AND password_hash = ? AND is_active = 1
            """, (username, password_hash))
            return row_to_dict(cursor.fetchone())


# =============================================================================
# 防除マスタリポジトリ
# =============================================================================

class PesticideMasterRepository:
    """防除マスタのCRUD操作"""

    @staticmethod
    def get_by_crop(crop: str, org_id: int = None) -> List[Dict[str, Any]]:
        """作物の防除データを取得"""
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT * FROM pesticide_masters
                WHERE crop = ? AND (org_id IS NULL OR org_id = ?)
                ORDER BY name
            """, (crop, org_id))
            return rows_to_list(cursor.fetchall())

    @staticmethod
    def get_all(org_id: int = None) -> List[Dict[str, Any]]:
        """全防除マスタを取得"""
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT * FROM pesticide_masters
                WHERE org_id IS NULL OR org_id = ?
                ORDER BY crop, name
            """, (org_id,))
            return rows_to_list(cursor.fetchall())

    @staticmethod
    def get_by_id(master_id: int) -> Optional[Dict[str, Any]]:
        """IDで防除マスタを取得"""
        with get_db() as conn:
            cursor = conn.execute(
                "SELECT * FROM pesticide_masters WHERE id = ?",
                (master_id,)
            )
            return row_to_dict(cursor.fetchone())

    @staticmethod
    def create(data: Dict[str, Any]) -> int:
        """防除マスタを作成"""
        with get_db() as conn:
            cursor = conn.execute("""
                INSERT INTO pesticide_masters
                (org_id, name, crop, category, manufacturer, active_ingredient,
                 usage_timing, dilution_rate, application_method, safety_interval, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data.get('org_id'),
                data.get('name'),
                data.get('crop'),
                data.get('category'),
                data.get('manufacturer'),
                data.get('active_ingredient'),
                data.get('usage_timing'),
                data.get('dilution_rate'),
                data.get('application_method'),
                data.get('safety_interval'),
                data.get('notes'),
            ))
            return cursor.lastrowid

    @staticmethod
    def update(master_id: int, data: Dict[str, Any]) -> bool:
        """防除マスタを更新"""
        with get_db() as conn:
            cursor = conn.execute("""
                UPDATE pesticide_masters SET
                    name = ?,
                    crop = ?,
                    category = ?,
                    manufacturer = ?,
                    active_ingredient = ?,
                    usage_timing = ?,
                    dilution_rate = ?,
                    application_method = ?,
                    safety_interval = ?,
                    notes = ?
                WHERE id = ?
            """, (
                data.get('name'),
                data.get('crop'),
                data.get('category'),
                data.get('manufacturer'),
                data.get('active_ingredient'),
                data.get('usage_timing'),
                data.get('dilution_rate'),
                data.get('application_method'),
                data.get('safety_interval'),
                data.get('notes'),
                master_id,
            ))
            return cursor.rowcount > 0

    @staticmethod
    def delete(master_id: int) -> bool:
        """防除マスタを削除"""
        with get_db() as conn:
            cursor = conn.execute(
                "DELETE FROM pesticide_masters WHERE id = ?",
                (master_id,)
            )
            return cursor.rowcount > 0

    @staticmethod
    def bulk_import(records: List[Dict[str, Any]], org_id: int = None) -> int:
        """CSVからの一括インポート（新スキーマ対応）"""
        try:
            count = 0
            with get_db() as conn:
                for record in records:
                    record['org_id'] = org_id
                    # 旧カラム名からの変換（互換性のため）
                    name = record.get('name') or record.get('pesticide_name')
                    conn.execute("""
                        INSERT INTO pesticide_masters
                        (org_id, name, crop, category, manufacturer, active_ingredient,
                         usage_timing, dilution_rate, application_method, safety_interval, notes)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        record.get('org_id'),
                        name,
                        record.get('crop'),
                        record.get('category'),
                        record.get('manufacturer'),
                        record.get('active_ingredient'),
                        record.get('usage_timing'),
                        record.get('dilution_rate'),
                        record.get('application_method'),
                        record.get('safety_interval'),
                        record.get('notes'),
                    ))
                    count += 1
            logger.info(f"作成成功: 防除マスタ一括インポート {count}件")
            return count
        except sqlite3.IntegrityError as e:
            error_msg = str(e).lower()
            if "unique" in error_msg:
                raise DuplicateKeyError(f"重複データです: {e}")
            elif "not null" in error_msg:
                raise NotNullViolationError(f"必須項目が未入力です: {e}")
            elif "foreign key" in error_msg:
                raise ForeignKeyViolationError(f"参照先が存在しません: {e}")
            else:
                raise DatabaseError(f"データベースエラー: {e}")
        except sqlite3.Error as e:
            logger.error(f"操作失敗: 防除マスタ一括インポート - {e}")
            raise DatabaseError(f"データベースエラーが発生しました: {e}")

    @staticmethod
    def delete_all(org_id: int = None) -> int:
        """全レコード削除（インポート前のクリア用）"""
        with get_db() as conn:
            if org_id is None:
                cursor = conn.execute("DELETE FROM pesticide_masters WHERE org_id IS NULL")
            else:
                cursor = conn.execute(
                    "DELETE FROM pesticide_masters WHERE org_id = ?",
                    (org_id,)
                )
            return cursor.rowcount


# =============================================================================
# 作物マスタリポジトリ
# =============================================================================

def ensure_crop_tables():
    """
    crop_master と user_crops テーブルが存在しない場合は作成し、初期データを投入する
    """
    with get_db() as conn:
        # crop_master テーブル
        cursor = conn.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='crop_master'
        """)
        if cursor.fetchone() is None:
            conn.execute("""
                CREATE TABLE crop_master (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    category TEXT,
                    family TEXT DEFAULT NULL,
                    display_order INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # 初期データ投入（FAMIC表記に準拠）
            initial_crops = [
                ('小麦(春播)', '穀物', 1, 'イネ科'),
                ('小麦(秋播)', '穀物', 2, 'イネ科'),
                ('だいず', '豆類', 3, 'マメ科'),
                ('てんさい', '根菜', 4, 'アカザ科'),
                ('ばれいしょ', '根菜', 5, 'ナス科'),
                ('あずき', '豆類', 6, 'マメ科'),
                ('にんじん', '野菜', 7, 'セリ科'),
                ('かぼちゃ', '野菜', 8, 'ウリ科'),
                ('キャベツ', '野菜', 9, 'アブラナ科'),
                ('だいこん', '野菜', 10, 'アブラナ科'),
            ]
            for name, category, order, family in initial_crops:
                conn.execute("""
                    INSERT INTO crop_master (name, category, display_order, family)
                    VALUES (?, ?, ?, ?)
                """, (name, category, order, family))

        # user_crops テーブル
        cursor = conn.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='user_crops'
        """)
        if cursor.fetchone() is None:
            conn.execute("""
                CREATE TABLE user_crops (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    parent_crop_id INTEGER NOT NULL,
                    custom_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (parent_crop_id) REFERENCES crop_master(id),
                    UNIQUE(user_id, parent_crop_id, custom_name)
                )
            """)

        conn.commit()


class CropMasterRepository:
    """作物マスタのCRUD操作（JA管理）"""

    @staticmethod
    def get_all(active_only: bool = True) -> List[Dict[str, Any]]:
        """全作物を取得"""
        with get_db() as conn:
            if active_only:
                cursor = conn.execute("""
                    SELECT * FROM crop_master
                    WHERE is_active = 1
                    ORDER BY display_order, name
                """)
            else:
                cursor = conn.execute("""
                    SELECT * FROM crop_master
                    ORDER BY display_order, name
                """)
            return rows_to_list(cursor.fetchall())

    @staticmethod
    def get_by_id(crop_id: int) -> Optional[Dict[str, Any]]:
        """IDで作物を取得"""
        with get_db() as conn:
            cursor = conn.execute(
                "SELECT * FROM crop_master WHERE id = ?", (crop_id,)
            )
            return row_to_dict(cursor.fetchone())

    @staticmethod
    def get_by_name(name: str) -> Optional[Dict[str, Any]]:
        """名前で作物を取得"""
        with get_db() as conn:
            cursor = conn.execute(
                "SELECT * FROM crop_master WHERE name = ?", (name,)
            )
            return row_to_dict(cursor.fetchone())

    @staticmethod
    def get_family_map() -> Dict[str, str]:
        """作物名→科名マッピング取得。UserCropも解決。

        Returns:
            {作物名: 科名} の辞書。familyがNULLの作物は除外。
        """
        with get_db() as conn:
            # crop_masterから直接取得
            cursor = conn.execute("""
                SELECT name, family FROM crop_master
                WHERE family IS NOT NULL AND is_active = 1
            """)
            family_map = {row['name']: row['family'] for row in cursor.fetchall()}

            # UserCropのcustom_nameも解決（親のfamilyを引き継ぐ）
            cursor = conn.execute("""
                SELECT uc.custom_name, cm.family
                FROM user_crops uc
                INNER JOIN crop_master cm ON cm.id = uc.parent_crop_id
                WHERE uc.custom_name IS NOT NULL AND cm.family IS NOT NULL
            """)
            for row in cursor.fetchall():
                family_map[row['custom_name']] = row['family']

            return family_map

    @staticmethod
    def create(name: str, display_order: int = 0, family: str = None) -> int:
        """作物を追加"""
        with get_db() as conn:
            cursor = conn.execute("""
                INSERT INTO crop_master (name, family, display_order)
                VALUES (?, ?, ?)
            """, (name, family, display_order))
            conn.commit()
            return cursor.lastrowid

    @staticmethod
    def update(crop_id: int, data: Dict[str, Any]) -> bool:
        """作物を更新"""
        with get_db() as conn:
            fields = []
            values = []
            for key in ['name', 'family', 'display_order', 'is_active']:
                if key in data:
                    fields.append(f"{key} = ?")
                    values.append(data[key])

            if not fields:
                return False

            values.append(crop_id)
            conn.execute(f"""
                UPDATE crop_master SET {', '.join(fields)}
                WHERE id = ?
            """, values)
            conn.commit()
            return True

    @staticmethod
    def delete(crop_id: int) -> bool:
        """作物を削除（非アクティブ化）"""
        with get_db() as conn:
            conn.execute(
                "UPDATE crop_master SET is_active = 0 WHERE id = ?",
                (crop_id,)
            )
            conn.commit()
            return True


# =============================================================================
# ユーザー作物リポジトリ
# =============================================================================

class UserCropRepository:
    """
    ユーザーが選択した作物のCRUD操作

    user_cropsテーブル構造:
        - id: 主キー
        - user_id: ユーザーID
        - parent_crop_id: 親作物ID（crop_masterへの参照、防除連携用）
        - custom_name: カスタム名（NULL=マスタ名をそのまま使用）
        - created_at: 作成日時
    """

    @staticmethod
    def get_user_crops(user_id: int) -> List[Dict[str, Any]]:
        """
        ユーザーの選択した作物を取得

        Returns:
            作物リスト。各要素は:
            - id: user_crops.id
            - parent_crop_id: crop_master.id
            - parent_name: crop_master.name（防除連携用）
            - name: 表示名（custom_nameがあればそれ、なければparent_name）
            - custom_name: カスタム名（NULLの場合あり）
        """
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT
                    uc.id,
                    uc.parent_crop_id,
                    cm.name as parent_name,
                    uc.custom_name,
                    COALESCE(uc.custom_name, cm.name) as name
                FROM user_crops uc
                INNER JOIN crop_master cm ON cm.id = uc.parent_crop_id
                WHERE uc.user_id = ? AND cm.is_active = 1
                ORDER BY cm.display_order, name
            """, (user_id,))
            return rows_to_list(cursor.fetchall())

    @staticmethod
    def get_user_crop_ids(user_id: int) -> List[int]:
        """ユーザーの選択した親作物IDリストを取得（重複なし）"""
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT DISTINCT parent_crop_id FROM user_crops
                WHERE user_id = ?
            """, (user_id,))
            return [row[0] for row in cursor.fetchall()]

    @staticmethod
    def set_user_crops(user_id: int, crop_ids: List[int]) -> bool:
        """
        ユーザーの作物選択を設定（マスタからの選択、カスタム名なし）
        既存のカスタム名なしエントリのみ削除して再登録
        """
        try:
            with get_db() as conn:
                # カスタム名なしのエントリを削除
                conn.execute("""
                    DELETE FROM user_crops
                    WHERE user_id = ? AND custom_name IS NULL
                """, (user_id,))

                # 新規登録
                for crop_id in crop_ids:
                    conn.execute("""
                        INSERT OR IGNORE INTO user_crops (user_id, parent_crop_id, custom_name)
                        VALUES (?, ?, NULL)
                    """, (user_id, crop_id))

                conn.commit()
                logger.info(f"作成成功: ユーザー作物選択 user_id={user_id} {len(crop_ids)}件")
                return True
        except sqlite3.IntegrityError as e:
            error_msg = str(e).lower()
            if "foreign key" in error_msg:
                raise ForeignKeyViolationError(f"参照先が存在しません: {e}")
            else:
                raise DatabaseError(f"データベースエラー: {e}")
        except sqlite3.Error as e:
            logger.error(f"操作失敗: ユーザー作物選択設定 user_id={user_id} - {e}")
            raise DatabaseError(f"データベースエラーが発生しました: {e}")

    @staticmethod
    def add_user_crop(user_id: int, parent_crop_id: int, custom_name: str = None) -> int:
        """
        ユーザーに作物を追加

        Args:
            user_id: ユーザーID
            parent_crop_id: 親作物ID（crop_master.id）
            custom_name: カスタム名（例: "ブロッコリー（2作目）"）

        Returns:
            新規作成されたuser_crops.id
        """
        try:
            with get_db() as conn:
                cursor = conn.execute("""
                    INSERT INTO user_crops (user_id, parent_crop_id, custom_name)
                    VALUES (?, ?, ?)
                """, (user_id, parent_crop_id, custom_name))
                conn.commit()
                user_crop_id = cursor.lastrowid
                logger.info(f"作成成功: ユーザー作物追加 user_id={user_id} crop_id={parent_crop_id} id={user_crop_id}")
                return user_crop_id
        except sqlite3.IntegrityError as e:
            error_msg = str(e).lower()
            if "unique" in error_msg:
                raise DuplicateKeyError(f"重複データです: {e}")
            elif "foreign key" in error_msg:
                raise ForeignKeyViolationError(f"参照先が存在しません: {e}")
            else:
                raise DatabaseError(f"データベースエラー: {e}")
        except sqlite3.Error as e:
            logger.error(f"操作失敗: ユーザー作物追加 user_id={user_id} - {e}")
            raise DatabaseError(f"データベースエラーが発生しました: {e}")

    @staticmethod
    def remove_user_crop(user_id: int, user_crop_id: int) -> bool:
        """ユーザーから作物を削除（user_crops.idで指定）"""
        with get_db() as conn:
            conn.execute("""
                DELETE FROM user_crops
                WHERE user_id = ? AND id = ?
            """, (user_id, user_crop_id))
            conn.commit()
            return True

    @staticmethod
    def remove_user_crop_by_parent(user_id: int, parent_crop_id: int, custom_name: str = None) -> bool:
        """ユーザーから作物を削除（parent_crop_id + custom_nameで指定）"""
        with get_db() as conn:
            if custom_name:
                conn.execute("""
                    DELETE FROM user_crops
                    WHERE user_id = ? AND parent_crop_id = ? AND custom_name = ?
                """, (user_id, parent_crop_id, custom_name))
            else:
                conn.execute("""
                    DELETE FROM user_crops
                    WHERE user_id = ? AND parent_crop_id = ? AND custom_name IS NULL
                """, (user_id, parent_crop_id))
            conn.commit()
            return True

    @staticmethod
    def get_parent_crop_id_by_name(user_id: int, crop_name: str) -> Optional[int]:
        """
        作物名から親作物IDを取得（防除連携用）

        Args:
            user_id: ユーザーID
            crop_name: 作物名（カスタム名 or マスタ名）

        Returns:
            parent_crop_id（見つからない場合はNone）
        """
        with get_db() as conn:
            # まずカスタム名で検索
            cursor = conn.execute("""
                SELECT parent_crop_id FROM user_crops
                WHERE user_id = ? AND custom_name = ?
            """, (user_id, crop_name))
            row = cursor.fetchone()
            if row:
                return row[0]

            # 次にマスタ名で検索
            cursor = conn.execute("""
                SELECT uc.parent_crop_id FROM user_crops uc
                INNER JOIN crop_master cm ON cm.id = uc.parent_crop_id
                WHERE uc.user_id = ? AND cm.name = ? AND uc.custom_name IS NULL
            """, (user_id, crop_name))
            row = cursor.fetchone()
            if row:
                return row[0]

            return None


# =============================================================================
# 農薬発注リポジトリ
# =============================================================================

class PesticideOrderRepository:
    """農薬発注リストのCRUD操作"""

    @staticmethod
    def get_orders(user_id: int, year: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        ユーザーの発注リスト一覧を取得

        Args:
            user_id: ユーザーID
            year: 対象年（任意）。指定時は target_year でフィルタ

        Returns:
            発注リストのリスト（id, name, target_year, status, created_at, updated_at）
        """
        with get_db() as conn:
            if year is not None:
                cursor = conn.execute("""
                    SELECT id, name, target_year, status, created_at, updated_at
                    FROM pesticide_orders
                    WHERE user_id = ? AND target_year = ?
                    ORDER BY updated_at DESC
                """, (user_id, str(year)))
            else:
                cursor = conn.execute("""
                    SELECT id, name, target_year, status, created_at, updated_at
                    FROM pesticide_orders
                    WHERE user_id = ?
                    ORDER BY updated_at DESC
                """, (user_id,))
            return rows_to_list(cursor.fetchall())

    @staticmethod
    def get_order(order_id: int) -> Optional[Dict[str, Any]]:
        """
        発注リスト詳細を取得（order_data_jsonをdictに展開）

        Args:
            order_id: 発注ID

        Returns:
            発注リスト詳細（見つからない場合はNone）
        """
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT * FROM pesticide_orders WHERE id = ?
            """, (order_id,))
            order = row_to_dict(cursor.fetchone())
            if not order:
                return None

            # order_data_json をパース
            if order.get('order_data_json'):
                order['order_data'] = json.loads(order['order_data_json'])
            else:
                order['order_data'] = {}

            return order

    @staticmethod
    def create_order(user_id: int, data: Dict[str, Any]) -> int:
        """
        発注リストを作成

        Args:
            user_id: ユーザーID
            data: 発注データ
                - name: 発注リスト名（必須）
                - target_year: 対象年（必須）
                - rotation_plan_id: 輪作計画ID（任意）
                - area_unit: 面積単位（デフォルト: 'ha'）
                - order_data: 発注内容（dict、JSON化して保存）

        Returns:
            作成された発注リストのID
        """
        with get_db() as conn:
            order_data_json = json.dumps(data.get('order_data', {}), ensure_ascii=False)

            cursor = conn.execute("""
                INSERT INTO pesticide_orders
                (user_id, name, rotation_plan_id, target_year, area_unit, order_data_json, status)
                VALUES (?, ?, ?, ?, ?, ?, 'draft')
            """, (
                user_id,
                data['name'],
                data.get('rotation_plan_id'),
                data['target_year'],
                data.get('area_unit', 'ha'),
                order_data_json
            ))
            conn.commit()
            return cursor.lastrowid

    @staticmethod
    def update_order(order_id: int, data: Dict[str, Any]) -> bool:
        """
        発注リストを更新

        Args:
            order_id: 発注ID
            data: 更新データ（name, target_year, area_unit, order_data, status等）

        Returns:
            更新成功ならTrue
        """
        with get_db() as conn:
            updates = []
            values = []

            if 'name' in data:
                updates.append("name = ?")
                values.append(data['name'])

            if 'target_year' in data:
                updates.append("target_year = ?")
                values.append(data['target_year'])

            if 'area_unit' in data:
                updates.append("area_unit = ?")
                values.append(data['area_unit'])

            if 'order_data' in data:
                updates.append("order_data_json = ?")
                values.append(json.dumps(data['order_data'], ensure_ascii=False))

            if 'status' in data:
                updates.append("status = ?")
                values.append(data['status'])

            if not updates:
                return False

            updates.append("updated_at = CURRENT_TIMESTAMP")
            values.append(order_id)

            conn.execute(f"""
                UPDATE pesticide_orders
                SET {', '.join(updates)}
                WHERE id = ?
            """, tuple(values))
            conn.commit()
            return True

    @staticmethod
    def delete_order(order_id: int) -> bool:
        """
        発注リストを削除

        Args:
            order_id: 発注ID

        Returns:
            削除成功ならTrue
        """
        with get_db() as conn:
            cursor = conn.execute("""
                DELETE FROM pesticide_orders WHERE id = ?
            """, (order_id,))
            conn.commit()
            return cursor.rowcount > 0


# =============================================================================
# 移行ユーティリティ
# =============================================================================

class MigrationUtils:
    """既存JSONデータからの移行ユーティリティ"""

    @staticmethod
    def migrate_json_fields(user_id: int, json_path: Path = None) -> Tuple[int, List[str]]:
        """
        fields.jsonからほ場データを移行

        Args:
            user_id: 移行先ユーザーID
            json_path: JSONファイルパス（デフォルト: data/fields.json）

        Returns:
            (移行件数, エラーリスト)
        """
        if json_path is None:
            json_path = JSON_DATA_DIR / "fields.json"

        if not json_path.exists():
            return 0, ["ファイルが見つかりません: " + str(json_path)]

        errors = []
        count = 0

        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        for field in data.get('fields', []):
            try:
                # 既存チェック
                existing = FieldRepository.get_field_by_code(user_id, field['field_id'])
                if existing:
                    errors.append(f"スキップ（既存）: {field['field_id']}")
                    continue

                FieldRepository.create_field(user_id, {
                    'field_code': field['field_id'],
                    'district': field.get('district'),
                    'name': field.get('name'),
                    'area_ha': field.get('area_ha', field.get('area_a', 0) / 100),
                    'beet_forbidden': 1 if field.get('beet_forbidden') else 0,
                    'coordinates_json': json.dumps(field.get('coordinates')) if field.get('coordinates') else None
                })
                count += 1
            except Exception as e:
                errors.append(f"エラー ({field.get('field_id', '?')}): {str(e)}")

        return count, errors

    @staticmethod
    def migrate_json_plans(user_id: int, plans_dir: Path = None) -> Tuple[int, List[str]]:
        """
        rotation_plans/ディレクトリから輪作計画を移行

        Args:
            user_id: 移行先ユーザーID
            plans_dir: 計画ディレクトリパス

        Returns:
            (移行件数, エラーリスト)
        """
        if plans_dir is None:
            plans_dir = JSON_DATA_DIR / "rotation_plans"

        if not plans_dir.exists():
            return 0, ["ディレクトリが見つかりません: " + str(plans_dir)]

        errors = []
        count = 0

        for plan_file in plans_dir.glob("*.json"):
            try:
                with open(plan_file, 'r', encoding='utf-8') as f:
                    plan_data = json.load(f)

                # 計画作成
                PlanRepository.create_plan(user_id, {
                    'name': plan_data.get('name', plan_file.stem),
                    'start_year': plan_data.get('start_year', 'R5'),
                    'end_year': plan_data.get('end_year', 'R10'),
                    'constraints': plan_data.get('constraints', {}),
                    'metadata': plan_data.get('metadata', {}),
                    'details': []  # 詳細は別途移行が必要
                })
                count += 1
            except Exception as e:
                errors.append(f"エラー ({plan_file.name}): {str(e)}")

        return count, errors

    @staticmethod
    def migrate_pesticide_master(csv_path: Path = None, org_id: int = None) -> Tuple[int, List[str]]:
        """
        pesticide_master.csvから防除マスタを移行

        Args:
            csv_path: CSVファイルパス
            org_id: 組織ID（NULLなら共通マスタ）

        Returns:
            (移行件数, エラーリスト)
        """
        import csv

        if csv_path is None:
            csv_path = Path(__file__).parent / "pesticide_master.csv"

        if not csv_path.exists():
            return 0, ["ファイルが見つかりません: " + str(csv_path)]

        errors = []
        count = 0

        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            with get_db() as conn:
                for row in reader:
                    try:
                        conn.execute("""
                            INSERT INTO pesticide_masters
                            (org_id, crop, month, period, target, pesticide_name,
                             dilution_rate, amount_per_10a, unit, days_before_harvest, notes)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            org_id,
                            row.get('crop'),
                            int(row['month']) if row.get('month') else None,
                            row.get('period'),
                            row.get('target'),
                            row.get('pesticide_name'),
                            row.get('dilution_rate'),
                            float(row['amount_per_10a']) if row.get('amount_per_10a') else None,
                            row.get('unit'),
                            row.get('days_before_harvest'),
                            row.get('notes')
                        ))
                        count += 1
                    except Exception as e:
                        errors.append(f"エラー: {str(e)}")

        return count, errors


# =============================================================================
# UserConstraintsRepository - ユーザー輪作制約設定
# =============================================================================

class UserConstraintsRepository:
    """ユーザーごとの輪作制約設定リポジトリ"""

    @staticmethod
    def get_constraints(user_id: int) -> Optional[Dict[str, Any]]:
        """
        ユーザーの制約設定を取得

        Returns:
            {
                'constraints': [...],  # 制約テーブル（リスト形式）
                'forbidden_transitions': str,
                'preferred_transitions': str,
                'main_crops': str
            }
        """
        with get_db() as conn:
            cursor = conn.execute(
                "SELECT * FROM user_constraints WHERE user_id = ?",
                (user_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            data = dict(row)
            # JSONをパース
            if data.get('constraints_json'):
                data['constraints'] = json.loads(data['constraints_json'])
            else:
                data['constraints'] = []
            return data

    @staticmethod
    def save_constraints(user_id: int, constraints: list, forbidden_transitions: str = "",
                         preferred_transitions: str = "", main_crops: str = "") -> bool:
        """
        ユーザーの制約設定を保存（INSERT OR REPLACE）

        Args:
            user_id: ユーザーID
            constraints: 制約テーブル（リスト形式）
            forbidden_transitions: 禁止遷移（テキスト形式）
            preferred_transitions: 優先遷移（テキスト形式）
            main_crops: 主作物（テキスト形式）

        Returns:
            成功時True
        """
        try:
            constraints_json = json.dumps(constraints, ensure_ascii=False)
            with get_db() as conn:
                conn.execute("""
                    INSERT INTO user_constraints (user_id, constraints_json, forbidden_transitions,
                                                  preferred_transitions, main_crops, updated_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(user_id) DO UPDATE SET
                        constraints_json = excluded.constraints_json,
                        forbidden_transitions = excluded.forbidden_transitions,
                        preferred_transitions = excluded.preferred_transitions,
                        main_crops = excluded.main_crops,
                        updated_at = CURRENT_TIMESTAMP
                """, (user_id, constraints_json, forbidden_transitions, preferred_transitions, main_crops))
            logger.info(f"作成成功: ユーザー制約設定 user_id={user_id}")
            return True
        except sqlite3.IntegrityError as e:
            error_msg = str(e).lower()
            if "foreign key" in error_msg:
                raise ForeignKeyViolationError(f"参照先が存在しません: {e}")
            else:
                raise DatabaseError(f"データベースエラー: {e}")
        except sqlite3.Error as e:
            logger.error(f"操作失敗: ユーザー制約設定保存 user_id={user_id} - {e}")
            raise DatabaseError(f"データベースエラーが発生しました: {e}")

    @staticmethod
    def delete_constraints(user_id: int) -> bool:
        """ユーザーの制約設定を削除"""
        with get_db() as conn:
            conn.execute(
                "DELETE FROM user_constraints WHERE user_id = ?",
                (user_id,)
            )
        return True


# =============================================================================
# PesticideRegistryRepository - 農薬登録情報
# =============================================================================

class PesticideRegistryRepository:
    """農薬登録情報（FAMIC登録基本部）のリポジトリ"""

    @staticmethod
    def get_by_id(pesticide_id: int) -> Optional[Dict[str, Any]]:
        """IDで農薬を取得"""
        with get_db() as conn:
            cursor = conn.execute(
                "SELECT * FROM pesticide_registry WHERE id = ?",
                (pesticide_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_by_name(name: str) -> Optional[Dict[str, Any]]:
        """農薬名で取得（完全一致）"""
        with get_db() as conn:
            cursor = conn.execute(
                "SELECT * FROM pesticide_registry WHERE name = ?",
                (name,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    @staticmethod
    def search(keyword: str, limit: int = 50) -> List[Dict[str, Any]]:
        """農薬名で部分一致検索"""
        with get_db() as conn:
            cursor = conn.execute(
                "SELECT * FROM pesticide_registry WHERE name LIKE ? ORDER BY name LIMIT ?",
                (f"%{keyword}%", limit)
            )
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def get_by_registration_number(reg_no: str) -> Optional[Dict[str, Any]]:
        """登録番号で取得"""
        with get_db() as conn:
            cursor = conn.execute(
                "SELECT * FROM pesticide_registry WHERE registration_number = ?",
                (reg_no,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_all(limit: int = 1000) -> List[Dict[str, Any]]:
        """全件取得（制限付き）"""
        with get_db() as conn:
            cursor = conn.execute(
                "SELECT * FROM pesticide_registry ORDER BY name LIMIT ?",
                (limit,)
            )
            return [dict(row) for row in cursor.fetchall()]


# =============================================================================
# PesticideUsageRepository - 農薬適用情報
# =============================================================================

class PesticideUsageRepository:
    """農薬適用情報（FAMIC登録適用部）のリポジトリ"""

    @staticmethod
    def get_by_pesticide_id(pesticide_id: int) -> List[Dict[str, Any]]:
        """農薬IDで適用情報を取得"""
        with get_db() as conn:
            cursor = conn.execute(
                "SELECT * FROM pesticide_usage WHERE pesticide_id = ? ORDER BY crop",
                (pesticide_id,)
            )
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def get_by_crop(crop: str) -> List[Dict[str, Any]]:
        """作物名で適用情報を取得"""
        with get_db() as conn:
            cursor = conn.execute(
                """
                SELECT u.*, r.name as pesticide_name, r.category, r.formulation
                FROM pesticide_usage u
                JOIN pesticide_registry r ON u.pesticide_id = r.id
                WHERE u.crop = ?
                ORDER BY r.name
                """,
                (crop,)
            )
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def search_by_crop(keyword: str, limit: int = 100) -> List[Dict[str, Any]]:
        """作物名で部分一致検索"""
        with get_db() as conn:
            cursor = conn.execute(
                """
                SELECT u.*, r.name as pesticide_name, r.category
                FROM pesticide_usage u
                JOIN pesticide_registry r ON u.pesticide_id = r.id
                WHERE u.crop LIKE ?
                ORDER BY u.crop, r.name
                LIMIT ?
                """,
                (f"%{keyword}%", limit)
            )
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def get_distinct_crops(keyword: str = None, limit: int = 50) -> List[str]:
        """FAMIC適用情報からユニークな作物名一覧を取得"""
        with get_db() as conn:
            if keyword:
                cursor = conn.execute(
                    """
                    SELECT DISTINCT crop FROM pesticide_usage
                    WHERE crop LIKE ?
                    ORDER BY crop
                    LIMIT ?
                    """,
                    (f"%{keyword}%", limit)
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT DISTINCT crop FROM pesticide_usage
                    ORDER BY crop
                    LIMIT ?
                    """,
                    (limit,)
                )
            return [row[0] for row in cursor.fetchall() if row[0]]

    @staticmethod
    def get_for_pesticide_and_crop(pesticide_id: int, crop: str) -> List[Dict[str, Any]]:
        """特定農薬×作物の適用情報を取得"""
        with get_db() as conn:
            cursor = conn.execute(
                "SELECT * FROM pesticide_usage WHERE pesticide_id = ? AND crop = ?",
                (pesticide_id, crop)
            )
            return [dict(row) for row in cursor.fetchall()]


# =============================================================================
# PesticideRecordRepository - 防除記録
# =============================================================================

class PesticideRecordRepository:
    """防除記録のリポジトリ"""

    @staticmethod
    def get_records(user_id: int, field_id: int = None, year: Optional[int] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """ユーザーの防除記録を取得"""
        with get_db() as conn:
            clauses = ["r.user_id = ?"]
            params: list = [user_id]
            if field_id:
                clauses.append("r.field_id = ?")
                params.append(field_id)
            if year is not None:
                clauses.append("strftime('%Y', r.spray_date) = ?")
                params.append(str(year))
            params.append(limit)
            where_sql = " AND ".join(clauses)
            cursor = conn.execute(
                f"""
                SELECT r.*, f.field_code, f.name as field_name
                FROM pesticide_records r
                JOIN fields f ON r.field_id = f.id
                WHERE {where_sql}
                ORDER BY r.spray_date DESC
                LIMIT ?
                """,
                tuple(params),
            )
            return rows_to_list(cursor.fetchall())

    @staticmethod
    def create_record(user_id: int, data: Dict[str, Any]) -> int:
        """防除記録を作成"""
        with get_db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO pesticide_records
                (user_id, field_id, spray_date, pesticide_name, pesticide_id,
                 dilution_rate, spray_amount, spray_unit, photo_path, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    data.get("field_id"),
                    data.get("spray_date"),
                    data.get("pesticide_name"),
                    data.get("pesticide_id"),
                    data.get("dilution_rate"),
                    data.get("spray_amount"),
                    data.get("spray_unit"),
                    data.get("photo_path"),
                    data.get("notes"),
                )
            )
            conn.commit()
            return cursor.lastrowid

    @staticmethod
    def update_record(record_id: int, data: Dict[str, Any]) -> bool:
        """防除記録を更新"""
        with get_db() as conn:
            cursor = conn.execute(
                """
                UPDATE pesticide_records SET
                    field_id = ?,
                    spray_date = ?,
                    pesticide_name = ?,
                    pesticide_id = ?,
                    dilution_rate = ?,
                    spray_amount = ?,
                    spray_unit = ?,
                    photo_path = ?,
                    notes = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    data.get("field_id"),
                    data.get("spray_date"),
                    data.get("pesticide_name"),
                    data.get("pesticide_id"),
                    data.get("dilution_rate"),
                    data.get("spray_amount"),
                    data.get("spray_unit"),
                    data.get("photo_path"),
                    data.get("notes"),
                    record_id,
                )
            )
            conn.commit()
            return cursor.rowcount > 0

    @staticmethod
    def delete_record(record_id: int) -> bool:
        """防除記録を削除"""
        with get_db() as conn:
            cursor = conn.execute(
                "DELETE FROM pesticide_records WHERE id = ?",
                (record_id,)
            )
            conn.commit()
            return cursor.rowcount > 0


# =============================================================================
# 発注テンプレート
# =============================================================================

class OrderTemplateRepository:
    """発注テンプレートのCRUD操作"""

    @staticmethod
    def get_templates(user_id: int) -> List[Dict[str, Any]]:
        """ユーザーのテンプレート一覧を取得"""
        with get_db() as conn:
            cursor = conn.execute(
                """
                SELECT id, user_id, name, type, items_json, notes, created_at, updated_at
                FROM order_templates
                WHERE user_id = ?
                ORDER BY updated_at DESC
                """,
                (user_id,)
            )
            rows = cursor.fetchall()
            result = []
            for row in rows:
                item = dict(row)
                if item.get("items_json"):
                    item["items"] = json.loads(item["items_json"])
                else:
                    item["items"] = []
                result.append(item)
            return result

    @staticmethod
    def get_template(template_id: int) -> Optional[Dict[str, Any]]:
        """テンプレートを取得"""
        with get_db() as conn:
            cursor = conn.execute(
                """
                SELECT id, user_id, name, type, items_json, notes, created_at, updated_at
                FROM order_templates
                WHERE id = ?
                """,
                (template_id,)
            )
            row = cursor.fetchone()
            if row:
                item = dict(row)
                if item.get("items_json"):
                    item["items"] = json.loads(item["items_json"])
                else:
                    item["items"] = []
                return item
            return None

    @staticmethod
    def create_template(user_id: int, data: Dict[str, Any]) -> int:
        """テンプレートを作成"""
        with get_db() as conn:
            items_json = json.dumps(data.get("items", []), ensure_ascii=False)
            cursor = conn.execute(
                """
                INSERT INTO order_templates (user_id, name, type, items_json, notes)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    data.get("name"),
                    data.get("type", "custom"),
                    items_json,
                    data.get("notes"),
                )
            )
            conn.commit()
            return cursor.lastrowid

    @staticmethod
    def update_template(template_id: int, data: Dict[str, Any]) -> bool:
        """テンプレートを更新"""
        with get_db() as conn:
            items_json = json.dumps(data.get("items", []), ensure_ascii=False)
            cursor = conn.execute(
                """
                UPDATE order_templates
                SET name = ?, type = ?, items_json = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    data.get("name"),
                    data.get("type", "custom"),
                    items_json,
                    data.get("notes"),
                    template_id,
                )
            )
            conn.commit()
            return cursor.rowcount > 0

    @staticmethod
    def delete_template(template_id: int) -> bool:
        """テンプレートを削除"""
        with get_db() as conn:
            cursor = conn.execute(
                "DELETE FROM order_templates WHERE id = ?",
                (template_id,)
            )
            conn.commit()
            return cursor.rowcount > 0


# =============================================================================
# 在庫テーブル初期化
# =============================================================================

def ensure_inventory_tables():
    """
    inventory関連テーブルのマイグレーション
    - inventoryテーブルに新カラム追加（既存データ保持）
    - inventory_transactionsテーブル作成
    - inventory_csv_operationsテーブル作成
    """
    with get_db() as conn:
        # 1. inventoryテーブルにカラム追加（既存チェック付き）
        cursor = conn.execute("PRAGMA table_info(inventory)")
        existing_columns = {row[1] for row in cursor.fetchall()}

        new_columns = [
            ("storage_location", "TEXT"),
            ("expiry_date", "DATE"),
            ("purchase_date", "DATE"),
            ("purchase_price", "REAL"),
            ("supplier", "TEXT"),
            ("lot_number", "TEXT"),
            ("last_used_date", "DATE"),
            ("usage_count", "INTEGER DEFAULT 0"),
        ]

        for col_name, col_type in new_columns:
            if col_name not in existing_columns:
                try:
                    conn.execute(f"ALTER TABLE inventory ADD COLUMN [{col_name}] {col_type}")
                except Exception as e:
                    print(f"Warning: Failed to add column {col_name}: {e}")

        # 2. inventory_transactionsテーブル
        conn.execute("""
            CREATE TABLE IF NOT EXISTS inventory_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                inventory_id INTEGER NOT NULL REFERENCES inventory(id) ON DELETE CASCADE,
                transaction_type TEXT NOT NULL CHECK (transaction_type IN ('in', 'out', 'adjust')),
                quantity REAL NOT NULL,
                unit TEXT,
                reference_type TEXT,
                reference_id INTEGER,
                notes TEXT,
                created_by INTEGER REFERENCES users(id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_inv_trans_inventory ON inventory_transactions(inventory_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_inv_trans_type ON inventory_transactions(transaction_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_inv_trans_created ON inventory_transactions(created_at)")

        # 3. inventory_csv_operationsテーブル
        conn.execute("""
            CREATE TABLE IF NOT EXISTS inventory_csv_operations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operation_type TEXT NOT NULL CHECK (operation_type IN ('import', 'export')),
                filename TEXT,
                record_count INTEGER,
                status TEXT CHECK (status IN ('success', 'partial', 'failed')),
                error_message TEXT,
                created_by INTEGER REFERENCES users(id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_csv_ops_type ON inventory_csv_operations(operation_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_csv_ops_created ON inventory_csv_operations(created_at)")

        conn.commit()


# =============================================================================
# 在庫リポジトリ
# =============================================================================

class InventoryRepository:
    """在庫管理のリポジトリ"""

    @staticmethod
    def get_inventory_by_pesticide(user_id: int, pesticide_name: str) -> Optional[Dict[str, Any]]:
        """農薬名で在庫を取得"""
        with get_db() as conn:
            cursor = conn.execute(
                """
                SELECT id, user_id, pesticide_name, amount, unit,
                       storage_location, expiry_date, last_used_date, usage_count, updated_at
                FROM inventory
                WHERE user_id = ? AND pesticide_name = ?
                """,
                (user_id, pesticide_name)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_inventory(inventory_id: int) -> Optional[Dict[str, Any]]:
        """IDで在庫を取得"""
        with get_db() as conn:
            cursor = conn.execute(
                """
                SELECT id, user_id, pesticide_name, amount, unit,
                       storage_location, expiry_date, last_used_date, usage_count, updated_at
                FROM inventory
                WHERE id = ?
                """,
                (inventory_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    @staticmethod
    def deduct_inventory(user_id: int, pesticide_name: str, quantity: float, unit: str,
                         reference_type: str = None, reference_id: int = None,
                         created_by: int = None) -> Dict[str, Any]:
        """
        在庫を控除し、取引履歴を記録

        Returns:
            {
                "success": bool,
                "warning": bool,  # 在庫不足の警告
                "remaining": float,  # 残量
                "deducted": float,  # 控除量
                "message": str
            }
        """
        with get_db() as conn:
            # 在庫を取得（なければ作成）
            cursor = conn.execute(
                "SELECT id, amount, unit FROM inventory WHERE user_id = ? AND pesticide_name = ?",
                (user_id, pesticide_name)
            )
            inv = cursor.fetchone()

            warning = False
            remaining = 0.0
            inventory_id = None

            if inv:
                inventory_id = inv["id"]
                current_amount = inv["amount"] or 0.0

                # 単位が異なる場合は警告（変換は行わない）
                if inv["unit"] and unit and inv["unit"] != unit:
                    warning = True

                remaining = current_amount - quantity

                # 在庫不足チェック
                if remaining < 0:
                    warning = True

                # 在庫を更新
                conn.execute(
                    """
                    UPDATE inventory
                    SET amount = ?, last_used_date = DATE('now'), usage_count = usage_count + 1, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (remaining, inventory_id)
                )
            else:
                # 在庫レコードがない場合は新規作成（マイナス在庫）
                cursor = conn.execute(
                    """
                    INSERT INTO inventory (user_id, pesticide_name, amount, unit, last_used_date, usage_count)
                    VALUES (?, ?, ?, ?, DATE('now'), 1)
                    """,
                    (user_id, pesticide_name, -quantity, unit)
                )
                inventory_id = cursor.lastrowid
                remaining = -quantity
                warning = True  # 在庫がなかった

            # 取引履歴を記録
            if inventory_id:
                conn.execute(
                    """
                    INSERT INTO inventory_transactions
                    (inventory_id, transaction_type, quantity, unit, reference_type, reference_id, created_by)
                    VALUES (?, 'out', ?, ?, ?, ?, ?)
                    """,
                    (inventory_id, quantity, unit, reference_type, reference_id, created_by)
                )

            conn.commit()

            message = ""
            if warning:
                if remaining < 0:
                    message = f"在庫不足: {pesticide_name} (残量: {remaining:.1f}{unit or ''})"
                elif not inv:
                    message = f"在庫未登録: {pesticide_name}"

            return {
                "success": True,
                "warning": warning,
                "remaining": remaining,
                "deducted": quantity,
                "message": message,
                "inventory_id": inventory_id
            }

    @staticmethod
    def get_transactions(inventory_id: int = None, user_id: int = None, limit: int = 100) -> List[Dict[str, Any]]:
        """取引履歴を取得"""
        with get_db() as conn:
            if inventory_id:
                cursor = conn.execute(
                    """
                    SELECT t.*, i.pesticide_name
                    FROM inventory_transactions t
                    JOIN inventory i ON t.inventory_id = i.id
                    WHERE t.inventory_id = ?
                    ORDER BY t.created_at DESC
                    LIMIT ?
                    """,
                    (inventory_id, limit)
                )
            elif user_id:
                cursor = conn.execute(
                    """
                    SELECT t.*, i.pesticide_name
                    FROM inventory_transactions t
                    JOIN inventory i ON t.inventory_id = i.id
                    WHERE i.user_id = ?
                    ORDER BY t.created_at DESC
                    LIMIT ?
                    """,
                    (user_id, limit)
                )
            else:
                return []
            return [dict(row) for row in cursor.fetchall()]


# =============================================================================
# 水田ポリゴン（Paddy Polygons）リポジトリ
# =============================================================================

def ensure_paddy_polygons_table():
    """paddy_polygons テーブルが存在しない場合は作成する"""
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS paddy_polygons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                field_id INTEGER NOT NULL,
                geometry TEXT NOT NULL,
                area_ha REAL NOT NULL,
                is_converted INTEGER DEFAULT 0,
                conversion_start_year INTEGER,
                source TEXT DEFAULT 'manual',
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (field_id) REFERENCES fields(id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_paddy_polygons_field_id
            ON paddy_polygons(field_id)
        """)
        conn.commit()


class PaddyPolygonRepository:
    """水田ポリゴンデータのCRUD操作"""

    @staticmethod
    def create(
        field_id: int,
        geometry: str,
        area_ha: float,
        is_converted: bool = False,
        conversion_start_year: Optional[int] = None,
        source: str = 'manual',
        notes: Optional[str] = None
    ) -> int:
        """
        水田ポリゴンを作成

        Args:
            field_id: ほ場ID
            geometry: ジオメトリ（GeoJSON等）
            area_ha: 面積（ha）
            is_converted: 転作フラグ
            conversion_start_year: 転作開始年度
            source: データソース（'manual', 'maff', 'kml'）
            notes: 備考

        Returns:
            作成されたポリゴンのID
        """
        try:
            with get_db() as conn:
                cursor = conn.execute("""
                    INSERT INTO paddy_polygons (
                        field_id, geometry, area_ha, is_converted,
                        conversion_start_year, source, notes
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    field_id,
                    geometry,
                    area_ha,
                    1 if is_converted else 0,
                    conversion_start_year,
                    source,
                    notes
                ))
                polygon_id = cursor.lastrowid
                logger.info(f"水田ポリゴン作成成功: id={polygon_id}, field_id={field_id}")
                return polygon_id
        except sqlite3.IntegrityError as e:
            error_msg = str(e).lower()
            logger.error(f"水田ポリゴン作成失敗: {e}")
            if "unique" in error_msg:
                raise DuplicateKeyError(f"重複データです: {e}")
            elif "not null" in error_msg:
                raise NotNullViolationError(f"必須項目が未入力です: {e}")
            elif "foreign key" in error_msg:
                raise ForeignKeyViolationError(f"参照先が存在しません: {e}")
            else:
                raise DatabaseError(f"データベースエラー: {e}")
        except sqlite3.Error as e:
            logger.error(f"水田ポリゴン作成失敗: {e}")
            raise DatabaseError(f"データベースエラーが発生しました: {e}")

    @staticmethod
    def get_by_id(polygon_id: int) -> Optional[Dict[str, Any]]:
        """
        IDで水田ポリゴンを取得

        Args:
            polygon_id: ポリゴンID

        Returns:
            ポリゴンデータ（存在しない場合はNone）
        """
        with get_db() as conn:
            cursor = conn.execute(
                "SELECT * FROM paddy_polygons WHERE id = ?",
                (polygon_id,)
            )
            row = cursor.fetchone()
            return row_to_dict(row)

    @staticmethod
    def get_by_field(field_id: int) -> List[Dict[str, Any]]:
        """
        ほ場IDで水田ポリゴン一覧を取得

        Args:
            field_id: ほ場ID

        Returns:
            ポリゴンデータのリスト
        """
        with get_db() as conn:
            cursor = conn.execute(
                "SELECT * FROM paddy_polygons WHERE field_id = ? ORDER BY id",
                (field_id,)
            )
            rows = cursor.fetchall()
            return rows_to_list(rows)

    @staticmethod
    def get_all_for_user(user_id: int) -> List[Dict[str, Any]]:
        """
        ユーザーの全水田ポリゴンを取得

        Args:
            user_id: ユーザーID

        Returns:
            ポリゴンデータのリスト
        """
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT pp.*
                FROM paddy_polygons pp
                JOIN fields f ON pp.field_id = f.id
                WHERE f.user_id = ?
                ORDER BY pp.id
            """, (user_id,))
            rows = cursor.fetchall()
            return rows_to_list(rows)

    @staticmethod
    def update(polygon_id: int, **kwargs) -> bool:
        """
        水田ポリゴンを更新

        Args:
            polygon_id: ポリゴンID
            **kwargs: 更新データ（geometry, area_ha, is_converted, conversion_start_year, source, notes）

        Returns:
            更新成功ならTrue
        """
        try:
            with get_db() as conn:
                # 更新対象カラムを動的に構築
                updates = []
                values = []
                for key in ['geometry', 'area_ha', 'is_converted', 'conversion_start_year', 'source', 'notes']:
                    if key in kwargs:
                        updates.append(f"{key} = ?")
                        # is_convertedはbool→intに変換
                        if key == 'is_converted':
                            values.append(1 if kwargs[key] else 0)
                        else:
                            values.append(kwargs[key])

                if not updates:
                    return False

                updates.append("updated_at = datetime('now', 'localtime')")
                values.append(polygon_id)

                sql = f"UPDATE paddy_polygons SET {', '.join(updates)} WHERE id = ?"
                cursor = conn.execute(sql, values)
                success = cursor.rowcount > 0

                if success:
                    logger.info(f"水田ポリゴン更新成功: id={polygon_id}")
                return success
        except sqlite3.IntegrityError as e:
            error_msg = str(e).lower()
            logger.error(f"水田ポリゴン更新失敗: {e}")
            if "unique" in error_msg:
                raise DuplicateKeyError(f"重複データです: {e}")
            elif "not null" in error_msg:
                raise NotNullViolationError(f"必須項目が未入力です: {e}")
            elif "foreign key" in error_msg:
                raise ForeignKeyViolationError(f"参照先が存在しません: {e}")
            else:
                raise DatabaseError(f"データベースエラー: {e}")
        except sqlite3.Error as e:
            logger.error(f"水田ポリゴン更新失敗: {e}")
            raise DatabaseError(f"データベースエラーが発生しました: {e}")

    @staticmethod
    def delete(polygon_id: int) -> bool:
        """
        水田ポリゴンを削除

        Args:
            polygon_id: ポリゴンID

        Returns:
            削除成功ならTrue
        """
        try:
            with get_db() as conn:
                cursor = conn.execute(
                    "DELETE FROM paddy_polygons WHERE id = ?",
                    (polygon_id,)
                )
                success = cursor.rowcount > 0
                if success:
                    logger.info(f"水田ポリゴン削除成功: id={polygon_id}")
                return success
        except sqlite3.Error as e:
            logger.error(f"水田ポリゴン削除失敗: {e}")
            raise DatabaseError(f"データベースエラーが発生しました: {e}")

    @staticmethod
    def get_stats(user_id: int) -> Dict[str, Any]:
        """ユーザーの水田ポリゴン統計を取得"""
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT
                    COUNT(*) AS total_count,
                    COALESCE(SUM(pp.area_ha), 0) AS total_area_ha,
                    COALESCE(SUM(CASE WHEN pp.is_converted = 0 THEN pp.area_ha ELSE 0 END), 0) AS paddy_area_ha,
                    COALESCE(SUM(CASE WHEN pp.is_converted = 1 THEN pp.area_ha ELSE 0 END), 0) AS converted_area_ha,
                    SUM(CASE WHEN pp.is_converted = 0 THEN 1 ELSE 0 END) AS paddy_count,
                    SUM(CASE WHEN pp.is_converted = 1 THEN 1 ELSE 0 END) AS converted_count
                FROM paddy_polygons pp
                JOIN fields f ON pp.field_id = f.id
                WHERE f.user_id = ?
            """, (user_id,))
            row = cursor.fetchone()
            return row_to_dict(row) if row else {
                'total_count': 0, 'total_area_ha': 0,
                'paddy_area_ha': 0, 'converted_area_ha': 0,
                'paddy_count': 0, 'converted_count': 0
            }

    @staticmethod
    def get_converted(user_id: int) -> List[Dict[str, Any]]:
        """
        ユーザーの転作済み水田ポリゴンを取得

        Args:
            user_id: ユーザーID

        Returns:
            転作済みポリゴンデータのリスト
        """
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT pp.*
                FROM paddy_polygons pp
                JOIN fields f ON pp.field_id = f.id
                WHERE f.user_id = ? AND pp.is_converted = 1
                ORDER BY pp.id
            """, (user_id,))
            rows = cursor.fetchall()
            return rows_to_list(rows)

    @staticmethod
    def get_paddy(user_id: int) -> List[Dict[str, Any]]:
        """
        ユーザーの水田（転作していない）ポリゴンを取得

        Args:
            user_id: ユーザーID

        Returns:
            水田ポリゴンデータのリスト
        """
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT pp.*
                FROM paddy_polygons pp
                JOIN fields f ON pp.field_id = f.id
                WHERE f.user_id = ? AND pp.is_converted = 0
                ORDER BY pp.id
            """, (user_id,))
            rows = cursor.fetchall()
            return rows_to_list(rows)


# =============================================================================
# 作物ポリゴン（Crop Polygons）リポジトリ
# =============================================================================

def ensure_crop_polygons_table():
    """crop_polygons テーブルが存在しない場合は作成する"""
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS crop_polygons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                field_id INTEGER NOT NULL,
                year INTEGER NOT NULL,
                crop_name TEXT NOT NULL,
                geometry TEXT NOT NULL,
                area_ha REAL NOT NULL,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (field_id) REFERENCES fields(id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_crop_polygons_field_year
            ON crop_polygons(field_id, year)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_crop_polygons_year
            ON crop_polygons(year)
        """)
        conn.commit()


class CropPolygonRepository:
    """作物ポリゴンデータのCRUD操作"""

    @staticmethod
    def create(
        field_id: int,
        year: int,
        crop_name: str,
        geometry: str,
        area_ha: float,
        notes: Optional[str] = None
    ) -> int:
        """
        作物ポリゴンを作成

        Args:
            field_id: ほ場ID
            year: 年度
            crop_name: 作物名
            geometry: ジオメトリ（GeoJSON等）
            area_ha: 面積（ha）
            notes: 備考

        Returns:
            作成されたポリゴンのID
        """
        try:
            with get_db() as conn:
                cursor = conn.execute("""
                    INSERT INTO crop_polygons (
                        field_id, year, crop_name, geometry, area_ha, notes
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    field_id,
                    year,
                    crop_name,
                    geometry,
                    area_ha,
                    notes
                ))
                polygon_id = cursor.lastrowid
                logger.info(f"作物ポリゴン作成成功: id={polygon_id}, field_id={field_id}, year={year}, crop={crop_name}")
                return polygon_id
        except sqlite3.IntegrityError as e:
            error_msg = str(e).lower()
            logger.error(f"作物ポリゴン作成失敗: {e}")
            if "unique" in error_msg:
                raise DuplicateKeyError(f"重複データです: {e}")
            elif "not null" in error_msg:
                raise NotNullViolationError(f"必須項目が未入力です: {e}")
            elif "foreign key" in error_msg:
                raise ForeignKeyViolationError(f"参照先が存在しません: {e}")
            else:
                raise DatabaseError(f"データベースエラー: {e}")
        except sqlite3.Error as e:
            logger.error(f"作物ポリゴン作成失敗: {e}")
            raise DatabaseError(f"データベースエラーが発生しました: {e}")

    @staticmethod
    def get_by_id(polygon_id: int) -> Optional[Dict[str, Any]]:
        """
        IDで作物ポリゴンを取得

        Args:
            polygon_id: ポリゴンID

        Returns:
            ポリゴンデータ（存在しない場合はNone）
        """
        with get_db() as conn:
            cursor = conn.execute(
                "SELECT * FROM crop_polygons WHERE id = ?",
                (polygon_id,)
            )
            row = cursor.fetchone()
            return row_to_dict(row)

    @staticmethod
    def get_by_field_year(field_id: int, year: int) -> List[Dict[str, Any]]:
        """
        ほ場IDと年度で作物ポリゴン一覧を取得

        Args:
            field_id: ほ場ID
            year: 年度

        Returns:
            ポリゴンデータのリスト
        """
        with get_db() as conn:
            cursor = conn.execute(
                "SELECT * FROM crop_polygons WHERE field_id = ? AND year = ? ORDER BY id",
                (field_id, year)
            )
            rows = cursor.fetchall()
            return rows_to_list(rows)

    @staticmethod
    def get_all_for_user_year(user_id: int, year: int) -> List[Dict[str, Any]]:
        """
        ユーザーの特定年度の全作物ポリゴンを取得

        Args:
            user_id: ユーザーID
            year: 年度

        Returns:
            ポリゴンデータのリスト
        """
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT cp.*
                FROM crop_polygons cp
                JOIN fields f ON cp.field_id = f.id
                WHERE f.user_id = ? AND cp.year = ?
                ORDER BY cp.id
            """, (user_id, year))
            rows = cursor.fetchall()
            return rows_to_list(rows)

    @staticmethod
    def update(polygon_id: int, **kwargs) -> bool:
        """
        作物ポリゴンを更新

        Args:
            polygon_id: ポリゴンID
            **kwargs: 更新データ（year, crop_name, geometry, area_ha, notes）

        Returns:
            更新成功ならTrue
        """
        try:
            with get_db() as conn:
                # 更新対象カラムを動的に構築
                updates = []
                values = []
                for key in ['year', 'crop_name', 'geometry', 'area_ha', 'notes']:
                    if key in kwargs:
                        updates.append(f"{key} = ?")
                        values.append(kwargs[key])

                if not updates:
                    return False

                updates.append("updated_at = datetime('now', 'localtime')")
                values.append(polygon_id)

                sql = f"UPDATE crop_polygons SET {', '.join(updates)} WHERE id = ?"
                cursor = conn.execute(sql, values)
                success = cursor.rowcount > 0

                if success:
                    logger.info(f"作物ポリゴン更新成功: id={polygon_id}")
                return success
        except sqlite3.IntegrityError as e:
            error_msg = str(e).lower()
            logger.error(f"作物ポリゴン更新失敗: {e}")
            if "unique" in error_msg:
                raise DuplicateKeyError(f"重複データです: {e}")
            elif "not null" in error_msg:
                raise NotNullViolationError(f"必須項目が未入力です: {e}")
            elif "foreign key" in error_msg:
                raise ForeignKeyViolationError(f"参照先が存在しません: {e}")
            else:
                raise DatabaseError(f"データベースエラー: {e}")
        except sqlite3.Error as e:
            logger.error(f"作物ポリゴン更新失敗: {e}")
            raise DatabaseError(f"データベースエラーが発生しました: {e}")

    @staticmethod
    def delete(polygon_id: int) -> bool:
        """
        作物ポリゴンを削除

        Args:
            polygon_id: ポリゴンID

        Returns:
            削除成功ならTrue
        """
        try:
            with get_db() as conn:
                cursor = conn.execute(
                    "DELETE FROM crop_polygons WHERE id = ?",
                    (polygon_id,)
                )
                success = cursor.rowcount > 0
                if success:
                    logger.info(f"作物ポリゴン削除成功: id={polygon_id}")
                return success
        except sqlite3.Error as e:
            logger.error(f"作物ポリゴン削除失敗: {e}")
            raise DatabaseError(f"データベースエラーが発生しました: {e}")

    @staticmethod
    def copy_from_previous_year(user_id: int, from_year: int, to_year: int) -> int:
        """
        前年度の作物ポリゴンを次年度にコピー

        Args:
            user_id: ユーザーID
            from_year: コピー元年度
            to_year: コピー先年度

        Returns:
            コピーした件数
        """
        try:
            with get_db() as conn:
                cursor = conn.execute("""
                    INSERT INTO crop_polygons (
                        field_id, year, crop_name, geometry, area_ha, notes
                    )
                    SELECT
                        cp.field_id, ?, cp.crop_name, cp.geometry, cp.area_ha, cp.notes
                    FROM crop_polygons cp
                    JOIN fields f ON cp.field_id = f.id
                    WHERE f.user_id = ? AND cp.year = ?
                """, (to_year, user_id, from_year))
                count = cursor.rowcount
                logger.info(f"作物ポリゴンコピー成功: {from_year}→{to_year}, {count}件")
                return count
        except sqlite3.IntegrityError as e:
            error_msg = str(e).lower()
            logger.error(f"作物ポリゴンコピー失敗: {e}")
            if "unique" in error_msg:
                raise DuplicateKeyError(f"重複データです: {e}")
            elif "not null" in error_msg:
                raise NotNullViolationError(f"必須項目が未入力です: {e}")
            elif "foreign key" in error_msg:
                raise ForeignKeyViolationError(f"参照先が存在しません: {e}")
            else:
                raise DatabaseError(f"データベースエラー: {e}")
        except sqlite3.Error as e:
            logger.error(f"作物ポリゴンコピー失敗: {e}")
            raise DatabaseError(f"データベースエラーが発生しました: {e}")


# =============================================================================
# 動作確認用
# =============================================================================

if __name__ == "__main__":
    print("=== DB接続テスト ===")
    with get_db() as conn:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        print(f"テーブル数: {len(tables)}")
        for t in tables:
            print(f"  - {t['name']}")

    print("\n=== リポジトリテスト ===")
    # 組織確認
    with get_db() as conn:
        cursor = conn.execute("SELECT * FROM organizations")
        orgs = cursor.fetchall()
        print(f"組織数: {len(orgs)}")
        for o in orgs:
            print(f"  - {o['name']} ({o['type']})")
