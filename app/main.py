"""FastAPI アプリエントリポイント。"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.db import configure_db
from app.routes import dashboard, fields, history, plans

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_db()
    yield


app = FastAPI(title="rotation-planner v2", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.include_router(dashboard.router)
app.include_router(fields.router)
app.include_router(history.router)
app.include_router(plans.router)
