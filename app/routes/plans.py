"""輪作計画 CRUD — name / start_year / end_year のメタデータのみ。

constraints_json / metadata_json は optimizer 接続時に拡張する。
"""
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.auth import CurrentUser
from app.db import connect

router = APIRouter(prefix="/plans")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _fetch_plans(user_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, name, start_year, end_year, constraints_json, metadata_json, created_at, updated_at "
            "FROM rotation_plans WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def _fetch_plan(user_id: int, plan_id: int) -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT id, name, start_year, end_year, constraints_json, metadata_json, created_at, updated_at "
            "FROM rotation_plans WHERE id = ? AND user_id = ?",
            (plan_id, user_id),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "計画が見つかりません")
    return dict(row)


@router.get("/")
def list_plans(request: Request, user: CurrentUser):
    plans = _fetch_plans(user["id"])
    return templates.TemplateResponse(
        request, "plans/list.html", {"user": user, "plans": plans}
    )


@router.get("/new", response_class=HTMLResponse)
def new_plan_form(request: Request, user: CurrentUser):
    return templates.TemplateResponse(request, "plans/_form.html", {"plan": None})


@router.post("/", response_class=HTMLResponse)
def create_plan(
    request: Request,
    user: CurrentUser,
    name: str = Form(...),
    start_year: str = Form(...),
    end_year: str = Form(...),
):
    with connect() as conn:
        cursor = conn.execute(
            "INSERT INTO rotation_plans (user_id, name, start_year, end_year) "
            "VALUES (?, ?, ?, ?)",
            (user["id"], name, start_year, end_year),
        )
        plan_id = cursor.lastrowid
    plan = _fetch_plan(user["id"], plan_id)
    return templates.TemplateResponse(request, "plans/_row.html", {"plan": plan})


@router.get("/{plan_id}/edit", response_class=HTMLResponse)
def edit_plan_form(request: Request, user: CurrentUser, plan_id: int):
    plan = _fetch_plan(user["id"], plan_id)
    return templates.TemplateResponse(request, "plans/_form.html", {"plan": plan})


@router.get("/{plan_id}")
def plan_detail(request: Request, user: CurrentUser, plan_id: int):
    plan = _fetch_plan(user["id"], plan_id)
    return templates.TemplateResponse(
        request, "plans/detail.html", {"user": user, "plan": plan}
    )


@router.post("/{plan_id}/optimize", response_class=HTMLResponse)
def optimize_plan(request: Request, user: CurrentUser, plan_id: int):
    plan = _fetch_plan(user["id"], plan_id)
    from app.optimizer_service import run_optimization_for_plan

    result = run_optimization_for_plan(user["id"], plan)
    return templates.TemplateResponse(
        request, "plans/_result.html", {"plan": plan, "result": result}
    )


@router.get("/{plan_id}/constraints")
def constraints_editor(request: Request, user: CurrentUser, plan_id: int):
    from app.optimizer_service import load_constraints_dict

    plan = _fetch_plan(user["id"], plan_id)
    constraints = load_constraints_dict(plan)
    return templates.TemplateResponse(
        request,
        "plans/constraints.html",
        {"user": user, "plan": plan, "constraints": constraints},
    )


@router.post("/{plan_id}/constraints")
async def save_constraints(
    request: Request,
    user: CurrentUser,
    plan_id: int,
):
    """フォーム全体を保存。同名の繰り返しフィールド (crops, min_ha, ...) を
    parallel-index で読む。FastAPI の Form だと List[str] は型強制で
    詰まることがあるため、生 form() を扱う。"""
    import json as _json

    plan = _fetch_plan(user["id"], plan_id)
    form = await request.form()
    crops = form.getlist("crop")
    min_ha_list = form.getlist("min_ha")
    cap_ha_list = form.getlist("cap_ha")
    min_gap_list = form.getlist("min_gap_years")
    min_fields_list = form.getlist("min_fields")
    max_fields_list = form.getlist("max_fields")

    constraints: dict[str, dict] = {}
    for i, crop in enumerate(crops):
        crop = crop.strip()
        if not crop:
            continue
        constraints[crop] = {
            "min_ha": _opt_float(min_ha_list[i] if i < len(min_ha_list) else ""),
            "cap_ha": _opt_float(cap_ha_list[i] if i < len(cap_ha_list) else ""),
            "min_gap_years": _opt_int(min_gap_list[i] if i < len(min_gap_list) else "", 0),
            "min_fields": _opt_int(min_fields_list[i] if i < len(min_fields_list) else "", 0),
            "max_fields": _opt_int_or_none(max_fields_list[i] if i < len(max_fields_list) else ""),
        }

    with connect() as conn:
        conn.execute(
            "UPDATE rotation_plans SET constraints_json = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND user_id = ?",
            (_json.dumps(constraints, ensure_ascii=False), plan_id, user["id"]),
        )

    return RedirectResponse(f"/plans/{plan_id}/constraints", status_code=303)


