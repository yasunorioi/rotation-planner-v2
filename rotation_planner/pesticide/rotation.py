"""
輪作計画データアクセスモジュール（農薬発注UI用）

DBから輪作計画を読み込み、農薬計算に必要なDataFrame形式で提供。
DB優先、CSVフォールバック方式。

Usage:
    from rotation_planner.pesticide.rotation import (
        RotationPlanRepository,
        get_user_plans_for_dropdown,
        load_rotation_plan_from_db,
    )

    # ドロップダウン用の計画一覧を取得
    plans = get_user_plans_for_dropdown(user_id)

    # 特定の計画をDataFrame形式で取得
    df, year_cols, error = load_rotation_plan_from_db(plan_id)
"""

import pandas as pd
from typing import List, Dict, Tuple, Optional, Any

# DBアクセス
try:
    from rotation_planner.common import PlanRepository, FieldRepository
except ImportError:
    PlanRepository = None
    FieldRepository = None


# =============================================================================
# RotationPlanRepository クラス
# =============================================================================

class RotationPlanRepository:
    """
    輪作計画のDBアクセス層（農薬発注UI用）

    PlanRepositoryをラップし、農薬計算に必要な形式でデータを提供。
    """

    @staticmethod
    def get_plans(user_id: int) -> List[Dict[str, Any]]:
        """
        ユーザーの輪作計画一覧を取得

        Args:
            user_id: ユーザーID

        Returns:
            計画リスト [{id, name, start_year, end_year, ...}, ...]
        """
        if PlanRepository is None:
            return []

        try:
            return PlanRepository.get_plans(user_id)
        except Exception:
            return []

    @staticmethod
    def get_plan(plan_id: int) -> Optional[Dict[str, Any]]:
        """
        特定の輪作計画を取得（詳細含む）

        Args:
            plan_id: 計画ID

        Returns:
            計画データ（詳細含む）
        """
        if PlanRepository is None:
            return None

        try:
            return PlanRepository.get_plan(plan_id)
        except Exception:
            return None

    @staticmethod
    def get_plan_as_dataframe(plan_id: int) -> Tuple[Optional[pd.DataFrame], List[str], Optional[str]]:
        """
        輪作計画をDataFrame形式で取得（農薬計算用）

        Args:
            plan_id: 計画ID

        Returns:
            (DataFrame, year_cols, error_message)

            DataFrameの形式:
                field_code | 面積(ha) | R5 | R6 | R7 | ...
                A-1        | 2.5     | 大豆 | 小麦 | てんさい | ...

            year_cols: ['R5', 'R6', 'R7', ...]
        """
        if PlanRepository is None:
            return None, [], "エラー: DBアクセスモジュールが利用できません"

        try:
            plan = PlanRepository.get_plan(plan_id)
            if not plan:
                return None, [], f"エラー: 計画ID {plan_id} が見つかりません"

            details = plan.get('details', [])
            if not details:
                return None, [], "エラー: 計画に詳細データがありません"

            # ほ場情報を取得してマッピング
            field_info = {}  # field_id -> {field_code, area_ha, ...}
            for detail in details:
                fid = detail['field_id']
                if fid not in field_info:
                    field_info[fid] = {
                        'field_code': detail.get('field_code', f'F{fid}'),
                        'district': detail.get('district', ''),
                        'field_name': detail.get('field_name', ''),
                        'area_ha': 0.0,  # 後で取得
                    }

            # ほ場の面積を取得
            if FieldRepository is not None:
                for fid in field_info.keys():
                    try:
                        field = FieldRepository.get_field(fid)
                        if field:
                            field_info[fid]['area_ha'] = field.get('area_ha', 0.0)
                    except Exception:
                        pass

            # 年列を収集
            years = sorted(set(d['year'] for d in details))
            year_cols = [f"R{y}" if isinstance(y, int) else str(y) for y in years]

            # DataFrameを構築
            rows = []
            for fid, finfo in field_info.items():
                row = {
                    'field_code': finfo['field_code'],
                    'district': finfo['district'],
                    'name': finfo['field_name'],
                    '面積(ha)': finfo['area_ha'],
                }

                # 各年の作物を設定
                for detail in details:
                    if detail['field_id'] == fid:
                        year_str = f"R{detail['year']}" if isinstance(detail['year'], int) else str(detail['year'])
                        row[year_str] = detail['crop']

                rows.append(row)

            df = pd.DataFrame(rows)

            # 列の順序を整理
            base_cols = ['field_code', 'district', 'name', '面積(ha)']
            ordered_cols = base_cols + year_cols
            existing_cols = [c for c in ordered_cols if c in df.columns]
            df = df[existing_cols]

            return df, year_cols, None

        except Exception as e:
            return None, [], f"エラー: {str(e)}"

    @staticmethod
    def save_plan(user_id: int, plan_data: Dict[str, Any]) -> int:
        """
        輪作計画を保存

        Args:
            user_id: ユーザーID
            plan_data: 計画データ
                - name: 計画名
                - start_year: 開始年
                - end_year: 終了年
                - details: [{field_id, year, crop}, ...]

        Returns:
            作成された計画ID
        """
        if PlanRepository is None:
            raise RuntimeError("DBアクセスモジュールが利用できません")

        return PlanRepository.create_plan(user_id, plan_data)


# =============================================================================
# 便利関数
# =============================================================================

def get_user_plans_for_dropdown(user_id: int) -> List[Tuple[str, int]]:
    """
    ドロップダウン用の計画リストを取得

    Args:
        user_id: ユーザーID

    Returns:
        [(表示名, plan_id), ...] 形式のリスト
        Gradio Dropdownのchoicesに直接使用可能
    """
    plans = RotationPlanRepository.get_plans(user_id)
    return [(f"{p['name']} ({p['start_year']}-{p['end_year']})", p['id']) for p in plans]


def load_rotation_plan_from_db(plan_id: int) -> Tuple[Optional[pd.DataFrame], List[str], Optional[str]]:
    """
    DBから輪作計画を読み込み（calculator.py の load_rotation_plan と同じインターフェース）

    Args:
        plan_id: 計画ID

    Returns:
        (DataFrame, year_cols, error_message)
    """
    return RotationPlanRepository.get_plan_as_dataframe(plan_id)


def has_saved_plans(user_id: int) -> bool:
    """
    ユーザーが保存済みの輪作計画を持っているか確認

    Args:
        user_id: ユーザーID

    Returns:
        1件以上あればTrue
    """
    plans = RotationPlanRepository.get_plans(user_id)
    return len(plans) > 0
