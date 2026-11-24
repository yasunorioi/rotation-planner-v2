"""ドメインライブラリの optimizer を呼び出す薄いサービス層。

ルーターから DB のレコードを optimizer.Field のリストに変換し、
RotationPlannerORTools.solve() を回して結果を整形して返す。
"""
import json
from typing import Optional

from app.db import connect


_UNCONSTRAINED = {
    "min_ha": None, "cap_ha": None,
    "min_gap_years": 0, "min_fields": 0, "max_fields": None,
}


def _fetch_user_crop_names(user_id: int) -> list[str]:
    """ユーザーが「作物を選ぶ」で選択した作物名 (user_crops)。未選択なら空リスト。"""
    with connect() as conn:
        rows = conn.execute(
            "SELECT COALESCE(uc.custom_name, cm.name) AS name "
            "FROM user_crops uc "
            "JOIN crop_master cm ON cm.id = uc.parent_crop_id "
            "WHERE uc.user_id = ? AND cm.is_active = 1 "
            "ORDER BY cm.display_order, name",
            (user_id,),
        ).fetchall()
    return [r["name"] for r in rows if r["name"]]


def default_constraints_dict(user_id: int | None = None) -> dict:
    """既定の作物集合 + 制約。

    user_id を渡し、その人が「作物を選ぶ」で作物を選んでいれば、その作物だけに
    絞った制約 dict を返す (DEFAULT_CONSTRAINTS に無い作物は無制約)。未選択なら
    DEFAULT_CONSTRAINTS をそのまま返す。
    """
    from rotation_planner.app import DEFAULT_CONSTRAINTS
    base = {crop: dict(values) for crop, values in DEFAULT_CONSTRAINTS.items()}
    if user_id is None:
        return base
    names = _fetch_user_crop_names(user_id)
    if not names:
        return base
    return {name: dict(base.get(name, _UNCONSTRAINED)) for name in names}


def load_constraints_dict(plan: dict, user_id: int | None = None) -> dict:
    """plan.constraints_json があればそれを、なければ既定 (user_crops 反映) を返す。"""
    raw = plan.get("constraints_json")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return default_constraints_dict(user_id)


