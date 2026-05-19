"""
年度関連のユーティリティ

農業年度: 4月〜翌3月
- 3月まで: 当年度（例: 2026年3月 → R8）
- 4月から: 新年度（例: 2026年4月 → R9）
"""

from datetime import datetime
from typing import Optional


def get_current_fiscal_year() -> str:
    """
    現在の農業年度を取得（令和形式）

    4月〜翌3月を1年度とする
    - 2026年1月〜3月 → R7（令和7年度）
    - 2026年4月〜12月 → R8（令和8年度）

    Returns:
        令和年度 (例: "R8")
    """
    now = datetime.now()
    year = now.year
    month = now.month

    # 1月〜3月は前年度
    if month <= 3:
        year -= 1

    # 西暦 → 令和変換（2019年 = 令和1年）
    reiwa_year = year - 2018

    return f"R{reiwa_year}"


def get_fiscal_year_for_date(dt: datetime) -> str:
    """
    指定日時の農業年度を取得

    Args:
        dt: 日時

    Returns:
        令和年度 (例: "R8")
    """
    year = dt.year
    month = dt.month

    if month <= 3:
        year -= 1

    reiwa_year = year - 2018
    return f"R{reiwa_year}"


def reiwa_to_western(reiwa_year: str) -> int:
    """
    令和年を西暦に変換

    Args:
        reiwa_year: 令和年 (例: "R8" or "8")

    Returns:
        西暦年 (例: 2026)
    """
    if reiwa_year.upper().startswith("R"):
        reiwa_year = reiwa_year[1:]

    return int(reiwa_year) + 2018


def western_to_reiwa(western_year: int) -> str:
    """
    西暦を令和年に変換

    Args:
        western_year: 西暦年 (例: 2026)

    Returns:
        令和年 (例: "R8")
    """
    reiwa_year = western_year - 2018
    return f"R{reiwa_year}"


def get_default_target_year() -> str:
    """
    デフォルトの対象年度を取得

    農薬発注などで使用する「デフォルトで選択される年度」
    - 3月まで: 当年度（今年度の発注）
    - 4月から: 翌年度（来年度の発注準備）

    Returns:
        令和年度 (例: "R9")
    """
    return get_current_fiscal_year()


def generate_year_choices(start_offset: int = -2, end_offset: int = 5) -> list:
    """
    年度選択肢を生成

    Args:
        start_offset: 現在年度からの開始オフセット（負は過去）
        end_offset: 現在年度からの終了オフセット

    Returns:
        令和年度のリスト (例: ["R6", "R7", "R8", "R9", "R10"])
    """
    current = get_current_fiscal_year()
    current_num = int(current[1:])

    return [f"R{current_num + i}" for i in range(start_offset, end_offset + 1)]
