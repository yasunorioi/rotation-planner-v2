"""
CSVエクスポートモジュール - 輪作計画・農薬発注のCSVダウンロード機能

使用方法:
    from rotation_planner.common.export import (
        export_rotation_plan_csv,
        export_pesticide_order_csv,
        create_csv_export_ui
    )

セキュリティ:
    - farmer: 自分のデータのみ
    - ja_staff/admin: 組織内全データ可
    - user_idフィルタ必須
"""

import os
import csv
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

# =============================================================================
# 定数
# =============================================================================

# CSV出力パス
CSV_OUTPUT_DIR = "/tmp"

# ロール定義
ADMIN_ROLES = {"admin", "ja_staff"}


# =============================================================================
# セキュリティヘルパー
# =============================================================================

def can_access_all_data(user_state: Dict[str, Any]) -> bool:
    """全データアクセス権限をチェック（JA職員・管理者）"""
    if not user_state:
        return False
    role = user_state.get("role", "farmer")
    return role in ADMIN_ROLES


def get_accessible_user_ids(user_state: Dict[str, Any]) -> List[int]:
    """
    アクセス可能なユーザーIDのリストを取得

    Returns:
        - farmer: 自分のuser_idのみ [user_id]
        - ja_staff/admin: 組織内全ユーザーID
    """
    if not user_state:
        return []

    user_id = user_state.get("user_id")
    role = user_state.get("role", "farmer")
    org_id = user_state.get("org_id")

    if role in ADMIN_ROLES and org_id:
        # 組織内の全農家IDを取得
        try:
            # 遅延インポートで循環参照を回避
            from rotation_planner.common.db_access import JAStaffRepository
            farmers = JAStaffRepository.get_all_farmers(org_id)
            return [f.get("id") for f in farmers if f.get("id")]
        except Exception:
            pass

    # 農家は自分のみ
    return [user_id] if user_id else []


# =============================================================================
# 輪作計画CSVエクスポート
# =============================================================================

def export_rotation_plan_csv(
    plan_id: int,
    user_state: Dict[str, Any]
) -> Tuple[Optional[str], str]:
    """
    輪作計画をCSV出力

    Args:
        plan_id: 計画ID
        user_state: ユーザー状態

    Returns:
        (CSVファイルパス, メッセージ)

    セキュリティ:
        - 自分の計画または組織内計画のみ出力可能
    """
    if not user_state or not user_state.get("user_id"):
        return None, "エラー: ログインが必要です"

    # 遅延インポート
    from rotation_planner.common.db_access import PlanRepository

    # 計画を取得
    plan = PlanRepository.get_plan(plan_id)
    if not plan:
        return None, f"エラー: 計画ID {plan_id} が見つかりません"

    # アクセス権限チェック
    plan_user_id = plan.get("user_id")
    accessible_ids = get_accessible_user_ids(user_state)

    if plan_user_id not in accessible_ids:
        return None, "エラー: この計画へのアクセス権限がありません"

    # CSV出力
    details = plan.get("details", [])
    if not details:
        return None, "エラー: 計画詳細データがありません"

    # ファイル名生成
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    plan_name = plan.get("name", "plan").replace(" ", "_")
    filename = f"輪作計画_{plan_name}_{timestamp}.csv"
    filepath = os.path.join(CSV_OUTPUT_DIR, filename)

    # CSV書き込み（UTF-8 with BOM）
    with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)

        # ヘッダー
        writer.writerow(["計画名", "ほ場コード", "ほ場名", "地区", "年度", "作物"])

        # データ行
        for detail in details:
            writer.writerow([
                plan.get("name", ""),
                detail.get("field_code", ""),
                detail.get("field_name", ""),
                detail.get("district", ""),
                detail.get("year", ""),
                detail.get("crop", "")
            ])

    return filepath, f"輪作計画CSVを出力しました（{len(details)}件）"