def _to_optional_float(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_int(v, default: int = 0) -> int:
    if v is None or v == "":
        return default
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def constraints_from_dict(d: dict):
    """JSON 由来の dict から optimizer.Constraints を構築する。"""
    from rotation_planner.app import Constraints, FIXED_FORBIDDEN_TRANSITIONS
    return Constraints(
        crop_mins={k: _to_optional_float(v.get("min_ha")) for k, v in d.items()},
        crop_caps={k: _to_optional_float(v.get("cap_ha")) for k, v in d.items()},
        min_gap_years={k: _to_int(v.get("min_gap_years"), 0) for k, v in d.items()},
        min_fields={k: _to_int(v.get("min_fields"), 0) for k, v in d.items()},
        max_fields={k: (_to_int(v["max_fields"]) if v.get("max_fields") not in (None, "") else None)
                    for k, v in d.items()},
        forbidden_transitions=set(FIXED_FORBIDDEN_TRANSITIONS),
    )


def _parse_reiwa(y: str) -> Optional[int]:
    y = y.strip()
    if y.upper().startswith("R"):
        y = y[1:]
    try:
        return int(y)
    except ValueError:
        return None


def _load_pins(conn, plan_id: int) -> dict[tuple[str, str], str]:
    """plan_details のピン (is_pinned=1) を {(field_code, year): crop} で返す。"""
    rows = conn.execute(
        "SELECT f.field_code, pd.year, pd.crop FROM plan_details pd "
        "JOIN fields f ON pd.field_id = f.id "
        "WHERE pd.plan_id = ? AND pd.is_pinned = 1",
        (plan_id,),
    ).fetchall()
    return {(r["field_code"], r["year"]): r["crop"] for r in rows if r["crop"]}


def load_plan_grid(user_id: int, plan: dict) -> dict:
    """永続済みの作業グリッドを solve せずに読む (詳細画面の表示用)。

    過去年=crop_history、将来年=plan_details (ピン + auto)。返り値は
    run_optimization_for_plan と同形 (score/errors は None/空)。
    """
    start_n = _parse_reiwa(plan["start_year"])
    end_n = _parse_reiwa(plan["end_year"])
    if start_n is None or end_n is None or start_n > end_n:
        return {"ok": False, "message": "計画の年度範囲が不正です (R7 など令和形式)"}

    with connect() as conn:
        field_rows = conn.execute(
            "SELECT id, field_code, area_ha, fixed_crop FROM fields WHERE user_id = ? ORDER BY field_code",
            (user_id,),
        ).fetchall()
        history_rows = conn.execute(
            "SELECT h.field_id, h.year, h.crop FROM crop_history h "
            "JOIN fields f ON h.field_id = f.id WHERE f.user_id = ?",
            (user_id,),
        ).fetchall()
        detail_rows = conn.execute(
            "SELECT f.field_code, pd.year, pd.crop, pd.is_pinned FROM plan_details pd "
            "JOIN fields f ON pd.field_id = f.id WHERE pd.plan_id = ?",
            (plan["id"],),
        ).fetchall()

    if not field_rows:
        return {"ok": False, "message": "ほ場が登録されていません"}

    field_codes = [f["field_code"] for f in field_rows]
    area_by_code = {f["field_code"]: float(f["area_ha"]) for f in field_rows}
    field_id_by_code = {f["field_code"]: f["id"] for f in field_rows}
    id_to_code = {f["id"]: f["field_code"] for f in field_rows}
    fixed_by_code = {f["field_code"]: f["fixed_crop"] for f in field_rows if f["fixed_crop"]}

    history_years: set[str] = set()
    grid: dict[tuple[str, str], str] = {}
    for h in history_rows:
        code = id_to_code.get(h["field_id"])
        if code is not None:
            grid[(code, h["year"])] = h["crop"]
            history_years.add(h["year"])

    future_years = [f"R{n}" for n in range(start_n, end_n + 1)]
    past_years = sorted(
        [y for y in history_years if (_parse_reiwa(y) or 0) < start_n],
        key=lambda y: _parse_reiwa(y) or 0,
    )

    pinned_cells: set[tuple[str, str]] = set()
    # fixed_crop は全将来年のピン (特殊ケース)。個別ピン (plan_details) が上書きする
    for code, crop in fixed_by_code.items():
        for y in future_years:
            grid[(code, y)] = crop
            pinned_cells.add((code, y))
    for r in detail_rows:
        if r["year"] not in future_years:
            continue
        grid[(r["field_code"], r["year"])] = r["crop"]
        if r["is_pinned"]:
            pinned_cells.add((r["field_code"], r["year"]))
        else:
            pinned_cells.discard((r["field_code"], r["year"]))

    all_years = past_years + future_years
    crops_in_result: list[str] = []
    seen_crops: set[str] = set()
    summary: dict[str, dict[str, float]] = {y: {} for y in all_years}
    for code in field_codes:
        for y in all_years:
            crop = grid.get((code, y))
            if not crop:
                continue
            if crop not in seen_crops:
                seen_crops.add(crop)
                crops_in_result.append(crop)
            summary[y][crop] = summary[y].get(crop, 0.0) + area_by_code[code]

    is_past = {y: True for y in past_years}
    for y in future_years:
        is_past[y] = False

    has_future = any((code, y) in grid for code in field_codes for y in future_years)
    if not has_future:
        msg = "まだ計画がありません"
    elif pinned_cells:
        msg = f"固定セル {len(pinned_cells)} 個 / 残りは自動"
    else:
        msg = "すべて自動 (固定セル 0 個)"

    return {
        "ok": True,
        "message": msg,
        "field_codes": field_codes,
        "past_years": past_years,
        "future_years": future_years,
        "grid": grid,
        "pinned": pinned_cells,
        "field_id_by_code": field_id_by_code,
        "is_past": is_past,
        "score": None,
        "errors": [],
        "summary": summary,
        "crops_in_result": crops_in_result,
        "has_future": has_future,
    }


def run_optimization_for_plan(user_id: int, plan: dict, timeout_seconds: int = 5,
                              random_seed: int | None = None) -> dict:
    """計画に対して輪作最適化を実行する。

    plan_details のピン (is_pinned=1) と ほ場の fixed_crop (全将来年ピン) を
    ソルバにハード注入し、空きセルだけ最適化する (pin-and-fill)。

    Returns:
        {
          "ok": bool,
          "message": str,
          "field_codes": list[str],
          "past_years": list[str],
          "future_years": list[str],
          "grid": dict[(field_code, year), crop],  # 履歴 + 計画
          "pinned": set[(field_code, year)],        # 人が固定したセル
          "field_id_by_code": dict[field_code, field_id],
          "is_past": dict[year, bool],
          "score": float | None,
          "errors": list[str],
        }
    """
    from rotation_planner.app import (
        RotationPlannerORTools,
        Field as OptField,
    )

    start_n = _parse_reiwa(plan["start_year"])
    end_n = _parse_reiwa(plan["end_year"])
    if start_n is None or end_n is None or start_n > end_n:
        return {"ok": False, "message": "計画の年度範囲が不正です (R7 など令和形式)"}

    with connect() as conn:
        field_rows = conn.execute(
            "SELECT id, field_code, name, district, area_ha, beet_forbidden, fixed_crop "
            "FROM fields WHERE user_id = ? ORDER BY field_code",
            (user_id,),
        ).fetchall()
        history_rows = conn.execute(
            "SELECT h.field_id, h.year, h.crop FROM crop_history h "
            "JOIN fields f ON h.field_id = f.id WHERE f.user_id = ?",
            (user_id,),
        ).fetchall()
        pins = _load_pins(conn, plan["id"])

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
    area_by_code: dict[str, float] = {}
    field_id_by_code: dict[str, int] = {}
    idx_by_code: dict[str, int] = {}
    fixed_by_code: dict[str, str] = {}
    for idx, f in enumerate(field_rows):
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
        area_by_code[f["field_code"]] = float(f["area_ha"])
        field_id_by_code[f["field_code"]] = f["id"]
        idx_by_code[f["field_code"]] = idx
        if f["fixed_crop"]:
            fixed_by_code[f["field_code"]] = f["fixed_crop"]

    constraints_dict = load_constraints_dict(plan, user_id)
    crops = list(constraints_dict.keys())
    constraints = constraints_from_dict(constraints_dict)

    # 固定割当: ほ場 fixed_crop (全将来年) → plan_details ピン (個別セルが優先)
    pinned_cells: set[tuple[str, str]] = set()
    fixed_assignments: dict[tuple[int, str], str] = {}
    for code, crop in fixed_by_code.items():
        for y in future_years:
            fixed_assignments[(idx_by_code[code], y)] = crop
            pinned_cells.add((code, y))
    for (code, y), crop in pins.items():
        if code in idx_by_code and y in future_years:
            fixed_assignments[(idx_by_code[code], y)] = crop
            pinned_cells.add((code, y))

    # ピンの作物が制約由来の crop リストに無いと、ソルバはそれを決定肢として
    # 持てずピンが黙殺される。固定割当の作物は無制約でも crop 集合に加える。
    for crop in fixed_assignments.values():
        if crop not in crops:
            crops.append(crop)

    planner = RotationPlannerORTools(opt_fields, past_years, future_years, crops, constraints)
    plan_dict, score, errors = planner.solve(
        timeout_seconds=timeout_seconds, district_grouping=False,
        fixed_assignments=fixed_assignments, random_seed=random_seed,
    )

    # grid: 履歴(過去) + 計画結果(将来)
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

    # 年×作物の合計面積サマリ。結果に登場する作物のみ列挙する
    all_years = past_years + future_years
    crops_in_result: list[str] = []
    seen_crops: set[str] = set()
    summary: dict[str, dict[str, float]] = {y: {} for y in all_years}
    for code in field_codes:
        for y in all_years:
            crop = grid.get((code, y))
            if not crop:
                continue
            if crop not in seen_crops:
                seen_crops.add(crop)
                crops_in_result.append(crop)
            summary[y][crop] = summary[y].get(crop, 0.0) + area_by_code[code]

    msg = f"スコア {score:.1f} / 過去{len(past_years)}年 + 将来{len(future_years)}年"
    if pinned_cells:
        msg += f" / 固定セル {len(pinned_cells)} 個"

    return {
        "ok": True,
        "message": msg,
        "field_codes": field_codes,
        "past_years": past_years,
        "future_years": future_years,
        "grid": grid,
        "pinned": pinned_cells,
        "field_id_by_code": field_id_by_code,
        "is_past": is_past,
        "score": score,
        "errors": errors or [],
        "summary": summary,
        "crops_in_result": crops_in_result,
    }


def persist_autofill(user_id: int, plan: dict, random_seed: int | None = None) -> dict:
    """pin-and-fill の「自動で埋める」実行。

    ピン (is_pinned=1) と fixed_crop を注入して solve し、ピンでない将来セルの
    結果を plan_details に is_pinned=0 で upsert する (ピンは温存)。
    結果 dict (run_optimization_for_plan と同形) を返す。
    """
    result = run_optimization_for_plan(user_id, plan, random_seed=random_seed)
    if not result.get("ok"):
        return result

    plan_id = plan["id"]
    field_id_by_code = result["field_id_by_code"]
    pinned = result["pinned"]
    with connect() as conn:
        for code in result["field_codes"]:
            fid = field_id_by_code.get(code)
            if not fid:
                continue
            for y in result["future_years"]:
                if (code, y) in pinned:
                    continue  # ピンはソルバ結果で上書きしない
                crop = result["grid"].get((code, y))
                if not crop:
                    continue
                conn.execute(
                    "INSERT INTO plan_details (plan_id, field_id, year, crop, is_pinned) "
                    "VALUES (?, ?, ?, ?, 0) "
                    "ON CONFLICT(plan_id, field_id, year) "
                    "DO UPDATE SET crop = excluded.crop, is_pinned = 0",
                    (plan_id, fid, y, crop),
                )
    return result


def set_plan_cell(user_id: int, plan_id: int, field_id: int, year: str, crop: str) -> None:
    """計画グリッドのセルを人が固定する (ピン)。crop が空なら該当セルを削除。"""
    with connect() as conn:
        owned = conn.execute(
            "SELECT 1 FROM fields WHERE id = ? AND user_id = ?", (field_id, user_id)
        ).fetchone()
        if owned is None:
            from fastapi import HTTPException
            raise HTTPException(404, "ほ場が見つかりません")
        crop = (crop or "").strip()
        if not crop:
            conn.execute(
                "DELETE FROM plan_details WHERE plan_id = ? AND field_id = ? AND year = ?",
                (plan_id, field_id, year),
            )
            return
        from app.crop_service import normalize_crop_name
        crop = normalize_crop_name(conn, crop)
        conn.execute(
            "INSERT INTO plan_details (plan_id, field_id, year, crop, is_pinned) "
            "VALUES (?, ?, ?, ?, 1) "
            "ON CONFLICT(plan_id, field_id, year) "
            "DO UPDATE SET crop = excluded.crop, is_pinned = 1",
            (plan_id, field_id, year, crop),
        )
