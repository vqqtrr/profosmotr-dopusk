"""
Контрольный расчет по сырым выгрузкам (независимо от будущего сервиса).
Нужен, чтобы убедиться, что синтетика устроена правильно, и потом сверять с ним сервис.
"""
import csv
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SREZ = date(2026, 10, 18)


def read(p):
    with open(p, encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter=";"))


q = lambda n: read(ROOT / "data/source/qms" / f"{n}.csv")
one_c = read(ROOT / "data/source/1c/one_c_imo.csv")
pat, ep, u186, u293, u294, an, ref = (q(n) for n in ["obj_patient_wh", "obj_episode_wh", "obj_usluga186_wh",
                                                    "obj_usluga293_wh", "obj_usluga294_wh", "obj_analyz_wh", "ref_usluga"])

# ---------- целостность ключей
errs = []
ep_ids = {e["Эпизод_хэш"] for e in ep}
pat_ids = {p["Пациент_хэш"] for p in pat}
u_ids = {u["Услуга186_хэш"] for u in u186}
s_ids = {s["Услуга293_хэш"] for s in u293}
codes = {r["Код_услуги"] for r in ref}
errs += [f"эпизод без пациента {e['Номер_эпизода']}" for e in ep if e["Пациент_хэш"] not in pat_ids]
errs += ["услуга без эпизода" for u in u186 if u["Эпизод_хэш"] not in ep_ids]
errs += [f"код нет в справочнике {u['Код_услуги']}" for u in u186 if u["Код_услуги"] not in codes]
errs += ["статус без услуги" for s in u293 if s["Услуга186_хэш"] not in u_ids]
errs += ["данные без статуса" for d in u294 if d["Услуга293_хэш"] not in s_ids]
errs += ["анализ без статуса" for a in an if a["Услуга293_хэш"] not in s_ids]
errs += ["событие после среза" for s in u293 if s["Дата_статуса"] > "2026-10-18 23:59:59"]
for k in ["Пациент_хэш"]:
    if len({p[k] for p in pat}) != len(pat):
        errs.append("дубли пациентов")
print("Целостность:", "OK" if not errs else Counter(errs).most_common(5))

# ---------- сопоставление 1С ↔ qMS
norm_fio = lambda s: re.sub(r"\s+", " ", s.strip().lower().replace("ё", "е"))
digits = lambda s: re.sub(r"\D", "", s)
by_key = {(norm_fio(p["ФИО"]), p["Дата_рождения"], digits(p["СНИЛС"])): p for p in pat}
match, partial = {}, {}
for s in one_c:
    k = (norm_fio(s["ФИО"]), s["Дата_рождения"], digits(s["СНИЛС"]))
    if k in by_key:
        match[digits(s["СНИЛС"])] = by_key[k]
    else:
        for p in pat:
            pk = (norm_fio(p["ФИО"]), p["Дата_рождения"], digits(p["СНИЛС"]))
            if sum(a == b for a, b in zip(k, pk)) == 2:
                partial[digits(s["СНИЛС"])] = p
print(f"Сопоставление: совпали {len(match)}, нет в qMS {len(one_c) - len(match)} (из них частичных {len(partial)}),"
      f" вне контингента {len(pat) - len(match)}")

# ---------- расчет статусов
eps_by_pat = defaultdict(list)
for e in ep:
    eps_by_pat[e["Пациент_хэш"]].append(e["Эпизод_хэш"])
u_by_ep = defaultdict(list)
for u in u186:
    u_by_ep[u["Эпизод_хэш"]].append(u)
st_by_u = defaultdict(list)
for s in u293:
    st_by_u[s["Услуга186_хэш"]].append(s)
data_by_st = defaultdict(dict)
for d in u294:
    data_by_st[d["Услуга293_хэш"]][d["Статус"]] = d["Данные"]
an_by_st = defaultdict(list)
for a in an:
    an_by_st[a["Услуга293_хэш"]].append(a)

REQ = {  # 14 обязательных обследований
    "ФЛГ": "A06.09.006", "АДСМ": "ВАК.АДСМ", "Корь": "ВАК.КОРЬ", "Краснуха": "ВАК.КРАСН", "Гепатит B (прив.)": "ВАК.ГЕПB",
    "ВИЧ": "A26.06.049", "HBsAg": "A26.06.036", "HCV": "A26.06.041", "RW": "A26.06.082",
    "Терапевт": "B01.047.001", "Хирург": "B01.057.001", "Невролог": "B01.023.001", "ЛОР": "B01.028.001",
    "Стоматолог": "B01.065.001"}
