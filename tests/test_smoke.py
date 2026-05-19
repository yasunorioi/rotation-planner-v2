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
