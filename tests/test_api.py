"""Проверки сервера: то, что получает экран методиста."""
import pytest
from fastapi.testclient import TestClient

import app.api as api
from app.db import connect
from app.pipeline import run_all


@pytest.fixture(scope="module")
def client(tmp_path_factory, monkeypatch_module=None):
    db = tmp_path_factory.mktemp("apidb") / "api.db"
    run_all(db_path=db, verbose=False)
    original = api.db
    api.db = lambda: connect(db)          # сервер читает тестовую базу
    yield TestClient(api.app)
    api.db = original


def test_levels_in_natural_order(client):
    levels = [t["level"] for t in client.get("/api/filters").json()]
    assert levels == ["СПО", "Специалитет", "Ординатура"]


def test_group_table(client):
    g = client.get("/api/group/ЛФ-301").json()
    assert len(g["exams"]) == 14
    assert g["summary"]["admitted"] + g["summary"]["not_admitted"] == g["summary"]["total"]
    by_fio = {s["fio"]: s for s in g["students"]}
    assert by_fio["Сидоров Павел Петрович"]["match_type"] == "не найден"          # FR-03
    assert by_fio["Морозова Анна Игоревна"]["match_type"] == "частичное"
    assert "СНИЛС" in by_fio["Морозова Анна Игоревна"]["match_note"]


def test_cell_shows_source(client):
    g = client.get("/api/group/ЛФ-301").json()
    sid = next(s["id"] for s in g["students"] if s["fio"] == "Орлов Дмитрий Сергеевич")
    c = client.get(f"/api/cell/{sid}/FLG").json()
    assert c["status"] == "Просрочено" and "08.10.2025" in c["source_date"]


def test_unknown_group(client):
    assert client.get("/api/group/НЕТ-ТАКОЙ").status_code == 404
