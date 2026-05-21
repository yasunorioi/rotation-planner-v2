"""バックアップ — SQLite ファイルをそのままダウンロード。

sqlite3 の backup API を使って、書込中の DB でも一貫した snapshot を取る。
"""
import io
import sqlite3
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates

from app.auth import CurrentUser
from app.db import configure_db

router = APIRouter(prefix="/backup")
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)


@router.get("/")
def backup_page(request: Request, user: CurrentUser):
    return templates.TemplateResponse(
        request, "backup/index.html", {"user": user}
    )


@router.get("/download")
def download_backup(user: CurrentUser):
    """SQLite ファイル全体を sqlite3.backup() でメモリ上にコピーして返す。
    file:::memory: を経由するので書込中でも一貫性のあるスナップショット。"""
    db_path = configure_db()
    if not db_path.exists():
        raise HTTPException(404, "DB ファイルがありません")
    # メモリ DB へ backup → ファイルに保存
    src = sqlite3.connect(str(db_path))
    try:
        dst = sqlite3.connect(":memory:")
        src.backup(dst)
        # serialize() でバイト列化 (Python 3.11+)
        try:
            blob = dst.serialize()
        except AttributeError:
            # フォールバック: 一時ファイル経由
            import tempfile, os
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp_path = tmp.name
            tmp_conn = sqlite3.connect(tmp_path)
            dst.backup(tmp_conn)
            tmp_conn.close()
            blob = open(tmp_path, "rb").read()
            os.unlink(tmp_path)
        dst.close()
    finally:
        src.close()
    fname = f"rotation_planner_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    return Response(
        blob,
        media_type="application/x-sqlite3",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
