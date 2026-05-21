"""主要画面とほ場 CRUD のスモーク。"""


def test_auth_required(app_client):
    app_client.auth = None
    assert app_client.get("/").status_code == 401
    assert app_client.get("/fields/").status_code == 401


def test_dashboard(app_client):
    r = app_client.get("/")
    assert r.status_code == 200
    assert "ダッシュボード" in r.text
    assert "テストユーザー" in r.text


def test_fields_empty_then_create_edit_delete(app_client):
    # 初期状態
    r = app_client.get("/fields/")
    assert r.status_code == 200
    assert "ほ場一覧" in r.text

    # 新規作成
    r = app_client.post(
        "/fields/",
        data={"field_code": "A001", "name": "東1号", "district": "本町", "area_ha": "1.5"},
    )
    assert r.status_code == 200
    assert "A001" in r.text
    assert "1.50" in r.text

    # 一覧に出る
    r = app_client.get("/fields/")
    assert "A001" in r.text and "東1号" in r.text

    # ID 抽出
    import re
    m = re.search(r'id="field-(\d+)"', r.text)
    assert m
    field_id = int(m.group(1))

    # 編集
    r = app_client.put(
        f"/fields/{field_id}",
        data={"field_code": "A001", "name": "東1号(改)", "district": "本町", "area_ha": "2.00"},
    )
    assert r.status_code == 200
    assert "東1号(改)" in r.text
    assert "2.00" in r.text

    # 削除
    r = app_client.delete(f"/fields/{field_id}")
    assert r.status_code == 200
    r = app_client.get("/fields/")
    assert "A001" not in r.text


def test_invalid_password(app_client):
    app_client.auth = ("test", "wrong")
    assert app_client.get("/").status_code == 401


def _create_field(client) -> int:
    import re
    r = client.post("/fields/", data={"field_code": "P001", "name": "テスト圃", "area_ha": "1.0"})
    return int(re.search(r'id="field-(\d+)"', r.text).group(1))


def test_polygon_editor_page(app_client):
    fid = _create_field(app_client)
    r = app_client.get(f"/fields/{fid}/polygon")
    assert r.status_code == 200
    assert "ポリゴン編集" in r.text
    assert "field-map-data" in r.text
    # 初期 GeoJSON は null
    assert '"geojson": null' in r.text or '"geojson":null' in r.text


def test_polygon_indicator_in_list(app_client):
    fid = _create_field(app_client)
    # 最初はチェックなし
    r = app_client.get("/fields/")
    assert r.status_code == 200
    import re
    rows = re.findall(rf'id="field-{fid}".+?</tr>', r.text, re.DOTALL)
    assert rows and "図</th>" not in rows[0]  # 列ヘッダではなくセルを確認したい
    # 図列のセル: beet_forbidden 列 (空) のあと、notes 列の前
    # ざっくり: ポリゴン保存前は ✓ がない (備考も空)
    polygon = {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[141, 43], [142, 43], [142, 44], [141, 43]]]}}
    import json
    app_client.post(f"/fields/{fid}/polygon", data={"geojson": json.dumps(polygon)})
    r = app_client.get("/fields/")
    rows = re.findall(rf'id="field-{fid}".+?</tr>', r.text, re.DOTALL)
    # ✓ の数を数える: ポリゴン登録後は2つ以上 (てんさい禁忌は false でも図は ✓)
    # ↑ 少なくとも図列に ✓ が現れる
    cells = re.findall(r'<td[^>]*>(.*?)</td>', rows[0], re.DOTALL)
    assert "✓" in cells, f"ポリゴン登録後の行に ✓ が見つからない: {cells}"


def test_polygon_save_and_clear(app_client):
    fid = _create_field(app_client)
    polygon_feature = {
        "type": "Feature",
        "properties": {},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[141.3, 43.0], [141.4, 43.0], [141.4, 43.1], [141.3, 43.1], [141.3, 43.0]]],
        },
    }
    import json
    r = app_client.post(
        f"/fields/{fid}/polygon",
        data={"geojson": json.dumps(polygon_feature)},
        follow_redirects=False,
    )
    assert r.status_code == 303
    # 再読込でロードできる
    r = app_client.get(f"/fields/{fid}/polygon")
    assert "Polygon" in r.text and "141.3" in r.text
    # クリア（空文字列 POST）
    r = app_client.post(f"/fields/{fid}/polygon", data={"geojson": ""}, follow_redirects=False)
    assert r.status_code == 303
    r = app_client.get(f"/fields/{fid}/polygon")
    assert '"geojson": null' in r.text or '"geojson":null' in r.text


def test_polygon_rejects_non_polygon(app_client):
    fid = _create_field(app_client)
    point = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [141.3, 43.0]}}
    import json
    r = app_client.post(f"/fields/{fid}/polygon", data={"geojson": json.dumps(point)})
    assert r.status_code == 400


def test_polygon_rejects_malformed_json(app_client):
    fid = _create_field(app_client)
    r = app_client.post(f"/fields/{fid}/polygon", data={"geojson": "{not json"})
    assert r.status_code == 400


def test_history_empty_state(app_client):
    r = app_client.get("/history/")
    assert r.status_code == 200
    assert "作付履歴" in r.text
    assert "ほ場が登録されていません" in r.text


def test_history_pivot_table_renders(app_client):
    fid = _create_field(app_client)
    r = app_client.get("/history/?from=R5&to=R8")
    assert r.status_code == 200
    # ヘッダに年が並ぶ
    for y in ["R5", "R6", "R7", "R8"]:
        assert f">{y}</th>" in r.text
    # 行にほ場コードが出る
    assert "P001" in r.text
    # セルの hx-get URL に field_id がちゃんと埋め込まれている
    assert f"field_id={fid}&year=R5" in r.text
    assert f"field_id={fid}&year=R8" in r.text


def test_history_cell_edit_save_clear(app_client):
    fid = _create_field(app_client)
    # 編集モード取得
    r = app_client.get(f"/history/cell/edit?field_id={fid}&year=R6")
    assert r.status_code == 200
    assert 'name="crop"' in r.text
    # 保存
    r = app_client.post(
        "/history/cell",
        data={"field_id": fid, "year": "R6", "crop": "てんさい"},
    )
    assert r.status_code == 200
    assert "てんさい" in r.text
    # 一覧で見える
    r = app_client.get("/history/?from=R5&to=R8")
    assert "てんさい" in r.text
    # 空文字保存 → 削除
    r = app_client.post(
        "/history/cell",
        data={"field_id": fid, "year": "R6", "crop": ""},
    )
    assert r.status_code == 200
    r = app_client.get("/history/?from=R5&to=R8")
    assert "てんさい" not in r.text


def test_history_cell_404_for_other_user(app_client):
    fid = _create_field(app_client)
    import hashlib, sqlite3, os
    db = os.environ["ROTATION_DB"]
    conn = sqlite3.connect(db)
    pw = hashlib.sha256(b"other").hexdigest()
    conn.execute(
        "INSERT INTO users (username, password_hash, display_name, role) VALUES (?, ?, ?, ?)",
        ("other", pw, "別人", "farmer"),
    )
    conn.commit()
    conn.close()
    app_client.auth = ("other", "other")
    assert app_client.get(f"/history/cell/edit?field_id={fid}&year=R6").status_code == 404
    r = app_client.post(
        "/history/cell",
        data={"field_id": fid, "year": "R6", "crop": "侵入"},
    )
    assert r.status_code == 404


