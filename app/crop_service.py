"""作物名まわりのサービス層。

作物名の「原点」は FAMIC 登録適用部 (pesticide_usage.crop)。
crop_master はそこから採用した canonical 作物 (FAMIC 表記)、crop_alias は
俗称 (ビート/砂糖大根 等) → canonical の一級マッピング。

いずれも app.db.connect() の生 SQL で扱い、ルーターを薄く保つ。
"""
from app.db import connect

# crop_history 上の「不明」マーカー。正規化で作物名として畳み込まない。
UNKNOWN_MARKER = "UNKNOWN"


# -----------------------------------------------------------------------------
# FAMIC (pesticide_usage) = 作物名の原点
# -----------------------------------------------------------------------------

def famic_search_crops(keyword: str | None, limit: int = 50) -> list[str]:
    """FAMIC 適用情報からユニークな作物名を検索 (部分一致)。"""
    with connect() as conn:
        if keyword:
            rows = conn.execute(
                "SELECT DISTINCT crop FROM pesticide_usage "
                "WHERE crop LIKE ? ORDER BY crop LIMIT ?",
                (f"%{keyword}%", limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT DISTINCT crop FROM pesticide_usage ORDER BY crop LIMIT ?",
                (limit,),
            ).fetchall()
    return [r["crop"] for r in rows if r["crop"]]


def famic_has_data() -> bool:
    with connect() as conn:
        return conn.execute("SELECT 1 FROM pesticide_usage LIMIT 1").fetchone() is not None


def famic_crop_exists(conn, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM pesticide_usage WHERE crop = ? LIMIT 1", (name,)
    ).fetchone() is not None


# -----------------------------------------------------------------------------
# crop_master (canonical) / crop_alias (俗称)
# -----------------------------------------------------------------------------

def ensure_crop_master(conn, name: str) -> int:
    """crop_master に name が無ければ追加し id を返す (既存ならその id)。"""
    row = conn.execute("SELECT id FROM crop_master WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO crop_master (name, is_active) VALUES (?, 1)", (name,)
    )
    return cur.lastrowid


def aliases_for(conn, crop_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT id, alias FROM crop_alias WHERE crop_id = ? ORDER BY alias",
        (crop_id,),
    ).fetchall()]


def normalize_crop_name(conn, raw: str | None) -> str:
    """俗称 → canonical に畳み込む。

    1. crop_master.name と完全一致ならそのまま (canonical)
    2. crop_alias.alias と一致すれば、その canonical 名
    3. どちらも無ければ入力そのまま (未知作物はフリーテキストのまま残す)
    """
    if raw is None:
        return raw
    s = raw.strip()
    if not s or s == UNKNOWN_MARKER:
        return s
    if conn.execute("SELECT 1 FROM crop_master WHERE name = ?", (s,)).fetchone():
        return s
    row = conn.execute(
        "SELECT cm.name FROM crop_alias ca "
        "JOIN crop_master cm ON cm.id = ca.crop_id WHERE ca.alias = ?",
        (s,),
    ).fetchone()
    if row:
        return row["name"]
    return s
