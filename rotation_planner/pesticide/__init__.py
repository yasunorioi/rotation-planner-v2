"""
rotation_planner.pesticide - 農薬発注モジュール

輪作計画に基づく農薬必要量の算出機能。
防除マスタに基づき、作物・時期別の農薬発注リストを生成。

主要機能:
    - 輪作計画CSVからの農薬必要量算出
    - 防除マスタ管理（DB/CSV対応）
    - 在庫考慮での発注量計算
    - JA向け集計機能

Usage:
    from rotation_planner.pesticide import (
        calculate_pesticide_requirements,
        load_pesticide_master_from_db,
        create_pesticide_order_ui,
    )

    # 農薬必要量を計算
    summary_df, detail_df, message = calculate_pesticide_requirements(
        rotation_df, year_cols, target_year, master_df, area_unit
    )

    # UIコンポーネントを作成
    components = create_pesticide_order_ui(user_state)
"""

from .calculator import (
    calculate_pesticide_requirements,
    load_rotation_plan,
    load_inventory_csv,
    normalize_crop,
    convert_to_base_unit,
    convert_from_base_unit,
    UNIT_CONVERSION,
    SPRAY_VOLUME_PER_10A,
    CROP_NORMALIZE,
)

from .master import (
    load_pesticide_master_from_db,
    load_pesticide_master_csv,
    get_default_master_path,
    get_crops_from_master,
    get_pesticides_for_crop,
)

# UIモジュール（Gradio UI は削除済み。React版へ移行）

from .rotation import (
    RotationPlanRepository,
    get_user_plans_for_dropdown,
    load_rotation_plan_from_db,
    has_saved_plans,
)

from .pdf_export import (
    generate_pesticide_order_pdf,
    check_pdf_support,
)

from .csv_io import (
    export_order_csv,
    import_order_csv,
    merge_with_calculated,
)

# 年度ユーティリティ（common経由でも利用可能だが利便性のため）
try:
    from rotation_planner.common.year_utils import (
        get_default_target_year,
        generate_year_choices,
        get_current_fiscal_year,
    )
except ImportError:
    get_default_target_year = None
    generate_year_choices = None
    get_current_fiscal_year = None

__all__ = [
    # calculator
    "calculate_pesticide_requirements",
    "load_rotation_plan",
    "load_inventory_csv",
    "normalize_crop",
    "convert_to_base_unit",
    "convert_from_base_unit",
    "UNIT_CONVERSION",
    "SPRAY_VOLUME_PER_10A",
    "CROP_NORMALIZE",
    # master
    "load_pesticide_master_from_db",
    "load_pesticide_master_csv",
    "get_default_master_path",
    "get_crops_from_master",
    "get_pesticides_for_crop",
    # ui（削除済み）
    # rotation
    "RotationPlanRepository",
    "get_user_plans_for_dropdown",
    "load_rotation_plan_from_db",
    "has_saved_plans",
    # pdf_export
    "generate_pesticide_order_pdf",
    "check_pdf_support",
    # csv_io
    "export_order_csv",
    "import_order_csv",
    "merge_with_calculated",
    # year_utils
    "get_default_target_year",
    "generate_year_choices",
    "get_current_fiscal_year",
]

__version__ = "1.0.0"