@router.post("/{plan_id}/constraints/add")
async def add_constraint_crop(
    request: Request,
    user: CurrentUser,
    plan_id: int,
    new_crop: str = Form(...),
):
    from app.optimizer_service import load_constraints_dict
    import json as _json

    plan = _fetch_plan(user["id"], plan_id)
    new_crop = new_crop.strip()
    if not new_crop:
        return RedirectResponse(f"/plans/{plan_id}/constraints", status_code=303)
    constraints = load_constraints_dict(plan)
    if new_crop not in constraints:
        constraints[new_crop] = {
            "min_ha": None, "cap_ha": None,
            "min_gap_years": 0, "min_fields": 0, "max_fields": None,
        }
    with connect() as conn:
        conn.execute(
            "UPDATE rotation_plans SET constraints_json = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND user_id = ?",
            (_json.dumps(constraints, ensure_ascii=False), plan_id, user["id"]),
        )
    return RedirectResponse(f"/plans/{plan_id}/constraints", status_code=303)


@router.post("/{plan_id}/constraints/remove")
async def remove_constraint_crop(
    request: Request,
    user: CurrentUser,
    plan_id: int,
    crop: str = Form(...),
):
    from app.optimizer_service import load_constraints_dict
    import json as _json

    plan = _fetch_plan(user["id"], plan_id)
    constraints = load_constraints_dict(plan)
    constraints.pop(crop, None)
    with connect() as conn:
        conn.execute(
            "UPDATE rotation_plans SET constraints_json = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND user_id = ?",
            (_json.dumps(constraints, ensure_ascii=False), plan_id, user["id"]),
        )
    return RedirectResponse(f"/plans/{plan_id}/constraints", status_code=303)


@router.post("/{plan_id}/snapshot", response_class=HTMLResponse)
def snapshot_plan(request: Request, user: CurrentUser, plan_id: int):
    """現在の計画結果をスナップショットとして metadata_json に保存。"""
    from datetime import datetime as _dt
    import json as _json
    from app.optimizer_service import run_optimization_for_plan

    plan = _fetch_plan(user["id"], plan_id)
    result = run_optimization_for_plan(user["id"], plan)
    if not result.get("ok"):
        raise HTTPException(400, result.get("message", "最適化失敗"))

    # grid のキーは tuple なので、JSON 化のため文字列キーへ変換
    serializable_grid = {f"{code}|{y}": crop for (code, y), crop in result["grid"].items()}
    snapshot = {
        "taken_at": _dt.now().isoformat(timespec="seconds"),
        "score": result.get("score"),
        "past_years": result["past_years"],
        "future_years": result["future_years"],
        "field_codes": result["field_codes"],
        "grid": serializable_grid,
    }
    with connect() as conn:
        conn.execute(
            "UPDATE rotation_plans SET metadata_json = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND user_id = ?",
            (_json.dumps(snapshot, ensure_ascii=False), plan_id, user["id"]),
        )
    return templates.TemplateResponse(
        request, "plans/_snapshot_result.html",
        {"plan": plan, "taken_at": snapshot["taken_at"]},
    )


@router.get("/{plan_id}/compare")
def compare_plan_vs_history(request: Request, user: CurrentUser, plan_id: int):
    """保存済みスナップショットと現在の crop_history を並べて比較。"""
    import json as _json

    plan = _fetch_plan(user["id"], plan_id)
    snapshot = None
    if plan.get("metadata_json"):
        try:
            snapshot = _json.loads(plan["metadata_json"])
        except _json.JSONDecodeError:
            snapshot = None

    actual_history: dict[tuple[str, str], str] = {}
    if snapshot:
        with connect() as conn:
            rows = conn.execute(
                "SELECT f.field_code, h.year, h.crop FROM crop_history h "
                "JOIN fields f ON h.field_id = f.id WHERE f.user_id = ?",
                (user["id"],),
            ).fetchall()
        for r in rows:
            actual_history[(r["field_code"], r["year"])] = r["crop"]

    return templates.TemplateResponse(
        request, "plans/compare.html",
        {"user": user, "plan": plan, "snapshot": snapshot, "actual": actual_history},
    )