OK_VALUES = {"отрицательно", "не обнаружены"}


def add_years(d, y):
    try:
        return d.replace(year=d.year + y)
    except ValueError:
        return d.replace(year=d.year + y, day=28)


def item_status(name, code, services):
    srv = [u for u in services if u["Код_услуги"] == code]
    if not srv:
        return "Нет данных"
    events = []
    for u in srv:
        sts = {s["Статус"]: s for s in st_by_u[u["Услуга186_хэш"]]}
        if "Отменена" in sts:
            continue
        if code.startswith("A26"):
            if "Результат готов" in sts:
                s = sts["Результат готов"]
                events.append((s["Дата_статуса"], "res", an_by_st[s["Услуга293_хэш"]][0]["Значение_анализа"]))
            elif "Выполнена" in sts:
                events.append((sts["Выполнена"]["Дата_статуса"], "wait", None))
        elif "Выполнена" in sts:
            s = sts["Выполнена"]
            dd = data_by_st[s["Услуга293_хэш"]]
            when = s["Дата_статуса"]
            if code == "ВАК.АДСМ" or code.startswith("ВАК"):
                when = datetime.strptime(dd["Дата вакцинации"], "%d.%m.%Y").strftime("%Y-%m-%d")
            events.append((when, "done", dd.get("Заключение", "")))
    if not events:
        # все назначения отменены: обследование не в работе
        return "Нет данных" if all("Отменена" in {x["Статус"] for x in st_by_u[u["Услуга186_хэш"]]} for u in srv) else "Назначено, не выполнено"
    when, kind, val = max(events)
    if kind == "wait":
        return "Ожидает результата"
    if kind == "res":
        return "Норма" if val in OK_VALUES else f"Не норма ({val})"
    if code == "B01.047.001" and "дообследование" in val:
        return "Не норма (дообследование)"
    if code == "A06.09.006" and "фтизиатр" in val:
        return "Не норма (к фтизиатру)"
    term = {"A06.09.006": 1, "ВАК.АДСМ": 10}.get(code)
    if term:
        exp = add_years(datetime.strptime(when[:10], "%Y-%m-%d").date(), term)
        left = (exp - SREZ).days
        if left < 0:
            return f"Просрочено {-left} дн."
        if left <= 30:
            return f"Скоро закончится ({left} дн.)"
    return "Норма"


results = {}
for s in one_c:
    p = match.get(digits(s["СНИЛС"]))
    if not p:
        results[digits(s["СНИЛС"])] = ("Недопуск", {"_": "Нет данных qMS"}, s["Группа"])
        continue
    services = [u for e in eps_by_pat[p["Пациент_хэш"]] for u in u_by_ep[e]]
    items = {n: item_status(n, c, services) for n, c in REQ.items()}
    ok = all(v == "Норма" or v.startswith("Скоро") for v in items.values())
    results[digits(s["СНИЛС"])] = ("Допуск" if ok else "Недопуск", items, s["Группа"])

print("Итог по всем:", Counter(r[0] for r in results.values()))
print("По группам:", sorted(Counter((r[2], r[0]) for r in results.values()).items()))
reasons = Counter()
for r in results.values():
    for k, v in r[1].items():
        if v != "Норма":
            reasons[(k, re.sub(r"\d+ дн\.", "n дн.", v))] += 1
print("Что не в норме (всего):", reasons.most_common(25))

# ---------- тест-кейсы
fails = 0
snils_by_fio = {s["ФИО"]: digits(s["СНИЛС"]) for s in one_c}
for t in read(ROOT / "tests/acceptance_cases.csv"):
    got, items, _ = results[snils_by_fio[t["ФИО"]]]
    bad = {k: v for k, v in items.items() if v != "Норма"}
    flag = "OK " if got == t["Ожидаемый_итог"] else "ОШИБКА"
    fails += got != t["Ожидаемый_итог"]
    print(f"{flag} {t['ID_теста']} {t['ФИО']:<28} ожид. {t['Ожидаемый_итог']:<8} получ. {got:<8} {bad}")
sys.exit(1 if fails or errs else 0)