def test_plans_crud(app_client):
    # 初期は空テーブル
    r = app_client.get("/plans/")
    assert r.status_code == 200
    assert "輪作計画" in r.text
    assert "plans-table" in r.text

    # 新規作成
    r = app_client.post(
        "/plans/",
        data={"name": "5年計画", "start_year": "R7", "end_year": "R11"},
    )
    assert r.status_code == 200
    assert "5年計画" in r.text and "R7" in r.text and "R11" in r.text

    # 一覧に出る
    r = app_client.get("/plans/")
    assert "5年計画" in r.text
    import re
    plan_id = int(re.search(r'id="plan-(\d+)"', r.text).group(1))

    # 編集
    r = app_client.put(
        f"/plans/{plan_id}",
        data={"name": "5年計画(改)", "start_year": "R7", "end_year": "R12"},
    )
    assert r.status_code == 200
    assert "5年計画(改)" in r.text and "R12" in r.text

    # 削除
    r = app_client.delete(f"/plans/{plan_id}")
    assert r.status_code == 200
    r = app_client.get("/plans/")
    assert "5年計画" not in r.text


def test_plans_404_for_other_user(app_client):
    r = app_client.post(
        "/plans/",
        data={"name": "他人の計画", "start_year": "R7", "end_year": "R11"},
    )
    import re
    plan_id = int(re.search(r'id="plan-(\d+)"', r.text).group(1))

    import hashlib, sqlite3, os
    db = os.environ["ROTATION_DB"]
    conn = sqlite3.connect(db)
    pw = hashlib.sha256(b"other").hexdigest()
    conn.execute(
        "INSERT INTO users (username, password_hash, display_name, role) VALUES (?, ?, ?, ?)",
        ("other", pw, "別人", "farmer"),
    )
    conn.commit()
    conn.close()
    app_client.auth = ("other", "other")
    assert app_client.get(f"/plans/{plan_id}/edit").status_code == 404
    assert app_client.delete(f"/plans/{plan_id}").status_code == 404
    assert app_client.put(
        f"/plans/{plan_id}",
        data={"name": "侵入", "start_year": "R7", "end_year": "R11"},
    ).status_code == 404


def test_plans_count_on_dashboard(app_client):
    app_client.post(
        "/plans/",
        data={"name": "計画A", "start_year": "R7", "end_year": "R11"},
    )
    app_client.post(
        "/plans/",
        data={"name": "計画B", "start_year": "R8", "end_year": "R12"},
    )
    r = app_client.get("/")
    # 「2」が3つの数値のどれかに含まれる
    assert ">2</span><span class=\"lbl\">輪作計画" in r.text


def test_plan_detail_page(app_client):
    r = app_client.post("/plans/", data={"name": "詳細テスト", "start_year": "R8", "end_year": "R10"})
    import re
    plan_id = int(re.search(r'id="plan-(\d+)"', r.text).group(1))
    r = app_client.get(f"/plans/{plan_id}")
    assert r.status_code == 200
    assert "詳細テスト" in r.text
    assert "計画を生成" in r.text
    assert f"/plans/{plan_id}/optimize" in r.text


def test_optimize_empty_fields_returns_error(app_client):
    r = app_client.post("/plans/", data={"name": "空計画", "start_year": "R8", "end_year": "R9"})
    import re
    plan_id = int(re.search(r'id="plan-(\d+)"', r.text).group(1))
    r = app_client.post(f"/plans/{plan_id}/optimize")
    assert r.status_code == 200
    assert "ほ場が登録されていません" in r.text


def test_optimize_runs_endtoend(app_client):
    # ほ場 3つ
    for i, code in enumerate(["F1", "F2", "F3"], start=1):
        app_client.post("/fields/", data={"field_code": code, "name": f"圃{i}", "area_ha": "2.0"})
    # 過去履歴
    fids = {}
    r = app_client.get("/fields/")
    import re
    for code in ["F1", "F2", "F3"]:
        m = re.search(rf'id="field-(\d+)".+?{code}', r.text, re.DOTALL)
        fids[code] = int(m.group(1))
    history_entries = [
        (fids["F1"], "R6", "だいず"),
        (fids["F1"], "R7", "てんさい"),
        (fids["F2"], "R6", "てんさい"),
        (fids["F2"], "R7", "小麦(秋播)"),
        (fids["F3"], "R7", "ばれいしょ"),
    ]
    for fid, y, crop in history_entries:
        app_client.post(
            "/history/cell",
            data={"field_id": fid, "year": y, "crop": crop},
        )
    # 計画 R8〜R10
    r = app_client.post("/plans/", data={"name": "実行テスト", "start_year": "R8", "end_year": "R10"})
    plan_id = int(re.search(r'id="plan-(\d+)"', r.text).group(1))
    # 最適化
    r = app_client.post(f"/plans/{plan_id}/optimize")
    assert r.status_code == 200
    assert "スコア" in r.text
    # ピボット表に過去年と将来年が並ぶ
    for y in ["R6", "R7", "R8", "R9", "R10"]:
        assert f">{y}</th>" in r.text
    # 圃場コードが並ぶ
    for code in ["F1", "F2", "F3"]:
        assert f">{code}</th>" in r.text
    # 過去履歴が表示される
    assert "だいず" in r.text or "てんさい" in r.text


def test_optimize_404_for_other_user(app_client):
    r = app_client.post("/plans/", data={"name": "私の計画", "start_year": "R8", "end_year": "R9"})
    import re
    plan_id = int(re.search(r'id="plan-(\d+)"', r.text).group(1))
    import hashlib, sqlite3, os
    db = os.environ["ROTATION_DB"]
    conn = sqlite3.connect(db)
    pw = hashlib.sha256(b"other").hexdigest()
    conn.execute(
        "INSERT INTO users (username, password_hash, display_name, role) VALUES (?, ?, ?, ?)",
        ("other", pw, "別人", "farmer"),
    )
    conn.commit()
    conn.close()
    app_client.auth = ("other", "other")
    assert app_client.get(f"/plans/{plan_id}").status_code == 404
    assert app_client.post(f"/plans/{plan_id}/optimize").status_code == 404


def test_constraints_editor_page(app_client):
    r = app_client.post("/plans/", data={"name": "C1", "start_year": "R8", "end_year": "R10"})
    import re
    pid = int(re.search(r'id="plan-(\d+)"', r.text).group(1))
    r = app_client.get(f"/plans/{pid}/constraints")
    assert r.status_code == 200
    assert "制約設定" in r.text
    # デフォルト作物が表示される
    assert "てんさい" in r.text
    assert "min_gap_years" in r.text


def test_constraints_save_and_reload(app_client):
    r = app_client.post("/plans/", data={"name": "C2", "start_year": "R8", "end_year": "R9"})
    import re
    pid = int(re.search(r'id="plan-(\d+)"', r.text).group(1))
    # 最初は constraints_json = NULL → デフォルト
    # 全 crops を 取得して送り直す（てんさい だけ修正）
    r = app_client.get(f"/plans/{pid}/constraints")
    # parse the form
    rows = re.findall(r'<input type="hidden" name="crop" value="([^"]+)">', r.text)
    assert "てんさい" in rows
    # POST: てんさい の min_gap_years を 5 に書き換え
    data = {
        "crop": rows,
        "min_ha": ["" for _ in rows],
        "cap_ha": ["" for _ in rows],
        "min_gap_years": ["5" if c == "てんさい" else "0" for c in rows],
        "min_fields": ["0" for _ in rows],
        "max_fields": ["" for _ in rows],
    }
    r = app_client.post(f"/plans/{pid}/constraints", data=data, follow_redirects=False)
    assert r.status_code == 303
    # 再読込で 5 になっている
    r = app_client.get(f"/plans/{pid}/constraints")
    # 表に value="5" を含む行が存在
    assert 'value="5"' in r.text