@router.post("/{plan_id}/apply-to-history", response_class=HTMLResponse)
def apply_plan_year_to_history(
    request: Request,
    user: CurrentUser,
    plan_id: int,
    year: str = Form(...),
):
    """指定した将来年の計画結果を crop_history に upsert する。
    年が past_years に入っている場合や、grid に該当年データがない場合はエラー。"""
    from app.optimizer_service import run_optimization_for_plan

    plan = _fetch_plan(user["id"], plan_id)
    result = run_optimization_for_plan(user["id"], plan)
    if not result.get("ok"):
        raise HTTPException(400, result.get("message", "最適化失敗"))
    if year not in result["future_years"]:
        raise HTTPException(400, f"年 {year} は計画の将来年 {result['future_years']} に含まれません")

    applied = 0
    with connect() as conn:
        # field_code → id の逆引き
        fmap = {
            r["field_code"]: r["id"]
            for r in conn.execute(
                "SELECT id, field_code FROM fields WHERE user_id = ?", (user["id"],)
            ).fetchall()
        }
        for code in result["field_codes"]:
            crop = result["grid"].get((code, year))
            fid = fmap.get(code)
            if not crop or not fid:
                continue
            conn.execute(
                "INSERT INTO crop_history (field_id, year, crop) VALUES (?, ?, ?) "
                "ON CONFLICT(field_id, year) DO UPDATE SET crop = excluded.crop",
                (fid, year, crop),
            )
            applied += 1

    return templates.TemplateResponse(
        request,
        "plans/_apply_result.html",
        {"plan": plan, "year": year, "applied": applied},
    )


@router.get("/{plan_id}/result.pdf")
def export_result_pdf(user: CurrentUser, plan_id: int):
    from fastapi.responses import Response
    from app.optimizer_service import run_optimization_for_plan
    from app.pdf_service import generate_plan_pdf

    plan = _fetch_plan(user["id"], plan_id)
    result = run_optimization_for_plan(user["id"], plan)
    pdf_bytes = generate_plan_pdf(plan, result)
    return Response(
        pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="plan_{plan_id}.pdf"'},
    )


@router.get("/{plan_id}/result.csv")
def export_result_csv(user: CurrentUser, plan_id: int):
    import io, csv
    from fastapi.responses import StreamingResponse
    from app.optimizer_service import run_optimization_for_plan

    plan = _fetch_plan(user["id"], plan_id)
    result = run_optimization_for_plan(user["id"], plan)
    buf = io.StringIO()
    w = csv.writer(buf)
    if not result.get("ok"):
        w.writerow(["error", result.get("message", "")])
    else:
        header = ["圃場"] + list(result["past_years"]) + list(result["future_years"])
        w.writerow(header)
        for code in result["field_codes"]:
            row = [code]
            for y in result["past_years"]:
                row.append(result["grid"].get((code, y), ""))
            for y in result["future_years"]:
                row.append(result["grid"].get((code, y), ""))
            w.writerow(row)
    buf.seek(0)
    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="plan_{plan_id}.csv"'},
    )


def _opt_float(s: str):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _opt_int(s: str, default: int):
    s = (s or "").strip()
    if not s:
        return default
    try:
        return int(float(s))
    except ValueError:
        return default


def _opt_int_or_none(s: str):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


@router.put("/{plan_id}", response_class=HTMLResponse)
def update_plan(
    request: Request,
    user: CurrentUser,
    plan_id: int,
    name: str = Form(...),
    start_year: str = Form(...),
    end_year: str = Form(...),
):
    with connect() as conn:
        result = conn.execute(
            "UPDATE rotation_plans SET name=?, start_year=?, end_year=?, "
            "updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?",
            (name, start_year, end_year, plan_id, user["id"]),
        )
        if result.rowcount == 0:
            raise HTTPException(404, "計画が見つかりません")
    plan = _fetch_plan(user["id"], plan_id)
    return templates.TemplateResponse(request, "plans/_row.html", {"plan": plan})


@router.delete("/{plan_id}")
def delete_plan(user: CurrentUser, plan_id: int):
    with connect() as conn:
        result = conn.execute(
            "DELETE FROM rotation_plans WHERE id = ? AND user_id = ?",
            (plan_id, user["id"]),
        )
        if result.rowcount == 0:
            raise HTTPException(404, "計画が見つかりません")
    return Response(status_code=200)