def export_all_plans_csv(user_state: Dict[str, Any]) -> Tuple[Optional[str], str]:
    """
    ユーザーの全輪作計画をCSV出力

    Args:
        user_state: ユーザー状態

    Returns:
        (CSVファイルパス, メッセージ)
    """
    if not user_state or not user_state.get("user_id"):
        return None, "エラー: ログインが必要です"

    # 遅延インポート
    from rotation_planner.common.db_access import PlanRepository

    user_id = user_state.get("user_id")
    role = user_state.get("role", "farmer")

    # 計画一覧を取得
    if role in ADMIN_ROLES:
        # JA職員・管理者: 組織内全計画
        accessible_ids = get_accessible_user_ids(user_state)

        all_details = []
        for uid in accessible_ids:
            plans = PlanRepository.get_plans(uid)
            for plan_meta in plans:
                plan = PlanRepository.get_plan(plan_meta.get("id"))
                if plan and plan.get("details"):
                    for detail in plan["details"]:
                        detail["plan_name"] = plan.get("name", "")
                        detail["owner_id"] = uid
                    all_details.extend(plan["details"])
    else:
        # 農家: 自分の計画のみ
        plans = PlanRepository.get_plans(user_id)
        all_details = []
        for plan_meta in plans:
            plan = PlanRepository.get_plan(plan_meta.get("id"))
            if plan and plan.get("details"):
                for detail in plan["details"]:
                    detail["plan_name"] = plan.get("name", "")
                all_details.extend(plan["details"])

    if not all_details:
        return None, "エラー: 輪作計画データがありません"

    # ファイル名生成
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"rotation_plans_all_{timestamp}.csv"
    filepath = os.path.join(CSV_OUTPUT_DIR, filename)

    # CSV書き込み（UTF-8 with BOM）
    with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)

        # ヘッダー
        writer.writerow(["計画名", "ほ場コード", "ほ場名", "地区", "年度", "作物"])

        # データ行
        for detail in all_details:
            writer.writerow([
                detail.get("plan_name", ""),
                detail.get("field_code", ""),
                detail.get("field_name", ""),
                detail.get("district", ""),
                detail.get("year", ""),
                detail.get("crop", "")
            ])

    return filepath, f"全輪作計画CSVを出力しました（{len(all_details)}件）"


# =============================================================================
# 農薬発注リストCSVエクスポート
# =============================================================================

def export_pesticide_order_csv(
    summary_data: List[Dict[str, Any]],
    detail_data: List[Dict[str, Any]] = None,
    user_state: Dict[str, Any] = None
) -> Tuple[Optional[str], str]:
    """
    農薬発注リストをCSV出力

    Args:
        summary_data: 農薬サマリデータ
        detail_data: 月別詳細データ（オプション）
        user_state: ユーザー状態

    Returns:
        (CSVファイルパス, メッセージ)
    """
    if not summary_data:
        return None, "エラー: 発注データがありません"

    # ファイル名生成
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"農薬発注_{timestamp}.csv"
    filepath = os.path.join(CSV_OUTPUT_DIR, filename)

    # CSV書き込み（UTF-8 with BOM）
    with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)

        # サマリ部分
        writer.writerow(["===== 農薬発注リスト（サマリ） ====="])
        writer.writerow(["農薬名", "必要量", "単位", "対象作物", "対象病害虫"])

        for row in summary_data:
            writer.writerow([
                row.get("農薬名", row.get("pesticide_name", "")),
                row.get("必要量", row.get("total_amount", "")),
                row.get("単位", row.get("unit", "")),
                row.get("対象作物", row.get("crops", "")),
                row.get("対象病害虫", row.get("targets", ""))
            ])

        # 詳細部分（オプション）
        if detail_data:
            writer.writerow([])  # 空行
            writer.writerow(["===== 月別詳細 ====="])
            writer.writerow(["月", "作物", "対象", "農薬名", "必要量", "面積(ha)"])

            for row in detail_data:
                writer.writerow([
                    row.get("月", row.get("month", "")),
                    row.get("作物", row.get("crop", "")),
                    row.get("対象", row.get("target", "")),
                    row.get("農薬名", row.get("pesticide_name", "")),
                    row.get("必要量", row.get("amount", "")),
                    row.get("面積(ha)", row.get("area_ha", ""))
                ])

    return filepath, f"農薬発注リストCSVを出力しました（{len(summary_data)}品目）"


