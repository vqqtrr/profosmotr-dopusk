"""
Приемочные тесты: 12 тестовых студентов группы ЛФ-301 (tests/acceptance_cases.csv).
Сценарии взяты из критериев приемки (Given / When / Then) и граничных случаев.
Запуск: python -m pytest -v
"""
import csv
from pathlib import Path

import pytest

from app.db import connect
from app.pipeline import run_all

HERE = Path(__file__).resolve().parent
CASES = list(csv.DictReader(open(HERE / "acceptance_cases.csv", encoding="utf-8"), delimiter=";"))


@pytest.fixture(scope="session")
def con(tmp_path_factory):
    db = tmp_path_factory.mktemp("db") / "test.db"     # отдельная база, рабочую не трогаем
    run_all(db_path=db, verbose=False)
    c = connect(db)
    yield c
    c.close()


def admission_of(con, fio):
    r = con.execute("""SELECT a.result, a.reason FROM admission a JOIN student s USING (student_id)
                       WHERE s.fio = ? AND s.group_name = 'ЛФ-301'""", (fio,)).fetchone()
    assert r, f"Студент {fio} не найден в витрине"
    return r["result"], r["reason"]


@pytest.mark.parametrize("case", CASES, ids=[c["ID_теста"] for c in CASES])
def test_acceptance(con, case):
    result, reason = admission_of(con, case["ФИО"])
    assert result == case["Ожидаемый_итог"], f"{case['Что_проверяем']}. Причина в системе: {reason}"
    if case["Причина_содержит"]:
        assert case["Причина_содержит"] in reason, f"В причине нет «{case['Причина_содержит']}»: {reason}"
    if case["Ожидаемый_итог"] == "Допуск":
        assert reason == "", f"У допущенного не должно быть причины: {reason}"


def test_yellow_does_not_block(con):
    """БП-2: «Скоро закончится» желтая ячейка, но итог Допуск (Кузнецова, ФЛГ 20 дн.)."""
    r = con.execute("""SELECT e.status, e.label, e.color FROM exam_status e JOIN student s USING (student_id)
                       WHERE s.fio = 'Кузнецова Елена Викторовна' AND e.exam_id = 'FLG'""").fetchone()
    assert (r["status"], r["label"], r["color"]) == ("Скоро закончится", "20 дн. осталось", "yellow")


def test_reload_has_no_duplicates(tmp_path):
    """Повторная загрузка не создает дублей."""
    db = tmp_path / "twice.db"
    first = run_all(db_path=db, verbose=False)
    second = run_all(db_path=db, verbose=False)
    c = connect(db)
    assert c.execute("SELECT COUNT(*) FROM src_usluga186").fetchone()[0] == first["counts"]["src_usluga186"]
    assert first["totals"] == second["totals"]
