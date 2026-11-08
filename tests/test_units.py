"""Проверки отдельных «узких мест» логики."""
from datetime import date

from app.calc import add_months
from app.matching import norm_fio, norm_snils


def test_norm_fio():
    assert norm_fio("КОВАЛЁВ  Пётр Ильич ") == norm_fio("Ковалев Петр Ильич")


def test_norm_snils():
    assert norm_snils("123-456-789 01") == "12345678901"


def test_add_months():
    assert add_months(date(2025, 11, 7), 12) == date(2026, 11, 7)
    assert add_months(date(2016, 11, 12), 120) == date(2026, 11, 12)
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
