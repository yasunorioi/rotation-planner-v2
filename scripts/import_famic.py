"""FAMIC 農薬登録データを DB に取り込む。

作物名の「原点」は FAMIC 登録適用部 (pesticide_usage.crop)。
/my-crops の FAMIC 検索はこのテーブルを引く。

データソース: https://www.acis.famic.go.jp/ddownload/index.htm
  - 登録基本部.xls   → pesticide_registry
  - 登録適用部一/二.xls → pesticide_usage

Usage:
    # 既定 (data/famic/{basic,usage1,usage2}.xls) を本番 DB に取込
    python -m scripts.import_famic

    # ファイル/DB を明示
    python -m scripts.import_famic --basic data/famic/basic.xls \
        --usage data/famic/usage1.xls data/famic/usage2.xls
"""
import argparse
import sys
from pathlib import Path

from app.db import configure_db

BASE_DIR = Path(__file__).resolve().parent.parent
FAMIC_DIR = BASE_DIR / "data" / "famic"


def main() -> int:
    parser = argparse.ArgumentParser(description="FAMIC 農薬登録データ取込")
    parser.add_argument("--basic", default=str(FAMIC_DIR / "basic.xls"),
                        help="登録基本部 xls")
    parser.add_argument("--usage", nargs="*",
                        default=[str(FAMIC_DIR / "usage1.xls"), str(FAMIC_DIR / "usage2.xls")],
                        help="登録適用部 xls (複数可)")
    args = parser.parse_args()

    db_path = configure_db()  # ROTATION_DB を反映しスキーマ整備
    print(f"[import_famic] DB: {db_path}")

    from rotation_planner.famic import importer

    basic = Path(args.basic)
    if not basic.exists():
        print(f"[import_famic] 登録基本部が見つかりません: {basic}", file=sys.stderr)
        return 1
    n_basic = importer.import_famic_basic(str(basic), str(db_path))
    print(f"[import_famic] pesticide_registry: {n_basic} 件")

    n_usage = 0
    for u in args.usage:
        p = Path(u)
        if not p.exists():
            print(f"[import_famic] 適用部スキップ (無し): {p}", file=sys.stderr)
            continue
        n = importer.import_famic_usage(str(p), str(db_path))
        print(f"[import_famic]   {p.name}: {n} 件")
        n_usage += n
    print(f"[import_famic] pesticide_usage: 合計 {n_usage} 件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
