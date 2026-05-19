"""
rotation_planner.common - 共通モジュール

認証、DBアクセス、データ移行など、全モジュールで共有する機能。

サブモジュール:
    - auth: 認証・認可（Gradio auth、ロールベースアクセス制御）
    - db: データベース接続ユーティリティ
    - db_access: DBアクセス層（SQLite、Repository パターン）
    - models: データモデル定義
    - export: CSVエクスポート

Usage:
    from rotation_planner.common import (
        authenticate,
        get_user_info,
        FieldRepository,
        UserRepository,
        get_db,
    )

    # 認証
    if authenticate(username, password):
        user = get_user_info(username)

    # DB操作
    with get_db() as conn:
        fields = FieldRepository.get_fields(user_id=1)
"""

# ロール定数
ROLE_ADMIN = "admin"
ROLE_JA_STAFF = "ja_staff"
ROLE_FARMER = "farmer"
ADMIN_ROLES = {ROLE_ADMIN, ROLE_JA_STAFF}

# 認証モジュール
from rotation_planner.common.auth import (
    authenticate,
    get_user_info,
    get_user_role,
    is_admin_role,
    can_access_user_data,
    can_access_farmer,  # 後方互換
    get_accessible_user_ids,
    get_accessible_farmers,  # 後方互換
    add_user,
    update_password,
    update_user_role,
    delete_user,
    get_admin_count,
    load_users,
    save_users,
    hash_password,
)

# DB接続モジュール
from rotation_planner.common.db import (
    get_db,
    get_connection,
    row_to_dict,
    rows_to_list,
    DB_PATH,
    DB_DIR,
    init_db,
    check_db_exists,
    get_db_info,
)

# DBアクセス層（リポジトリ）
from rotation_planner.common.db_access import (
    FieldRepository,
    CropHistoryRepository,
    PlanRepository,
    UserRepository,
    JAStaffRepository,
    PesticideMasterRepository,
    CropMasterRepository,
    UserCropRepository,
    UserConstraintsRepository,
    PesticideOrderRepository,
    PesticideRegistryRepository,
    PesticideUsageRepository,
    PesticideRecordRepository,
    InventoryRepository,
    OrderTemplateRepository,
    MigrationUtils,
    ensure_crop_tables,
    ensure_inventory_tables,
)

# モデル
from rotation_planner.common.models import (
    User,
    Field,
    RotationPlan,
    PlanDetail,
    CropHistory,
    PesticideMaster,
    PesticideOrder,
    Role,
)

# エクスポート
from rotation_planner.common.export import (
    export_rotation_plan_csv,
    export_all_plans_csv,
    export_pesticide_order_csv,
    export_ja_aggregate_pesticide_csv,
    export_fields_csv,
    can_access_all_data,
    get_accessible_user_ids,
)

# UIユーティリティ
from rotation_planner.common.ui_utils import (
    format_alert,
    format_success,
    format_error,
    format_warning,
    format_info,
)

# 年度ユーティリティ
from rotation_planner.common.year_utils import (
    get_current_fiscal_year,
    get_fiscal_year_for_date,
    reiwa_to_western,
    western_to_reiwa,
    get_default_target_year,
    generate_year_choices,
)

__all__ = [
    # ロール定数
    "ROLE_ADMIN",
    "ROLE_JA_STAFF",
    "ROLE_FARMER",
    "ADMIN_ROLES",
    # 認証
    "authenticate",
    "get_user_info",
    "get_user_role",
    "is_admin_role",
    "can_access_user_data",
    "can_access_farmer",  # 後方互換
    "get_accessible_user_ids",
    "get_accessible_farmers",  # 後方互換
    "add_user",
    "update_password",
    "update_user_role",
    "delete_user",
    "get_admin_count",
    "load_users",
    "save_users",
    "hash_password",
    # DB接続
    "get_db",
    "get_connection",
    "row_to_dict",
    "rows_to_list",
    "DB_PATH",
    "DB_DIR",
    "init_db",
    "check_db_exists",
    "get_db_info",
    # リポジトリ
    "FieldRepository",
    "CropHistoryRepository",
    "PlanRepository",
    "UserRepository",
    "JAStaffRepository",
    "PesticideMasterRepository",
    "CropMasterRepository",
    "UserCropRepository",
    "UserConstraintsRepository",
    "PesticideOrderRepository",
    "PesticideRegistryRepository",
    "PesticideUsageRepository",
    "PesticideRecordRepository",
    "InventoryRepository",
    "MigrationUtils",
    "ensure_crop_tables",
    "ensure_inventory_tables",
    # モデル
    "User",
    "Field",
    "RotationPlan",
    "PlanDetail",
    "CropHistory",
    "PesticideMaster",
    "PesticideOrder",
    "Role",
    # エクスポート
    "export_rotation_plan_csv",
    "export_all_plans_csv",
    "export_pesticide_order_csv",
    "export_ja_aggregate_pesticide_csv",
    "export_fields_csv",
    "can_access_all_data",
    "get_accessible_user_ids",
    # UIユーティリティ
    "format_alert",
    "format_success",
    "format_error",
    "format_warning",
    "format_info",
    # 年度ユーティリティ
    "get_current_fiscal_year",
    "get_fiscal_year_for_date",
    "reiwa_to_western",
    "western_to_reiwa",
    "get_default_target_year",
    "generate_year_choices",
]
