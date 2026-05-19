"""ドメインライブラリの optimizer を呼び出す薄いサービス層。

ルーターから DB のレコードを optimizer.Field のリストに変換し、
RotationPlannerORTools.solve() を回して結果を整形して返す。
"""
from typing import Optional

from app.db import connect


def _parse_reiwa(y: str) -> Optional[int]:
    y = y.strip()
    if y.upper().startswith("R"):
        y = y[1:]
    try:
        return int(y)
    except ValueError:
        return None


def run_optimization_for_plan(user_id: int, plan: dict, timeout_seconds: int = 5) -> dict:
    """計画に対して輪作最適化を実行する。

    Returns:
        {
          "ok": bool,
          "message": str,
          "field_codes": list[str],
          "past_years": list[str],
          "future_years": list[str],
          "grid": dict[(field_code, year), crop],  # 履歴 + 計画
          "is_past": dict[year, bool],
          "score": float | None,
          "errors": list[str],
        }
    """
    from rotation_planner.app import (
        RotationPlannerORTools,
        Constraints,
        DEFAULT_CONSTRAINTS,
        FIXED_FORBIDDEN_TRANSITIONS,
        Field as OptField,
        build_constraints_table,
        parse_constraints_table,
    )

    start_n = _parse_reiwa(plan["start_year"])
    end_n = _parse_reiwa(plan["end_year"])
    if start_n is None or end_n is None or start_n > end_n:
        return {"ok": False, "message": "計画の年度範囲が不正です (R7 など令和形式)"}

    with connect() as conn:
        field_rows = conn.execute(
            "SELECT id, field_code, name, district, area_ha, beet_forbidden "
            "FROM fields WHERE user_id = ? ORDER BY field_code",
            (user_id,),
        ).fetchall()
        history_rows = conn.execute(
            "SELECT h.field_id, h.year, h.crop FROM crop_history h "
            "JOIN fields f ON h.field_id = f.id WHERE f.user_id = ?",
            (user_id,),
        ).fetchall()

    if not field_rows:
        return {"ok": False, "message": "ほ場が登録されていません"}

    history_map: dict[int, dict[str, str]] = {}
    history_years: set[str] = set()
    for h in history_rows:
        history_map.setdefault(h["field_id"], {})[h["year"]] = h["crop"]
        history_years.add(h["year"])

    future_years = [f"R{n}" for n in range(start_n, end_n + 1)]
    past_years = sorted(
        [y for y in history_years if (_parse_reiwa(y) or 0) < start_n],
        key=lambda y: _parse_reiwa(y) or 0,
    )

    opt_fields = []
    field_codes = []
    for f in field_rows:
        history = history_map.get(f["id"], {})
        opt_fields.append(
            OptField(
                field_id=f["field_code"],
                district=f["district"] or "",
                name=f["name"] or f["field_code"],
                area_ha=float(f["area_ha"]),
                history=history,
                beet_forbidden=bool(f["beet_forbidden"]),
            )
        )
        field_codes.append(f["field_code"])

    crops = list(DEFAULT_CONSTRAINTS.keys())
    table = build_constraints_table(crops)
    crop_mins, crop_caps, min_gap, min_f, max_f = parse_constraints_table(table)
    constraints = Constraints(
        crop_mins=crop_mins,
        crop_caps=crop_caps,
        min_gap_years=min_gap,
        min_fields=min_f,
        max_fields=max_f,
        forbidden_transitions=set(FIXED_FORBIDDEN_TRANSITIONS),
    )

    planner = RotationPlannerORTools(opt_fields, past_years, future_years, crops, constraints)
    plan_dict, score, errors = planner.solve(timeout_seconds=timeout_seconds, district_grouping=False)

    # grid: 履歴 + 計画結果
    grid: dict[tuple[str, str], str] = {}
    for idx, f in enumerate(opt_fields):
        for y in past_years:
            if y in f.history:
                grid[(f.field_id, y)] = f.history[y]
        for y in future_years:
            crop = plan_dict.get((idx, y)) if plan_dict else None
            if crop:
                grid[(f.field_id, y)] = crop

    is_past = {y: True for y in past_years}
    for y in future_years:
        is_past[y] = False

    return {
        "ok": True,
        "message": f"スコア {score:.1f} / 過去{len(past_years)}年 + 将来{len(future_years)}年",
        "field_codes": field_codes,
        "past_years": past_years,
        "future_years": future_years,
        "grid": grid,
        "is_past": is_past,
        "score": score,
        "errors": errors or [],
    }