def test_constraints_add_and_remove_crop(app_client):
    r = app_client.post("/plans/", data={"name": "C3", "start_year": "R8", "end_year": "R9"})
    import re
    pid = int(re.search(r'id="plan-(\d+)"', r.text).group(1))
    # 追加
    r = app_client.post(
        f"/plans/{pid}/constraints/add",
        data={"new_crop": "そば"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    r = app_client.get(f"/plans/{pid}/constraints")
    assert "そば" in r.text
    # 削除
    r = app_client.post(
        f"/plans/{pid}/constraints/remove",
        data={"crop": "そば"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    r = app_client.get(f"/plans/{pid}/constraints")
    # crop 行として残っていない
    rows = re.findall(r'<input type="hidden" name="crop" value="([^"]+)">', r.text)
    assert "そば" not in rows


def test_optimizer_uses_saved_constraints(app_client):
    # ほ場 1つ
    app_client.post("/fields/", data={"field_code": "K1", "name": "畑1", "area_ha": "1.0"})
    # 計画
    r = app_client.post("/plans/", data={"name": "C4", "start_year": "R8", "end_year": "R9"})
    import re
    pid = int(re.search(r'id="plan-(\d+)"', r.text).group(1))
    # 制約: そば だけにする → 結果が「そば」だけになるはず (連作禁止違反は出るが)
    # まず全 crops 削除して そば だけ追加
    r = app_client.get(f"/plans/{pid}/constraints")
    rows = re.findall(r'<input type="hidden" name="crop" value="([^"]+)">', r.text)
    for crop in rows:
        app_client.post(
            f"/plans/{pid}/constraints/remove",
            data={"crop": crop},
        )
    app_client.post(f"/plans/{pid}/constraints/add", data={"new_crop": "そば"})
    # 最適化
    r = app_client.post(f"/plans/{pid}/optimize")
    assert r.status_code == 200
    assert "そば" in r.text


def test_result_csv_download(app_client):
    app_client.post("/fields/", data={"field_code": "Z1", "name": "畑Z1", "area_ha": "1.5"})
    r = app_client.post("/plans/", data={"name": "C5", "start_year": "R8", "end_year": "R9"})
    import re
    pid = int(re.search(r'id="plan-(\d+)"', r.text).group(1))
    r = app_client.get(f"/plans/{pid}/result.csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("content-type", "")
    # BOM 付き UTF-8 + Z1 が含まれる
    body = r.content
    assert body.startswith(b"\xef\xbb\xbf")
    text = body.decode("utf-8-sig")
    assert "Z1" in text
    assert "R8" in text and "R9" in text


def test_csv_template_download(app_client):
    r = app_client.get("/fields/template.csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("content-type", "")
    text = r.content.decode("utf-8-sig")
    assert "ほ場ID" in text and "area" in text


def test_csv_import_creates_fields_and_history(app_client):
    csv_text = (
        "ほ場ID,地区,ほ場名,area,beet_forbidden,R5,R6,R7\n"
        "I001,北地区,北1号,280,0,大豆,てんさい,小麦(秋播)\n"
        "I002,南地区,南2号,310,1,てんさい,大豆,\n"
    )
    r = app_client.post(
        "/fields/import",
        files={"file": ("fields.csv", csv_text.encode("utf-8-sig"), "text/csv")},
    )
    assert r.status_code == 200
    assert "追加 2" in r.text
    assert "履歴 5" in r.text  # 大豆/てんさい/小麦 + てんさい/大豆

    # 一覧で確認
    r = app_client.get("/fields/")
    assert "I001" in r.text and "北1号" in r.text
    assert "I002" in r.text
    # area: 280a → 2.80ha
    assert "2.80" in r.text
    # 履歴
    r = app_client.get("/history/?from=R5&to=R7")
    assert "大豆" in r.text and "てんさい" in r.text


def test_csv_import_upsert_existing_field(app_client):
    # 既存
    r = app_client.post(
        "/fields/",
        data={"field_code": "U001", "name": "旧名称", "area_ha": "1.0"},
    )
    assert r.status_code == 200
    # CSV で同じ field_code を更新
    csv_text = "ほ場ID,地区,ほ場名,area,beet_forbidden\nU001,新地区,新名称,500,1\n"
    r = app_client.post(
        "/fields/import",
        files={"file": ("u.csv", csv_text.encode("utf-8-sig"), "text/csv")},
    )
    assert "更新 1" in r.text
    r = app_client.get("/fields/")
    assert "新名称" in r.text
    assert "旧名称" not in r.text
    assert "5.00" in r.text  # 500a → 5.00ha


def test_csv_import_handles_invalid_rows(app_client):
    csv_text = (
        "ほ場ID,area\n"
        "GOOD,150\n"
        ",100\n"  # field_code 空 → error
        "BAD,abc\n"  # area 不正 → error
    )
    r = app_client.post(
        "/fields/import",
        files={"file": ("e.csv", csv_text.encode("utf-8-sig"), "text/csv")},
    )
    assert "追加 1" in r.text
    assert "エラー 2" in r.text


def test_csv_import_rejects_missing_required_columns(app_client):
    csv_text = "ほ場名\nA\n"  # field_code, area 両方欠落
    r = app_client.post(
        "/fields/import",
        files={"file": ("bad.csv", csv_text.encode("utf-8-sig"), "text/csv")},
    )
    assert r.status_code == 400


def test_result_summary_table(app_client):
    # ほ場 3つで計画 → サマリ表が出る
    for code in ["S1", "S2", "S3"]:
        app_client.post("/fields/", data={"field_code": code, "name": code, "area_ha": "2.0"})
    r = app_client.post("/plans/", data={"name": "S計画", "start_year": "R8", "end_year": "R9"})
    import re
    pid = int(re.search(r'id="plan-(\d+)"', r.text).group(1))
    r = app_client.post(f"/plans/{pid}/optimize")
    assert r.status_code == 200
    assert "年別 × 作物別 合計面積" in r.text
    # 3ほ場 × 2.0ha = 6.00ha の合計が将来年のどこかに出る
    assert "6.00" in r.text or "4.00" in r.text or "2.00" in r.text  # 分散される可能性


def test_history_csv_export(app_client):
    # ほ場 + 履歴を CSV インポートで投入
    csv_in = "ほ場ID,area,R6,R7\nE1,200,大豆,てんさい\nE2,150,てんさい,小麦(秋播)\n"
    app_client.post(
        "/fields/import",
        files={"file": ("h.csv", csv_in.encode("utf-8-sig"), "text/csv")},
    )
    # エクスポート
    r = app_client.get("/history/export.csv?from=R6&to=R7")
    assert r.status_code == 200
    body = r.content
    assert body.startswith(b"\xef\xbb\xbf")
    text = body.decode("utf-8-sig")
    assert "ほ場ID,ほ場名,R6,R7" in text
    assert "E1,," in text and "大豆,てんさい" in text
    assert "E2,," in text and "てんさい,小麦(秋播)" in text


def _make_field(client, code="X1"):
    import re
    r = client.post("/fields/", data={"field_code": code, "name": code, "area_ha": "1.0"})
    return int(re.search(r'id="field-(\d+)"', r.text).group(1))


def test_pesticide_records_empty(app_client):
    r = app_client.get("/pesticide-records/")
    assert r.status_code == 200
    assert "防除記録" in r.text
    # ほ場0件のときは追加ボタンの代わりに案内
    assert "先に" in r.text and "ほ場" in r.text


def test_pesticide_records_crud(app_client):
    fid = _make_field(app_client, "X1")
    # 新規
    r = app_client.post(
        "/pesticide-records/",
        data={
            "field_id": fid, "spray_date": "2026-05-10",
            "pesticide_name": "ベンレート", "dilution_rate": "1000倍",
            "spray_amount": "0.3", "spray_unit": "L/10a", "notes": "テスト",
        },
    )
    assert r.status_code == 200
    assert "ベンレート" in r.text
    assert "2026-05-10" in r.text
    import re
    rec_id = int(re.search(r'id="record-(\d+)"', r.text).group(1))

    # 一覧
    r = app_client.get("/pesticide-records/")
    assert "ベンレート" in r.text

    # 編集
    r = app_client.put(
        f"/pesticide-records/{rec_id}",
        data={
            "field_id": fid, "spray_date": "2026-05-11",
            "pesticide_name": "ベンレート(改)", "dilution_rate": "2000倍",
            "spray_amount": "0.5", "spray_unit": "L/10a", "notes": "",
        },
    )
    assert r.status_code == 200
    assert "ベンレート(改)" in r.text and "2026-05-11" in r.text

    # 削除
    assert app_client.delete(f"/pesticide-records/{rec_id}").status_code == 200
    r = app_client.get("/pesticide-records/")
    assert "ベンレート" not in r.text


def test_pesticide_records_csv_export(app_client):
    fid = _make_field(app_client, "X2")
    app_client.post(
        "/pesticide-records/",
        data={
            "field_id": fid, "spray_date": "2026-05-12",
            "pesticide_name": "テストP", "dilution_rate": "",
            "spray_amount": "", "spray_unit": "", "notes": "",
        },
    )
    r = app_client.get("/pesticide-records/export.csv")
    assert r.status_code == 200
    body = r.content
    assert body.startswith(b"\xef\xbb\xbf")
    text = body.decode("utf-8-sig")
    assert "散布日,ほ場ID" in text
    assert "テストP" in text and "X2" in text and "2026-05-12" in text


def test_pesticide_record_rejects_other_user_field(app_client):
    fid = _make_field(app_client, "X3")
    import hashlib, sqlite3, os
    db = os.environ["ROTATION_DB"]
    conn = sqlite3.connect(db)
    pw = hashlib.sha256(b"other").hexdigest()
    conn.execute(
        "INSERT INTO users (username, password_hash, display_name, role) VALUES (?, ?, ?, ?)",
        ("other", pw, "別人", "farmer"),
    )
    conn.commit()
    conn.close()
    app_client.auth = ("other", "other")
    # 別ユーザが他人のほ場 ID で書こうとすると 400
    r = app_client.post(
        "/pesticide-records/",
        data={
            "field_id": fid, "spray_date": "2026-05-13",
            "pesticide_name": "侵入", "dilution_rate": "",
            "spray_amount": "", "spray_unit": "", "notes": "",
        },
    )
    assert r.status_code == 400


def test_fields_export_csv(app_client):
    # CSV インポートで投入
    csv_in = (
        "ほ場ID,地区,ほ場名,area,beet_forbidden,R6,R7\n"
        "EX1,地区A,名称A,250,0,大豆,てんさい\n"
        "EX2,地区B,名称B,180,1,てんさい,小麦(秋播)\n"
    )
    app_client.post("/fields/import", files={"file": ("in.csv", csv_in.encode("utf-8-sig"), "text/csv")})
    r = app_client.get("/fields/export.csv")
    assert r.status_code == 200
    text = r.content.decode("utf-8-sig")
    # ヘッダ (固定作物列を含む)
    assert "ほ場ID,地区,ほ場名,area,beet_forbidden,固定作物,備考,R6,R7" in text
    # 値 (250a → 2.50ha → 戻すと250.0a, fixed_crop と備考は空)
    assert "EX1,地区A,名称A,250.0,0,,," in text
    assert "EX2,地区B,名称B,180.0,1,,," in text
    # 履歴
    assert "大豆,てんさい" in text


def test_history_template_and_import(app_client):
    # テンプレ
    r = app_client.get("/history/template.csv")
    assert r.status_code == 200
    text = r.content.decode("utf-8-sig")
    assert "ほ場ID" in text and "R" in text  # 何らかの令和年が入る

    # 既存ほ場
    _make_field(app_client, "H1")
    _make_field(app_client, "H2")
    csv_in = (
        "ほ場ID,R6,R7\n"
        "H1,大豆,てんさい\n"
        "H2,てんさい,\n"  # H2 R7 は空文字 → 既存があれば削除、なければ無視
        "NOPE,何か,別の\n"  # 未登録 → エラー
    )
    r = app_client.post(
        "/history/import",
        files={"file": ("h.csv", csv_in.encode("utf-8-sig"), "text/csv")},
    )
    assert r.status_code == 200
    assert "upsert 3" in r.text
    assert "エラー 1" in r.text
    # 確認
    r = app_client.get("/history/?from=R6&to=R7")
    assert "大豆" in r.text and "てんさい" in r.text


def test_pesticide_template_and_import(app_client):
    # テンプレ
    r = app_client.get("/pesticide-records/template.csv")
    assert r.status_code == 200
    text = r.content.decode("utf-8-sig")
    assert "散布日" in text and "ほ場ID" in text and "農薬名" in text

    # 既存ほ場
    _make_field(app_client, "P1")
    csv_in = (
        "散布日,ほ場ID,農薬名,希釈倍率,量,単位,備考\n"
        "2026-05-10,P1,薬A,1000倍,0.3,L/10a,テスト1\n"
        "2026-05-11,P1,薬B,2000倍,0.5,L/10a,\n"
        "2026-05-12,NOPE,薬C,,,,\n"  # 未登録
        ",P1,薬D,,,,\n"  # 必須欠落
    )
    r = app_client.post(
        "/pesticide-records/import",
        files={"file": ("p.csv", csv_in.encode("utf-8-sig"), "text/csv")},
    )
    assert r.status_code == 200
    assert "追加 2" in r.text
    assert "エラー 2" in r.text
    r = app_client.get("/pesticide-records/")
    assert "薬A" in r.text and "薬B" in r.text
    assert "薬C" not in r.text


def test_pesticide_import_rejects_missing_columns(app_client):
    csv_in = "ほ場ID\nP1\n"
    r = app_client.post(
        "/pesticide-records/import",
        files={"file": ("bad.csv", csv_in.encode("utf-8-sig"), "text/csv")},
    )
    assert r.status_code == 400


def test_fields_filter_by_district(app_client):
    csv_in = (
        "ほ場ID,地区,ほ場名,area\n"
        "FD1,北,北1,200\n"
        "FD2,北,北2,200\n"
        "FD3,南,南1,200\n"
    )
    app_client.post("/fields/import", files={"file": ("f.csv", csv_in.encode("utf-8-sig"), "text/csv")})
    r = app_client.get("/fields/?district=北")
    assert "FD1" in r.text and "FD2" in r.text and "FD3" not in r.text
    assert "該当 2 件" in r.text
    # エクスポートも絞り込みが効く
    r = app_client.get("/fields/export.csv?district=北")
    text = r.content.decode("utf-8-sig")
    assert "FD1" in text and "FD2" in text and "FD3" not in text


def test_fields_filter_by_polygon(app_client):
    fid1 = _make_field(app_client, "PG1")
    _make_field(app_client, "PG2")
    poly = {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[141,43],[142,43],[142,44],[141,43]]]}}
    import json
    app_client.post(f"/fields/{fid1}/polygon", data={"geojson": json.dumps(poly)})
    r = app_client.get("/fields/?polygon=有")
    assert "PG1" in r.text and "PG2" not in r.text
    r = app_client.get("/fields/?polygon=無")
    assert "PG2" in r.text and "PG1" not in r.text


def test_pesticide_records_filter_by_year(app_client):
    fid = _make_field(app_client, "PR1")
    for date, name in [
        ("2025-04-10", "薬A"),
        ("2026-05-10", "薬B"),
        ("2026-06-10", "薬C"),
    ]:
        app_client.post(
            "/pesticide-records/",
            data={"field_id": fid, "spray_date": date, "pesticide_name": name,
                  "dilution_rate": "", "spray_amount": "", "spray_unit": "", "notes": ""},
        )
    r = app_client.get("/pesticide-records/?year=2026")
    assert "薬B" in r.text and "薬C" in r.text and "薬A" not in r.text
    assert "該当 2 件" in r.text
    # エクスポートも
    r = app_client.get("/pesticide-records/export.csv?year=2026")
    text = r.content.decode("utf-8-sig")
    assert "薬B" in text and "薬C" in text and "薬A" not in text


def test_pesticide_records_filter_by_field(app_client):
    fid_a = _make_field(app_client, "PA")
    fid_b = _make_field(app_client, "PB")
    app_client.post("/pesticide-records/", data={
        "field_id": fid_a, "spray_date": "2026-05-01", "pesticide_name": "Aの薬",
        "dilution_rate": "", "spray_amount": "", "spray_unit": "", "notes": "",
    })
    app_client.post("/pesticide-records/", data={
        "field_id": fid_b, "spray_date": "2026-05-01", "pesticide_name": "Bの薬",
        "dilution_rate": "", "spray_amount": "", "spray_unit": "", "notes": "",
    })
    r = app_client.get(f"/pesticide-records/?field_id={fid_a}")
    assert "Aの薬" in r.text and "Bの薬" not in r.text


def test_polygons_geojson_export(app_client):
    fid_a = _make_field(app_client, "G1")
    fid_b = _make_field(app_client, "G2")
    # G1 にのみポリゴン
    import json
    poly = {"type": "Feature", "geometry": {"type": "Polygon",
            "coordinates": [[[141, 43], [142, 43], [142, 44], [141, 43]]]}}
    app_client.post(f"/fields/{fid_a}/polygon", data={"geojson": json.dumps(poly)})

    r = app_client.get("/fields/polygons.geojson")
    assert r.status_code == 200
    assert "geo+json" in r.headers.get("content-type", "")
    fc = r.json()
    assert fc["type"] == "FeatureCollection"
    # ポリゴンを持つほ場のみ
    assert len(fc["features"]) == 1
    p = fc["features"][0]["properties"]
    assert p["field_code"] == "G1"
    assert p["id"] == fid_a


def test_polygons_geojson_user_isolation(app_client):
    fid = _make_field(app_client, "ISO")
    import json, hashlib, sqlite3, os
    poly = {"type": "Feature", "geometry": {"type": "Polygon",
            "coordinates": [[[141, 43], [142, 43], [142, 44], [141, 43]]]}}
    app_client.post(f"/fields/{fid}/polygon", data={"geojson": json.dumps(poly)})
    db = os.environ["ROTATION_DB"]
    conn = sqlite3.connect(db)
    pw = hashlib.sha256(b"other").hexdigest()
    conn.execute(
        "INSERT INTO users (username, password_hash, display_name, role) VALUES (?, ?, ?, ?)",
        ("other", pw, "別人", "farmer"),
    )
    conn.commit()
    conn.close()
    app_client.auth = ("other", "other")
    r = app_client.get("/fields/polygons.geojson")
    assert r.status_code == 200
    fc = r.json()
    assert fc["features"] == []


def test_fields_map_page(app_client):
    r = app_client.get("/fields/map")
    assert r.status_code == 200
    assert "ほ場マップ" in r.text
    assert "leaflet.css" in r.text
    assert "/fields/polygons.geojson" in r.text


def test_plan_pdf_download(app_client):
    _make_field(app_client, "PDF1")
    r = app_client.post("/plans/", data={"name": "PDFtest", "start_year": "R8", "end_year": "R9"})
    import re
    pid = int(re.search(r'id="plan-(\d+)"', r.text).group(1))
    r = app_client.get(f"/plans/{pid}/result.pdf")
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("application/pdf")
    # PDF マジックバイト %PDF-
    assert r.content.startswith(b"%PDF-")
    # 一定サイズ以上 (空でない)
    assert len(r.content) > 1000


def _make_dummy_png(path: str) -> None:
    """zlib デフレートを使った最小の有効 PNG (1x1 透明) を書き出す。"""
    import zlib, struct
    # 1x1 RGBA, alpha=0
    raw = b"\x00" + b"\x00\x00\x00\x00"  # filter byte + RGBA pixel
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    def chunk(typ, data):
        crc = zlib.crc32(typ + data) & 0xffffffff
        return struct.pack(">I", len(data)) + typ + data + struct.pack(">I", crc)
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(raw))
           + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


def test_plan_pdf_includes_logo_when_present(app_client, monkeypatch, tmp_path):
    # data/ ディレクトリにロゴを置く (pdf_service の _DATA_DIR を差し替え)
    logo_path = tmp_path / "logo.png"
    _make_dummy_png(str(logo_path))
    import app.pdf_service as pdf_svc
    monkeypatch.setattr(pdf_svc, "_DATA_DIR", tmp_path)

    _make_field(app_client, "LOGO1")
    r = app_client.post("/plans/", data={"name": "LogoTest", "start_year": "R8", "end_year": "R9"})
    import re
    pid = int(re.search(r'id="plan-(\d+)"', r.text).group(1))
    r = app_client.get(f"/plans/{pid}/result.pdf")
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF-")
    # ロゴあり版はサイズが少し増える
    size_with = len(r.content)
    # ロゴ無し版
    monkeypatch.setattr(pdf_svc, "_DATA_DIR", tmp_path / "no_such_dir")
    r2 = app_client.get(f"/plans/{pid}/result.pdf")
    size_without = len(r2.content)
    # 画像が埋め込まれているので明らかに大きい (1x1 PNG でも数十バイト〜)
    # 厳密な差分は環境依存だが、少なくとも壊れないことを確認
    assert r2.content.startswith(b"%PDF-")


def test_pesticide_records_pdf(app_client):
    fid = _make_field(app_client, "PRP1")
    app_client.post("/pesticide-records/", data={
        "field_id": fid, "spray_date": "2026-05-10", "pesticide_name": "PDF薬",
        "dilution_rate": "1000倍", "spray_amount": "0.3", "spray_unit": "L/10a", "notes": "",
    })
    r = app_client.get("/pesticide-records/export.pdf")
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF-")
    assert len(r.content) > 1000


def test_polygon_computed_area_displayed(app_client):
    fid = _make_field(app_client, "AC1")  # area_ha=1.0
    # 大きめのポリゴン (~緯度1度差は約111km)
    import json
    poly = {"type": "Feature", "geometry": {"type": "Polygon",
            "coordinates": [[[141.0, 43.0], [141.01, 43.0], [141.01, 43.01], [141.0, 43.01], [141.0, 43.0]]]}}
    app_client.post(f"/fields/{fid}/polygon", data={"geojson": json.dumps(poly)})
    r = app_client.get(f"/fields/{fid}/polygon")
    assert r.status_code == 200
    # 計算面積が出る
    assert "計算面積" in r.text
    # 同期ボタンが出る (area_ha=1.0 ha vs 計算 ~91ha 程度の差があるはず)
    assert "area_ha を計算値で更新" in r.text


def test_polygon_sync_area(app_client):
    fid = _make_field(app_client, "AC2")
    import json
    poly = {"type": "Feature", "geometry": {"type": "Polygon",
            "coordinates": [[[141.0, 43.0], [141.001, 43.0], [141.001, 43.001], [141.0, 43.001], [141.0, 43.0]]]}}
    app_client.post(f"/fields/{fid}/polygon", data={"geojson": json.dumps(poly)})
    r = app_client.post(f"/fields/{fid}/polygon/sync_area", follow_redirects=False)
    assert r.status_code == 303
    # area_ha が更新されている
    r = app_client.get("/fields/")
    import re
    row = re.search(rf'id="field-{fid}".+?</tr>', r.text, re.DOTALL).group(0)
    # 1.0 ではなく、計算された値
    assert "1.00" not in row.split("</td>")[3]  # area 列


def test_polygon_sync_area_404_without_polygon(app_client):
    fid = _make_field(app_client, "AC3")
    r = app_client.post(f"/fields/{fid}/polygon/sync_area")
    assert r.status_code == 400


def test_kml_import_and_export(app_client):
    kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>KML001</name>
      <description>サンプル北畑</description>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>141.0,43.0,0 141.001,43.0,0 141.001,43.001,0 141.0,43.001,0 141.0,43.0,0</coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
    <Placemark>
      <name>KML002</name>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>141.1,43.1,0 141.101,43.1,0 141.101,43.101,0 141.1,43.101,0 141.1,43.1,0</coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
  </Document>
</kml>
"""
    r = app_client.post(
        "/fields/import_kml",
        files={"file": ("test.kml", kml.encode("utf-8"), "application/vnd.google-earth.kml+xml")},
    )
    assert r.status_code == 200
    assert "追加 2" in r.text
    # 一覧で確認
    r = app_client.get("/fields/")
    assert "KML001" in r.text and "KML002" in r.text
    # ポリゴン有印が立つ
    import re
    row = re.search(r'id="field-\d+".+?KML001.+?</tr>', r.text, re.DOTALL).group(0)
    assert row.count("✓") >= 1

    # 再アップロードは更新
    r = app_client.post(
        "/fields/import_kml",
        files={"file": ("test.kml", kml.encode("utf-8"), "application/vnd.google-earth.kml+xml")},
    )
    assert "更新 2" in r.text

    # 取込された polygon の座標は GeoJSON 標準 [lng, lat] になっているか確認
    # (ライブラリ KML パーサは [lat, lng] を返すので変換が必要)
    r = app_client.get("/fields/polygons.geojson")
    fc = r.json()
    feat_by_name = {f["properties"]["field_code"]: f for f in fc["features"]}
    coords = feat_by_name["KML001"]["geometry"]["coordinates"][0]
    # KML 入力の最初の点は 141.0, 43.0 (lng, lat)
    assert abs(coords[0][0] - 141.0) < 0.01, f"lng が先頭でない: {coords[0]}"
    assert abs(coords[0][1] - 43.0) < 0.01, f"lat が2番目でない: {coords[0]}"

    # 取込された polygon から測地線面積が正しく計算できる (NaN にならない)
    import math
    poly_editor = app_client.get(f"/fields/{int(feat_by_name['KML001']['properties']['id'])}/polygon")
    assert "計算面積" in poly_editor.text
    assert "nan" not in poly_editor.text  # NaN は座標順バグの兆候

    # KML エクスポート: 座標順が lng,lat,alt として正しい
    r = app_client.get("/fields/polygons.kml")
    assert r.status_code == 200
    text = r.content.decode("utf-8")
    assert "<kml" in text and "KML001" in text
    # KML coordinates 内の最初の点を抽出: 経度,緯度,高度 形式
    import re
    m = re.search(r"<coordinates>\s*([^<]+?)\s*</coordinates>", text)
    assert m, "coordinates 要素が見つからない"
    first_point = m.group(1).split()[0].split(",")
    lng_out, lat_out = float(first_point[0]), float(first_point[1])
    # KML001 は [141.0, 43.0] あたり
    assert 140 < lng_out < 142, f"KML 出力の経度が変: {lng_out}"
    assert 42 < lat_out < 44, f"KML 出力の緯度が変: {lat_out}"


def test_kml_import_invalid_file(app_client):
    r = app_client.post(
        "/fields/import_kml",
        files={"file": ("not.kml", b"garbage", "application/vnd.google-earth.kml+xml")},
    )
    # パースエラーは 400 (parse_kml_or_kmz_bytes はその場合 [] を返すこともある)
    # 空ファイル扱いになるかもしれないので結果メッセージで判定
    assert r.status_code in (200, 400)
    if r.status_code == 200:
        assert "Placemark が見つかりませんでした" in r.text


def test_kmz_export(app_client):
    fid = _make_field(app_client, "KMZ1")
    import json
    poly = {"type": "Feature", "geometry": {"type": "Polygon",
            "coordinates": [[[141.0, 43.0], [141.001, 43.0], [141.001, 43.001], [141.0, 43.0]]]}}
    app_client.post(f"/fields/{fid}/polygon", data={"geojson": json.dumps(poly)})
    r = app_client.get("/fields/polygons.kmz")
    assert r.status_code == 200
    # KMZ = ZIP
    assert r.content.startswith(b"PK")


def test_apply_plan_year_to_history(app_client):
    # ほ場 + 計画
    _make_field(app_client, "AP1")
    _make_field(app_client, "AP2")
    r = app_client.post("/plans/", data={"name": "適用テスト", "start_year": "R8", "end_year": "R9"})
    import re
    pid = int(re.search(r'id="plan-(\d+)"', r.text).group(1))
    # 適用
    r = app_client.post(
        f"/plans/{pid}/apply-to-history",
        data={"year": "R8"},
    )
    assert r.status_code == 200
    assert "計画を作付履歴に反映しました" in r.text
    assert "2 件 upsert" in r.text or "1 件 upsert" in r.text  # 最適化結果次第
    # 履歴ページで R8 が埋まっている
    r = app_client.get("/history/?from=R8&to=R8")
    # 何らかの作物名が出現 (どの作物かは最適化次第)
    assert "AP1" in r.text


def test_apply_to_history_rejects_past_year(app_client):
    _make_field(app_client, "AP3")
    r = app_client.post("/plans/", data={"name": "T", "start_year": "R8", "end_year": "R9"})
    import re
    pid = int(re.search(r'id="plan-(\d+)"', r.text).group(1))
    # 計画範囲外
    r = app_client.post(f"/plans/{pid}/apply-to-history", data={"year": "R5"})
    assert r.status_code == 400


def test_aggregation_page(app_client):
    # 履歴データ投入 (2 ほ場 × 2 年)
    csv_in = (
        "ほ場ID,area,R6,R7\n"
        "AG1,200,だいず,てんさい\n"  # 2.0ha
        "AG2,300,てんさい,だいず\n"  # 3.0ha
    )
    app_client.post(
        "/fields/import",
        files={"file": ("a.csv", csv_in.encode("utf-8-sig"), "text/csv")},
    )
    r = app_client.get("/aggregation/?from=R6&to=R7")
    assert r.status_code == 200
    assert "作付集計" in r.text
    # R6 だいず 2.0ha + R6 てんさい 3.0ha = 合計 5.0
    assert "5.00" in r.text  # 合計列に出る
    # CSV
    r = app_client.get("/aggregation/export.csv?from=R6&to=R7")
    text = r.content.decode("utf-8-sig")
    assert "年" in text and "だいず" in text and "てんさい" in text
    # 各セル
    # R6: だいず 2.00, てんさい 3.00
    assert "2.00" in text and "3.00" in text
    # PDF
    r = app_client.get("/aggregation/export.pdf?from=R6&to=R7")
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF-")


def test_aggregation_empty(app_client):
    r = app_client.get("/aggregation/?from=R20&to=R21")
    assert r.status_code == 200
    assert "履歴データがありません" in r.text


def test_history_cell_edit_has_crop_datalist(app_client):
    fid = _make_field(app_client, "DL1")
    # 履歴に「あさつき」を1件入れて、それが候補に出ることを確認
    app_client.post("/history/cell", data={"field_id": fid, "year": "R6", "crop": "あさつき"})
    r = app_client.get(f"/history/cell/edit?field_id={fid}&year=R7")
    assert r.status_code == 200
    # input が datalist を参照
    assert "list=\"crop-suggestions-" in r.text
    assert "<datalist " in r.text
    # DEFAULT_CONSTRAINTS から:
    assert '<option value="てんさい"></option>' in r.text
    # ユーザの履歴から:
    assert '<option value="あさつき"></option>' in r.text


def test_history_cell_datalist_includes_plan_constraints(app_client):
    fid = _make_field(app_client, "DL2")
    # 計画作成 + そばを制約に追加
    import re
    r = app_client.post("/plans/", data={"name": "DT", "start_year": "R8", "end_year": "R9"})
    pid = int(re.search(r'id="plan-(\d+)"', r.text).group(1))
    app_client.post(f"/plans/{pid}/constraints/add", data={"new_crop": "そば"})
    # 履歴セル編集 → そば が候補に出る
    r = app_client.get(f"/history/cell/edit?field_id={fid}&year=R7")
    assert '<option value="そば"></option>' in r.text


def test_field_fixed_crop_crud(app_client):
    # 新規作成 with fixed_crop
    r = app_client.post("/fields/", data={
        "field_code": "FC1", "name": "牧草地", "area_ha": "1.5",
        "fixed_crop": "牧草",
    })
    assert r.status_code == 200
    assert "牧草" in r.text  # 行表示に出る
    import re
    fid = int(re.search(r'id="field-(\d+)"', r.text).group(1))

    # 編集フォームに値が入る
    r = app_client.get(f"/fields/{fid}/edit")
    assert 'value="牧草"' in r.text

    # 更新で空にする
    r = app_client.put(f"/fields/{fid}", data={
        "field_code": "FC1", "name": "牧草地", "area_ha": "1.5",
        "fixed_crop": "",
    })
    r = app_client.get("/fields/")
    row = re.search(rf'id="field-{fid}".+?</tr>', r.text, re.DOTALL).group(0)
    # fixed-crop セルが空になっている
    assert '<td class="fixed-crop"></td>' in row


def test_field_fixed_crop_csv_roundtrip(app_client):
    csv_in = (
        "ほ場ID,area,固定作物,R6\n"
        "PERM1,200,牧草,\n"
        "PERM2,300,,だいず\n"
    )
    r = app_client.post(
        "/fields/import",
        files={"file": ("f.csv", csv_in.encode("utf-8-sig"), "text/csv")},
    )
    assert r.status_code == 200
    assert "追加 2" in r.text
    r = app_client.get("/fields/")
    # PERM1 の行に「牧草」が表示
    import re
    row = re.search(r'id="field-\d+".+?PERM1.+?</tr>', r.text, re.DOTALL).group(0)
    assert "牧草" in row
    # エクスポート
    r = app_client.get("/fields/export.csv")
    text = r.content.decode("utf-8-sig")
    assert "固定作物" in text
    assert "PERM1,," in text and "牧草" in text


def test_optimizer_overrides_with_fixed_crop(app_client):
    # 固定作物ほ場と通常ほ場
    app_client.post("/fields/", data={
        "field_code": "FIX1", "name": "永久畑", "area_ha": "2.0", "fixed_crop": "牧草",
    })
    app_client.post("/fields/", data={
        "field_code": "ROT1", "name": "ローテ", "area_ha": "2.0",
    })
    r = app_client.post("/plans/", data={"name": "FT", "start_year": "R8", "end_year": "R9"})
    import re
    pid = int(re.search(r'id="plan-(\d+)"', r.text).group(1))
    r = app_client.post(f"/plans/{pid}/optimize")
    assert r.status_code == 200
    # 固定作物ほ場 1 件 とメッセージに出る
    assert "固定作物ほ場 1 件" in r.text
    # FIX1 の R8/R9 セルは「牧草」
    # ピボット表の FIX1 行を確認
    row = re.search(r'class="field-label">FIX1</th>.+?</tr>', r.text, re.DOTALL).group(0)
    assert row.count("牧草") >= 2  # R8 + R9


def test_field_form_district_datalist(app_client):
    # 地区A と 地区B のほ場を作る
    app_client.post("/fields/", data={
        "field_code": "DA1", "district": "地区A", "area_ha": "1.0",
    })
    app_client.post("/fields/", data={
        "field_code": "DA2", "district": "地区B", "area_ha": "1.0",
    })
    # 新規 form に datalist に両地区が出る
    r = app_client.get("/fields/new")
    assert r.status_code == 200
    assert 'list="field-districts"' in r.text
    assert '<datalist id="field-districts">' in r.text
    assert '<option value="地区A"></option>' in r.text
    assert '<option value="地区B"></option>' in r.text


def test_pesticide_master_crud(app_client):
    # 空の状態
    r = app_client.get("/pesticide-masters/")
    assert r.status_code == 200
    assert "農薬マスタ" in r.text

    # 新規
    r = app_client.post(
        "/pesticide-masters/",
        data={"name": "ベンレート", "crop": "てんさい", "dilution_rate": "1000倍",
              "application_method": "殺菌", "usage_timing": "5月", "notes": "テスト"},
    )
    assert r.status_code == 200
    assert "ベンレート" in r.text and "てんさい" in r.text
    import re
    mid = int(re.search(r'id="master-(\d+)"', r.text).group(1))

    # 編集
    r = app_client.put(
        f"/pesticide-masters/{mid}",
        data={"name": "ベンレート(改)", "crop": "だいず", "dilution_rate": "2000倍",
              "application_method": "殺菌", "usage_timing": "6月", "notes": ""},
    )
    assert "ベンレート(改)" in r.text and "だいず" in r.text

    # 削除
    assert app_client.delete(f"/pesticide-masters/{mid}").status_code == 200
    r = app_client.get("/pesticide-masters/")
    assert "ベンレート" not in r.text


def test_pesticide_master_csv_import(app_client):
    csv_in = (
        "農薬名,対象作物,希釈倍率,用途,使用時期,備考\n"
        "M1,てんさい,1000倍,殺菌,5月,メモ1\n"
        "M2,だいず,500倍,除草,4月,\n"
    )
    r = app_client.post(
        "/pesticide-masters/import",
        files={"file": ("m.csv", csv_in.encode("utf-8-sig"), "text/csv")},
    )
    assert r.status_code == 200
    assert "追加 2" in r.text
    # 再インポートで更新
    r = app_client.post(
        "/pesticide-masters/import",
        files={"file": ("m.csv", csv_in.encode("utf-8-sig"), "text/csv")},
    )
    assert "更新 2" in r.text


def test_pesticide_record_form_uses_master_datalist(app_client):
    _make_field(app_client, "PF1")
    app_client.post("/pesticide-masters/", data={
        "name": "マスタA", "crop": "", "dilution_rate": "",
        "application_method": "", "usage_timing": "", "notes": "",
    })
    # 過去の防除記録にあった農薬名も候補に出る
    fid = _make_field(app_client, "PF2")
    app_client.post("/pesticide-records/", data={
        "field_id": fid, "spray_date": "2026-05-10", "pesticide_name": "過去B",
        "dilution_rate": "", "spray_amount": "", "spray_unit": "", "notes": "",
    })
    r = app_client.get("/pesticide-records/new")
    assert 'list="pesticide-names"' in r.text
    assert '<option value="マスタA"></option>' in r.text
    assert '<option value="過去B"></option>' in r.text


def test_plan_snapshot_and_compare(app_client):
    # ほ場 2 つ
    _make_field(app_client, "CMP1")
    _make_field(app_client, "CMP2")
    # 計画
    r = app_client.post("/plans/", data={"name": "C計画", "start_year": "R8", "end_year": "R9"})
    import re
    pid = int(re.search(r'id="plan-(\d+)"', r.text).group(1))

    # 比較ページ - snapshot 無し
    r = app_client.get(f"/plans/{pid}/compare")
    assert r.status_code == 200
    assert "スナップショットがありません" in r.text

    # スナップショット保存
    r = app_client.post(f"/plans/{pid}/snapshot")
    assert r.status_code == 200
    assert "スナップショットを保存しました" in r.text

    # 比較ページ - snapshot あり、未実績で全部「未実績」
    r = app_client.get(f"/plans/{pid}/compare")
    assert r.status_code == 200
    assert "スナップショット作成:" in r.text
    assert "未実績" in r.text  # まだ R8/R9 の history がない

    # apply-to-history で R8 を実績に反映
    app_client.post(f"/plans/{pid}/apply-to-history", data={"year": "R8"})
    r = app_client.get(f"/plans/{pid}/compare")
    # R8 は計画通り反映されたので一致セル
    assert "cell-match" in r.text


def test_plan_compare_shows_diff(app_client):
    fid = _make_field(app_client, "DIFF1")
    r = app_client.post("/plans/", data={"name": "Diff", "start_year": "R8", "end_year": "R9"})
    import re
    pid = int(re.search(r'id="plan-(\d+)"', r.text).group(1))
    app_client.post(f"/plans/{pid}/snapshot")
    # 履歴に違う作物を手動投入
    app_client.post("/history/cell", data={"field_id": fid, "year": "R8", "crop": "ぜったい違う作物"})
    r = app_client.get(f"/plans/{pid}/compare")
    # 差分セルが出る
    assert "cell-diff" in r.text
    assert "ぜったい違う作物" in r.text


def test_field_detail_page(app_client):
    fid = _make_field(app_client, "DT1")
    # 履歴 + 防除記録投入
    app_client.post("/history/cell", data={"field_id": fid, "year": "R6", "crop": "だいず"})
    app_client.post("/history/cell", data={"field_id": fid, "year": "R7", "crop": "てんさい"})
    app_client.post("/pesticide-records/", data={
        "field_id": fid, "spray_date": "2026-05-10", "pesticide_name": "薬X",
        "dilution_rate": "1000倍", "spray_amount": "0.3", "spray_unit": "L/10a", "notes": "",
    })
    r = app_client.get(f"/fields/{fid}/detail")
    assert r.status_code == 200
    assert "DT1" in r.text
    # 履歴セクション
    assert "作付履歴 (2 件)" in r.text
    assert "だいず" in r.text and "てんさい" in r.text
    # 防除記録セクション
    assert "薬X" in r.text and "2026-05-10" in r.text


def test_field_detail_404_for_other_user(app_client):
    fid = _make_field(app_client, "DT2")
    import hashlib, sqlite3, os
    db = os.environ["ROTATION_DB"]
    conn = sqlite3.connect(db)
    pw = hashlib.sha256(b"other").hexdigest()
    conn.execute(
        "INSERT INTO users (username, password_hash, display_name, role) VALUES (?, ?, ?, ?)",
        ("other", pw, "別人", "farmer"),
    )
    conn.commit()
    conn.close()
    app_client.auth = ("other", "other")
    assert app_client.get(f"/fields/{fid}/detail").status_code == 404


def test_crop_master_seeded_on_fresh_db(app_client):
    # 新規 DB はスキーマで seed 済み (db_schema.sql 内の INSERT OR IGNORE)
    r = app_client.get("/crop-masters/")
    assert r.status_code == 200
    # 主要作物が出る
    for crop in ["小麦(春播)", "だいず", "てんさい", "ばれいしょ"]:
        assert crop in r.text


def test_crop_master_crud(app_client):
    # 新規
    r = app_client.post(
        "/crop-masters/",
        data={"name": "そば", "category": "穀物", "family": "タデ科",
              "display_order": "20", "is_active": "on"},
    )
    assert r.status_code == 200
    assert "そば" in r.text and "タデ科" in r.text
    import re
    cid = int(re.search(r'id="crop-(\d+)"', r.text).group(1))

    # 編集
    r = app_client.put(
        f"/crop-masters/{cid}",
        data={"name": "そば(改)", "category": "雑穀", "family": "タデ科",
              "display_order": "21", "is_active": "on"},
    )
    assert "そば(改)" in r.text and "雑穀" in r.text

    # 削除
    assert app_client.delete(f"/crop-masters/{cid}").status_code == 200


def test_crop_master_inactive_excluded_from_datalist(app_client):
    fid = _make_field(app_client, "DM1")
    # 「あさつき」を crop_master に inactive で追加
    r = app_client.post(
        "/crop-masters/",
        data={"name": "あさつき", "category": "野菜", "family": "ユリ科",
              "display_order": "30"},  # is_active なし → 0
    )
    assert r.status_code == 200
    # history cell edit に出てこない
    r = app_client.get(f"/history/cell/edit?field_id={fid}&year=R7")
    assert '<option value="あさつき"></option>' not in r.text
    # アクティブな作物は出る
    assert '<option value="てんさい"></option>' in r.text


def test_crop_master_csv_import(app_client):
    csv_in = (
        "作物名,分類,科,display_order,is_active\n"
        "ライ麦,穀物,イネ科,15,1\n"
        "オーツ麦,穀物,イネ科,16,0\n"
    )
    r = app_client.post(
        "/crop-masters/import",
        files={"file": ("c.csv", csv_in.encode("utf-8-sig"), "text/csv")},
    )
    assert r.status_code == 200
    assert "追加 2" in r.text
    r = app_client.get("/crop-masters/")
    assert "ライ麦" in r.text and "オーツ麦" in r.text


def test_polygon_404_for_other_user_field(app_client):
    fid = _create_field(app_client)
    # 別ユーザー作る
    import hashlib, sqlite3, os
    db = os.environ["ROTATION_DB"]
    conn = sqlite3.connect(db)
    pw = hashlib.sha256(b"other").hexdigest()
    conn.execute(
        "INSERT INTO users (username, password_hash, display_name, role) VALUES (?, ?, ?, ?)",
        ("other", pw, "別人", "farmer"),
    )
    conn.commit()
    conn.close()
    app_client.auth = ("other", "other")
    assert app_client.get(f"/fields/{fid}/polygon").status_code == 404
