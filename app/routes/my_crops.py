"""作物を選ぶ — ユーザーが作る作物 (user_crops) を管理する。

設計:
- 作物名の「原点」は FAMIC 登録適用部 (pesticide_usage)。検索して採用する。
- 採用した作物は crop_master (canonical/FAMIC 表記) に無ければ追加し、user_crops へ。
- 俗称 (ビート/砂糖大根 等) は crop_alias に一級で持つ (custom_name は使わない)。
- 輪作計画はここで選んだ作物集合で組まれる (optimizer_service 参照)。
"""
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from app.auth import CurrentUser
from app.crop_service import (
    aliases_for,
    ensure_crop_master,
    famic_has_data,
    famic_search_crops,
)
from app.db import connect

router = APIRouter(prefix="/my-crops")
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)


def _selected_crops(conn, uid: int) -> list[dict]:
    """ユーザーが選択中の作物 (canonical) + 別名。"""
    rows = conn.execute(
        "SELECT cm.id, cm.name FROM user_crops uc "
        "JOIN crop_master cm ON cm.id = uc.parent_crop_id "
        "WHERE uc.user_id = ? AND uc.custom_name IS NULL AND cm.is_active = 1 "
        "ORDER BY cm.display_order, cm.name",
        (uid,),
    ).fetchall()
    out = []
    for r in rows:
        out.append({"id": r["id"], "name": r["name"], "aliases": aliases_for(conn, r["id"])})
    return out


def _unselected_master(conn, uid: int) -> list[dict]:
    """crop_master にあるが未選択の作物 (クイック追加用)。"""
    rows = conn.execute(
        "SELECT id, name FROM crop_master WHERE is_active = 1 AND id NOT IN ("
        "  SELECT parent_crop_id FROM user_crops WHERE user_id = ? AND custom_name IS NULL"
        ") ORDER BY display_order, name",
        (uid,),
    ).fetchall()
    return [dict(r) for r in rows]


def _list_ctx(conn, uid: int) -> dict:
    return {
        "selected": _selected_crops(conn, uid),
        "unselected": _unselected_master(conn, uid),
    }


def _render_list(request: Request, uid: int) -> HTMLResponse:
    with connect() as conn:
        ctx = _list_ctx(conn, uid)
    return templates.TemplateResponse(request, "my_crops/_list.html", ctx)


@router.get("/", response_class=HTMLResponse)
def page(request: Request, user: CurrentUser):
    with connect() as conn:
        ctx = _list_ctx(conn, user["id"])
    ctx["user"] = user
    ctx["famic_ready"] = famic_has_data()
    return templates.TemplateResponse(request, "my_crops/index.html", ctx)


# --- FAMIC 検索 (作物名の原点) --------------------------------------------

@router.get("/famic", response_class=HTMLResponse)
def famic_search(request: Request, user: CurrentUser, q: str = ""):
    q = q.strip()
    results = famic_search_crops(q, limit=40) if q else []
    with connect() as conn:
        existing = {
            r["name"] for r in conn.execute("SELECT name FROM crop_master").fetchall()
        }
    return templates.TemplateResponse(
        request, "my_crops/_famic_results.html",
        {"q": q, "results": results, "existing": existing},
    )


@router.post("/famic/add", response_class=HTMLResponse)
def famic_add(request: Request, user: CurrentUser, name: str = Form(...)):
    name = name.strip()
    if not name:
        raise HTTPException(400, "作物名が空です")
    with connect() as conn:
        # FAMIC に存在する作物名のみ採用を許す (捏造防止)
        if not conn.execute(
            "SELECT 1 FROM pesticide_usage WHERE crop = ? LIMIT 1", (name,)
        ).fetchone():
            raise HTTPException(400, f"FAMIC 適用情報に「{name}」が見つかりません")
        cid = ensure_crop_master(conn, name)
        conn.execute(
            "INSERT OR IGNORE INTO user_crops (user_id, parent_crop_id, custom_name) "
            "VALUES (?, ?, NULL)",
            (user["id"], cid),
        )
    return _render_list(request, user["id"])


# --- user_crops 選択の増減 -------------------------------------------------

@router.post("/add/{crop_id}", response_class=HTMLResponse)
def add_selected(request: Request, user: CurrentUser, crop_id: int):
    with connect() as conn:
        if not conn.execute(
            "SELECT 1 FROM crop_master WHERE id = ? AND is_active = 1", (crop_id,)
        ).fetchone():
            raise HTTPException(404, "作物が見つかりません")
        conn.execute(
            "INSERT OR IGNORE INTO user_crops (user_id, parent_crop_id, custom_name) "
            "VALUES (?, ?, NULL)",
            (user["id"], crop_id),
        )
    return _render_list(request, user["id"])


@router.post("/remove/{crop_id}", response_class=HTMLResponse)
def remove_selected(request: Request, user: CurrentUser, crop_id: int):
    with connect() as conn:
        conn.execute(
            "DELETE FROM user_crops WHERE user_id = ? AND parent_crop_id = ? "
            "AND custom_name IS NULL",
            (user["id"], crop_id),
        )
    return _render_list(request, user["id"])


# --- 別名 (crop_alias) -----------------------------------------------------

@router.post("/{crop_id}/aliases", response_class=HTMLResponse)
def add_alias(request: Request, user: CurrentUser, crop_id: int, alias: str = Form(...)):
    alias = alias.strip()
    with connect() as conn:
        if not conn.execute(
            "SELECT 1 FROM crop_master WHERE id = ?", (crop_id,)
        ).fetchone():
            raise HTTPException(404, "作物が見つかりません")
        if alias:
            # canonical 名と衝突する別名は作らない (曖昧回避)
            clash = conn.execute(
                "SELECT 1 FROM crop_master WHERE name = ?", (alias,)
            ).fetchone()
            if not clash:
                # alias は UNIQUE。既存なら黙って無視 (別作物に取られている等)。
                conn.execute(
                    "INSERT OR IGNORE INTO crop_alias (crop_id, alias) VALUES (?, ?)",
                    (crop_id, alias),
                )
    return _render_list(request, user["id"])


@router.delete("/aliases/{alias_id}")
def delete_alias(request: Request, user: CurrentUser, alias_id: int):
    with connect() as conn:
        conn.execute("DELETE FROM crop_alias WHERE id = ?", (alias_id,))
        ctx = _list_ctx(conn, user["id"])
    return templates.TemplateResponse(request, "my_crops/_list.html", ctx)
