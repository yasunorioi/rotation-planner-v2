"""
rotation_planner.famic - FAMICデータインポートモジュール

農林水産消費安全技術センター（FAMIC）の農薬登録情報をDBにインポート。

Usage:
    from rotation_planner.famic import import_famic_basic, import_famic_usage

    # 登録基本部をインポート
    count = import_famic_basic("data/famic/登録基本部.xls")

    # 登録適用部をインポート
    count = import_famic_usage("data/famic/登録適用部一.xls")

    # FAMICから自動ダウンロード・インポート
    from rotation_planner.famic import download_and_import_all
    result = download_and_import_all()

    # 自動更新設定
    from rotation_planner.famic import get_famic_settings, set_famic_settings
    set_famic_settings(auto_update_enabled=True)
"""

from .importer import (
    import_famic_basic,
    import_famic_usage,
    get_import_stats,
    get_famic_settings,
    set_famic_settings,
    download_famic_file,
    download_and_import_all,
    check_and_update_if_needed,
)

__all__ = [
    "import_famic_basic",
    "import_famic_usage",
    "get_import_stats",
    "get_famic_settings",
    "set_famic_settings",
    "download_famic_file",
    "download_and_import_all",
    "check_and_update_if_needed",
]
