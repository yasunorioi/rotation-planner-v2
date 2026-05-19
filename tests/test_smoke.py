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
