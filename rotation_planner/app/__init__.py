"""
輪作計画メーカー パッケージ
app.py からの後方互換性インポートをサポート
"""

# 定数
from .constraints import (
    DEFAULT_CROPS,
    DEFAULT_CONSTRAINTS,
    FIXED_FORBIDDEN_TRANSITIONS,
    DEFAULT_PREFERRED_TRANSITIONS,
    DEFAULT_MAIN_CROPS,
    get_default_crops,
    Constraints,
    build_constraints_table,
    load_constraints_csv,
    parse_constraints_table,
    parse_forbidden_transitions,
    parse_preferred_transitions,
    update_constraints_table,
)

# ユーティリティ
from .utils import (
    UNKNOWN_MARKER,
    COLUMN_ALIASES,
    Field,
    parse_year_columns,
    generate_future_years,
    normalize_columns,
    infer_crop_for_year,
    infer_unknown_crops,
    load_csv,
    generate_result_tables,
    generate_csv_content,
)

# 最適化
from .optimizer import (
    RotationPlannerHeuristic,
    RotationPlannerORTools,
    run_sensitivity_analysis,
    run_optimization,
)

# UI（Gradio UI は削除済み。React版へ移行）

__all__ = [
    # 定数
    'DEFAULT_CROPS',
    'DEFAULT_CONSTRAINTS',
    'FIXED_FORBIDDEN_TRANSITIONS',
    'DEFAULT_PREFERRED_TRANSITIONS',
    'DEFAULT_MAIN_CROPS',
    'get_default_crops',
    'UNKNOWN_MARKER',
    'COLUMN_ALIASES',
    # データクラス
    'Field',
    'Constraints',
    # 制約関数
    'build_constraints_table',
    'load_constraints_csv',
    'parse_constraints_table',
    'parse_forbidden_transitions',
    'parse_preferred_transitions',
    'update_constraints_table',
    # ユーティリティ
    'parse_year_columns',
    'generate_future_years',
    'normalize_columns',
    'infer_crop_for_year',
    'infer_unknown_crops',
    'load_csv',
    'generate_result_tables',
    'generate_csv_content',
    # 最適化
    'RotationPlannerHeuristic',
    'RotationPlannerORTools',
    'run_sensitivity_analysis',
    'run_optimization',
]