def export_ja_aggregate_pesticide_csv(
    user_state: Dict[str, Any]
) -> Tuple[Optional[str], str]:
    """
    JA集計用：組織内全農家の農薬発注集計をCSV出力

    Args:
        user_state: ユーザー状態（JA職員・管理者のみ）

    Returns:
        (CSVファイルパス, メッセージ)
    """
    if not user_state:
        return None, "エラー: ログインが必要です"

    role = user_state.get("role", "farmer")
    if role not in ADMIN_ROLES:
        return None, "エラー: JA職員または管理者権限が必要です"

    try:
        # 遅延インポート
        from rotation_planner.pesticide import get_aggregate_pesticide_orders
        org_id = user_state.get("org_id", 1)
        aggregate_data = get_aggregate_pesticide_orders(org_id)

        if aggregate_data is None or (hasattr(aggregate_data, 'empty') and aggregate_data.empty):
            return None, "エラー: 集計データがありません"

        # ファイル名生成
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"JA農薬集計_{timestamp}.csv"
        filepath = os.path.join(CSV_OUTPUT_DIR, filename)

        # DataFrameをCSV出力
        aggregate_data.to_csv(filepath, index=False, encoding="utf-8-sig")

        return filepath, f"JA集計CSVを出力しました（{len(aggregate_data)}件）"

    except ImportError:
        return None, "エラー: rotation_planner.pesticideモジュールが見つかりません"
    except Exception as e:
        return None, f"エラー: {str(e)}"


# =============================================================================
# ほ場一覧CSVエクスポート
# =============================================================================

def export_fields_csv(user_state: Dict[str, Any]) -> Tuple[Optional[str], str]:
    """
    ほ場一覧をCSV出力

    Args:
        user_state: ユーザー状態

    Returns:
        (CSVファイルパス, メッセージ)

    セキュリティ:
        - farmer: 自分のほ場のみ
        - ja_staff/admin: 組織内全ほ場
    """
    if not user_state or not user_state.get("user_id"):
        return None, "エラー: ログインが必要です"

    # 遅延インポート
    from rotation_planner.common.db_access import FieldRepository, JAStaffRepository

    user_id = user_state.get("user_id")
    role = user_state.get("role", "farmer")

    # ほ場を取得
    if role in ADMIN_ROLES:
        # 組織内全ほ場
        org_id = user_state.get("org_id", 1)
        try:
            fields = JAStaffRepository.get_all_fields(org_id)
        except Exception:
            fields = FieldRepository.get_fields(user_id)
    else:
        # 自分のほ場のみ
        fields = FieldRepository.get_fields(user_id)

    if not fields:
        return None, "エラー: ほ場データがありません"

    # ファイル名生成
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"ほ場一覧_{timestamp}.csv"
    filepath = os.path.join(CSV_OUTPUT_DIR, filename)

    # CSV書き込み（UTF-8 with BOM）- 輪作計画メーカー形式
    with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)

        # ヘッダー（輪作計画メーカー形式）
        writer.writerow(["ほ場ID", "地区", "ほ場名", "area", "beet_forbidden"])

        # データ行
        for field in fields:
            area_a = field.get("area_a", field.get("area_ha", 0) * 100)
            beet = 1 if field.get("beet_forbidden") else 0
            writer.writerow([
                field.get("field_code", ""),
                field.get("district", ""),
                field.get("name", ""),
                f"{area_a:.2f}",
                beet
            ])

    return filepath, f"ほ場一覧CSVを出力しました（{len(fields)}件）"
