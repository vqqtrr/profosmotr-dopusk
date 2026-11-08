"""
3. Справочник правил допуска.

Правила лежат в папке rules/ в обычных CSV-файлах (их можно править в Excel):
  exams.csv            14 обязательных обследований, коды услуг qMS, сроки действия;
  bad_conclusions.csv  фразы в заключении, при которых обследование не в норме;
  ok_results.csv       ответы анализов, которые считаются нормой;
  settings.csv         общие настройки (порог «скоро закончится»).
В коде расчета нет ни одного кода услуги и ни одного срока: все берется отсюда.
"""
import csv
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RULES_DIR = ROOT / "rules"


def _read(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter=";"))


def load_rules(con, rules_dir=None):
    """Перенести правила из CSV в таблицы rule_*."""
    d = Path(rules_dir or RULES_DIR)
    with con:
        for t in ("rule_exam", "rule_bad_conclusion", "rule_ok_result", "rule_setting"):
            con.execute(f"DELETE FROM {t}")
        for r in _read(d / "exams.csv"):
            con.execute("INSERT INTO rule_exam VALUES (?,?,?,?,?,?,?)", (
                r["id"], r["раздел"], r["название"], r["код_услуги"], r["вид"],
                int(r["срок_мес"]) if r["срок_мес"] else None, int(r["порядок"])))
        for r in _read(d / "bad_conclusions.csv"):
            con.execute("INSERT INTO rule_bad_conclusion VALUES (?,?,?,?)",
                        (r["код_услуги"], r["фраза"], r.get("подпись") or "не в норме",
                         r.get("причина") or r["фраза"]))
        for r in _read(d / "ok_results.csv"):
            con.execute("INSERT INTO rule_ok_result VALUES (?)", (r["ответ"].strip().lower(),))
        for r in _read(d / "settings.csv"):
            con.execute("INSERT INTO rule_setting VALUES (?,?)", (r["параметр"], r["значение"]))


@dataclass
class Rules:
    exams: list            # строки rule_exam по порядку колонок
    bad_phrases: dict      # код услуги -> [(фраза, подпись для ячейки, текст для причины)]
    ok_results: set        # нормальные ответы анализов
    soon_days: int         # порог «скоро закончится»


def get_rules(con):
    exams = [dict(r) for r in con.execute("SELECT * FROM rule_exam ORDER BY sort_order")]
    bad = {}
    for r in con.execute("SELECT * FROM rule_bad_conclusion"):
        bad.setdefault(r["service_code"], []).append((r["phrase"].lower(), r["label"], r["reason"]))
    ok = {r["value"] for r in con.execute("SELECT value FROM rule_ok_result")}
    settings = {r["key"]: r["value"] for r in con.execute("SELECT * FROM rule_setting")}
    return Rules(exams, bad, ok, int(settings.get("порог_скоро_дней", 30)))
