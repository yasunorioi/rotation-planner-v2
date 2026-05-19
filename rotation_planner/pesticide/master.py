"""
防除マスタ管理モジュール

防除マスタの読み込み・管理機能を提供。
DB正（pesticide_mastersテーブル）。CSVはインポート用。
"""

import pandas as pd
import os
from typing import Optional

# DBアクセス
try:
    from rotation_planner.common import PesticideMasterRepository
except ImportError:
    PesticideMasterRepository = None


# =============================================================================
# マスタ読み込み（DB）
# =============================================================================

def load_pesticide_master(org_id: int = None) -> pd.DataFrame:
    """
    防除マスタをDBから読み込み

    Args:
        org_id: 組織ID（組織別マスタがある場合に使用）

    Returns:
        防除マスタのDataFrame
    """
    if PesticideMasterRepository is not None:
        try:
            rows = PesticideMasterRepository.get_all(org_id)
            if rows:
                return pd.DataFrame(rows)
        except Exception:
            pass

    return pd.DataFrame()


# 後方互換エイリアス
def load_pesticide_master_from_db(org_id: int = None) -> pd.DataFrame:
    """後方互換用。load_pesticide_master() を使用してください。"""
    return load_pesticide_master(org_id)


# =============================================================================
# CSVインポート用
# =============================================================================

def get_default_master_path() -> str:
    """デフォルトの防除マスタCSVパスを取得（インポート用）"""
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base_dir, "pesticide_master.csv")


def load_pesticide_master_csv(master_path: str = None) -> pd.DataFrame:
    """
    防除マスタCSVを読み込み（インポート用）

    Args:
        master_path: CSVファイルパス（Noneの場合はデフォルトパス）

    Returns:
        防除マスタのDataFrame

    CSV形式:
        crop,month,target,pesticide_name,dilution_rate,amount_per_10a,unit
        てんさい,4,苗立枯病,トップジンM水和剤,1000,,mL
        大豆,5,アブラムシ,スミチオン乳剤,1000,,mL
    """
    if master_path is None:
        master_path = get_default_master_path()

    if not os.path.exists(master_path):
        return pd.DataFrame()

    try:
        df = pd.read_csv(master_path, encoding='utf-8')
        return df
    except Exception:
        try:
            df = pd.read_csv(master_path, encoding='utf-8-sig')
            return df
        except Exception:
            return pd.DataFrame()


def get_crops_from_master(master_df: pd.DataFrame) -> list:
    """
    マスタから作物リストを取得

    Args:
        master_df: 防除マスタDataFrame

    Returns:
        作物名のリスト
    """
    if master_df.empty or 'crop' not in master_df.columns:
        return []
    return sorted(master_df['crop'].unique().tolist())


def get_pesticides_for_crop(master_df: pd.DataFrame, crop: str) -> pd.DataFrame:
    """
    指定作物の農薬一覧を取得

    Args:
        master_df: 防除マスタDataFrame
        crop: 作物名

    Returns:
        該当作物の農薬データ
    """
    if master_df.empty or 'crop' not in master_df.columns:
        return pd.DataFrame()
    return master_df[master_df['crop'] == crop]
