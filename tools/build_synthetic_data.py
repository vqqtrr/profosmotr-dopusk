"""
Сборка синтетических выгрузок 1С и qMS для прототипа «Допуск к практике».

Основа: учебный набор (звезда fact_uslugi + dim_*), сделанный ранее по этому же кейсу.
Скрипт «разворачивает» его обратно в сырые таблицы по физической модели БД
(one_c_imo, obj_patient_wh, obj_episode_wh, obj_usluga186/293/294_wh, obj_analyz_wh,
ref_usluga, ref_analyz) и дописывает то, чего не хватало для требований FR-03/05/06:
  - уровень, факультет, курс, группа, дата рождения и СНИЛС в 1С;
  - прививки (АДСМ, корь, краснуха, гепатит B) - сведения из сертификата;
  - анализы на ВИЧ, гепатиты B и C, RW;
  - ФЛГ прошлого года (чтобы появились истекающие и просроченные сроки);
  - 12 тестовых студентов в группе ЛФ-301 (сценарии из ПР2 и граничные случаи).

Все люди и значения вымышленные. Дата среза: 18.10.2026 23:59.
Запуск: python3 tools/build_synthetic_data.py
"""
import csv
import hashlib
import json
import random
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "tools" / "base_clean_star.xlsx"
OUT_1C = ROOT / "data" / "source" / "1c"
OUT_QMS = ROOT / "data" / "source" / "qms"
SREZ = datetime(2026, 10, 18, 23, 59, 59)
SREZ_D = SREZ.date()
rnd = random.Random(2026)


def h(*parts):
    return hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()


def ts(d):
    return d.strftime("%Y-%m-%d %H:%M:%S") if d else ""


def ds(d):
    return d.strftime("%Y-%m-%d") if d else ""


def snils_digits():
    while True:
        nine = [rnd.randint(0, 9) for _ in range(9)]
        if nine[0] == 0:
            continue
        s = sum(d * (9 - i) for i, d in enumerate(nine))
        if s < 100:
            cs = s
        elif s in (100, 101):
            cs = 0
        else:
            cs = s % 101
            cs = 0 if cs == 100 else cs
        return "".join(map(str, nine)) + f"{cs:02d}"


def snils_fmt(d):
    return f"{d[0:3]}-{d[3:6]}-{d[6:9]} {d[9:11]}"


def dob_for_age(age):
    hi = date(SREZ_D.year - age, SREZ_D.month, SREZ_D.day)
    lo = date(SREZ_D.year - age - 1, SREZ_D.month, SREZ_D.day) + timedelta(days=1)
    return lo + timedelta(days=rnd.randint(0, (hi - lo).days))


def add_months(d, m):
    y, mo = divmod(d.month - 1 + m, 12)
    return date(d.year + y, mo + 1, min(d.day, 28 if mo + 1 == 2 else 30 if mo + 1 in (4, 6, 9, 11) else 31))


# ---------------------------------------------------------------- справочники
CODE = dict(TER="B01.047.001", SUR="B01.057.001", NEU="B01.023.001", OPH="B01.029.001",
            ENT="B01.028.001", DEN="B01.065.001", FLG="A06.09.006", ECG="A05.10.006",
            OAK="B03.016.003", OAM="B03.016.006", BIO="B03.016.004",
            HIV="A26.06.049", HBS="A26.06.036", HCV="A26.06.041", RW="A26.06.082",
            V_ADSM="ВАК.АДСМ", V_MEAS="ВАК.КОРЬ", V_RUB="ВАК.КРАСН", V_HEPB="ВАК.ГЕПB")
NEW_USLUGI = [
    (CODE["HIV"], "Исследование антител к ВИЧ-1/2 и антигена p24 в крови", "Лабораторная диагностика"),
    (CODE["HBS"], "Определение антигена (HBsAg) вируса гепатита B в крови", "Лабораторная диагностика"),
    (CODE["HCV"], "Определение антител к вирусу гепатита C в крови", "Лабораторная диагностика"),
    (CODE["RW"], "Определение антител к бледной трепонеме в крови (RW)", "Лабораторная диагностика"),
    (CODE["V_ADSM"], "Сведения о вакцинации: АДСМ (дифтерия, столбняк)", "Вакцинация"),
    (CODE["V_MEAS"], "Сведения о вакцинации: корь", "Вакцинация"),
    (CODE["V_RUB"], "Сведения о вакцинации: краснуха", "Вакцинация"),
    (CODE["V_HEPB"], "Сведения о вакцинации: гепатит B", "Вакцинация"),
]
INF_ANALYZ = {CODE["HIV"]: ("HIV_AGAB", "Антитела к ВИЧ-1/2 и антиген p24", "—"),
              CODE["HBS"]: ("HBSAG", "HBsAg (гепатит B)", "—"),
              CODE["HCV"]: ("HCV_AB", "Антитела к вирусу гепатита C", "—"),
              CODE["RW"]: ("TP_AB", "Антитела к бледной трепонеме (RW)", "—")}
NEG = {CODE["HIV"]: "не обнаружены", CODE["HBS"]: "отрицательно",
       CODE["HCV"]: "отрицательно", CODE["RW"]: "отрицательно"}
VACC = [CODE["V_ADSM"], CODE["V_MEAS"], CODE["V_RUB"], CODE["V_HEPB"]]
LAB_RESULT = {CODE["OAK"], CODE["OAM"], CODE["BIO"], CODE["HIV"], CODE["HBS"], CODE["HCV"], CODE["RW"]}
NORMAL_CONCL = {
    CODE["TER"]: "Годен без ограничений", CODE["SUR"]: "Патологии не выявлено",
    CODE["NEU"]: "Без неврологической патологии", CODE["OPH"]: "Острота зрения в норме",
    CODE["ENT"]: "ЛОР-патологии не выявлено", CODE["DEN"]: "Санация не требуется",
    CODE["FLG"]: "Очаговых и инфильтративных изменений нет",
    CODE["ECG"]: "Ритм синусовый, ЧСС 60-90, без патологии",
}

# ---------------------------------------------------------------- чтение основы
wb = openpyxl.load_workbook(BASE, read_only=True)


def sheet(name):
    rows = list(wb[name].iter_rows(values_only=True))
    hdr = rows[0]
    return [dict(zip(hdr, r)) for r in rows[1:] if r[0] is not None]


students = sheet("dim_student")
episodes = sheet("dim_episode")
fact = sheet("fact_uslugi")
detail = sheet("detail_analyzy")
ref_us = sheet("dim_usluga")

# ---------------------------------------------------------------- таблицы-результаты
one_c, patients, eps, u186, u293, u294, analyz = [], [], [], [], [], [], []
person = {}          # ID_студента -> dict(fio, dob, snils, in1c, inqms, pat_hash)


def add_status(u_hash, status, when, data_rows=(), analyses=()):
    s_hash = h("st", u_hash, status, when)
    u293.append(dict(Услуга293_хэш=s_hash, Услуга186_хэш=u_hash, Статус=status, Дата_статуса=ts(when)))
    for field, val in data_rows:
        u294.append(dict(Услуга294_хэш=h("d", s_hash, field), Услуга293_хэш=s_hash, Статус=field, Данные=val))
    for code, val in analyses:
        analyz.append(dict(Анализ_хэш=h("a", s_hash, code), Услуга293_хэш=s_hash, Код_анализа=code, Значение_анализа=val))
    return s_hash


def add_usluga(ep_hash, code, assigned, done=None, result_at=None, cancelled=None,
               concl=None, complaints=None, analyses=(), extra_rows=(), key=None):
    """Одна назначенная услуга + история статусов. Ничего после среза не пишется."""
    u_hash = key or h("u", ep_hash, code, assigned)
    if done and done > SREZ:
        done = None
    if result_at and (not done or result_at > SREZ):
        result_at = None
    u186.append(dict(Услуга186_хэш=u_hash, Эпизод_хэш=ep_hash, Код_услуги=code,
                     Дата_назначения=ts(assigned), Дата_выполнения=ts(done)))
    add_status(u_hash, "Назначена", assigned)
    if cancelled:
        add_status(u_hash, "Отменена", cancelled)
        return u_hash
    if done:
        rows = list(extra_rows)
        if concl:
            rows.append(("Заключение", concl))
        if complaints:
            rows.append(("Жалобы", complaints))
        add_status(u_hash, "Выполнена", done, rows)
        if result_at:
            add_status(u_hash, "Результат готов", result_at, analyses=analyses)
    return u_hash


def add_episode(pid, number, opened, closed=None):
    e_hash = h("ep", number)
    eps.append(dict(Эпизод_хэш=e_hash, Пациент_хэш=person[pid]["pat"], Номер_эпизода=number,
                    Дата_открытия=ds(opened), Дата_закрытия=ds(closed) if closed and closed <= SREZ_D else ""))
    return e_hash


# ---------------------------------------------------------------- 1. люди и контингент
GROUPS = {  # возраст -> (уровень, курс, варианты групп (факультет, группа))
    18: ("СПО", 2, [("Медицинский колледж", "СД-21")]),
    19: ("СПО", 3, [("Медицинский колледж", "СД-31")]),
    20: ("Специалитет", 2, [("Лечебный факультет", "ЛФ-201"), ("Педиатрический факультет", "ПФ-201")]),
    21: ("Специалитет", 3, [("Лечебный факультет", "ЛФ-301"), ("Педиатрический факультет", "ПФ-301")]),
    22: ("Специалитет", 4, [("Лечебный факультет", "ЛФ-401"), ("Педиатрический факультет", "ПФ-401")]),
    23: ("Специалитет", 5, [("Лечебный факультет", "ЛФ-501"), ("Педиатрический факультет", "ПФ-501")]),
    24: ("Ординатура", 1, [("Институт медицинского образования", "ОРД-101")]),
}
counter_by_age = defaultdict(int)
for s in students:
    sid = s["ID_студента"]
    p = dict(fio=s["ФИО"], dob=dob_for_age(s["Возраст_на_срез"]), snils=snils_digits(),
             in1c=s["В_контингенте_1С"] == "Да", inqms=s["Есть_в_qMS"] == "Да",
             reg=s["Рег_номер_qMS"], pat=h("pat", sid))
    person[sid] = p
    if p["in1c"]:
        lvl, kurs, opts = GROUPS[s["Возраст_на_срез"]]
        # группа ЛФ-301 оставляем поменьше: в нее добавятся 12 тестовых студентов
        i = counter_by_age[s["Возраст_на_срез"]]
        counter_by_age[s["Возраст_на_срез"]] += 1
        fac, grp = opts[i % len(opts)]
        if grp == "ЛФ-301" and i % 4 == 0:
            fac, grp = "Педиатрический факультет", "ПФ-301"
        p.update(level=lvl, kurs=kurs, fac=fac, grp=grp)

# ---------------------------------------------------------------- 2. qMS из звезды
ep_hash_by_num, ep_by_num = {}, {}
for e in episodes:
    ep_by_num[e["Номер_эпизода"]] = e
    closed = e["Дата_закрытия_на_срез"]
    ep_hash_by_num[e["Номер_эпизода"]] = add_episode(
        e["ID_студента"], e["Номер_эпизода"], e["Дата_открытия"].date(), closed.date() if closed else None)

detail_by_u = defaultdict(list)
for d in detail:
    detail_by_u[d["ID_назначения"]].append((d["Код_анализа"], d["Значение"]))

oak_by_student = {}
for f in fact:
    st = f["Статус_на_срез"]
    assigned = f["Дата_назначения"]
    done = f["Дата_выполнения_на_срез"] if st != "Назначена, не выполнена" else None
    res = None
    if st == "Результат готов":
        res = done + timedelta(hours=f["Ожидание_результата_ч"] or 24)
        res = min(res, SREZ)
    cancel = min(assigned + timedelta(days=1), SREZ) if st == "Отменена" else None
    add_usluga(ep_hash_by_num[f["Номер_эпизода"]], f["Код_услуги"], assigned, done, res, cancel,
               concl=f["Заключение"], complaints=f["Жалобы"],
               analyses=detail_by_u.get(f["ID_назначения"], []), key=f["ID_назначения"])
    if f["Код_услуги"] == CODE["OAK"] and f["ID_студента"] not in oak_by_student and st != "Отменена":
        oak_by_student[f["ID_студента"]] = (f, done, res)

# ---------------------------------------------------------------- 3. дописываем недостающее
main_ep = {}
for e in episodes:
    if e["Тип_эпизода"] == "Основной":
        main_ep[e["ID_студента"]] = e
flg_done_this_year = {f["ID_студента"] for f in fact
                      if f["Код_услуги"] == CODE["FLG"] and f["Статус_на_срез"] in ("Выполнена", "Результат готов")}

# 3.0 у «завершивших» (основной эпизод закрыт) в исходном наборе были назначены не все осмотры.
#     Дописываем недостающие обязательные осмотры и ФЛГ внутри срока эпизода, с нормальным заключением.
codes_by_student = defaultdict(set)
for f in fact:
    codes_by_student[f["ID_студента"]].add(f["Код_услуги"])
filled = 0
for sid, e in main_ep.items():
    closed = e["Дата_закрытия_на_срез"]
    if not closed:
        continue
    opened = e["Дата_открытия"]
    span = max((closed - opened).days, 1)
    for code in [CODE["TER"], CODE["SUR"], CODE["NEU"], CODE["ENT"], CODE["DEN"], CODE["FLG"], CODE["OAK"]]:
        if code in codes_by_student[sid]:
            continue
        t = opened + timedelta(days=rnd.randint(0, span - 1), hours=9, minutes=rnd.randint(0, 400))
        if code == CODE["OAK"]:
            res = t + timedelta(hours=6)
            add_usluga(ep_hash_by_num[e["Номер_эпизода"]], code, t, t + timedelta(minutes=15), res,
                       analyses=[("HGB", rnd.randint(120, 150)), ("WBC", round(rnd.uniform(4.5, 8.5), 1))])
            oak_by_student[sid] = (dict(Номер_эпизода=e["Номер_эпизода"], Дата_назначения=t), t + timedelta(minutes=15), res)
        else:
            add_usluga(ep_hash_by_num[e["Номер_эпизода"]], code, t, t + timedelta(hours=1), concl=NORMAL_CONCL[code])
            if code == CODE["FLG"]:
                flg_done_this_year.add(sid)
        filled += 1
print("Дописано осмотров у завершивших:", filled)

# 3.1 анализы на инфекции - берутся вместе с ОАК (одна венепункция)
rw_doubtful = 0
for sid, (f, done, res) in sorted(oak_by_student.items()):
    ep = ep_hash_by_num[f["Номер_эпизода"]]
    for k, code in enumerate([CODE["HIV"], CODE["HBS"], CODE["HCV"], CODE["RW"]]):
        assigned = f["Дата_назначения"] + timedelta(minutes=2 + k)
        r = res + timedelta(hours=18) if res else None   # инфекции готовятся дольше ОАК
        val = NEG[code]
        if code == CODE["RW"] and r and rnd.random() < 0.02:
            val = "сомнительно"
            rw_doubtful += 1
        add_usluga(ep, code, assigned, done, r, analyses=[(INF_ANALYZ[code][0], val)] if r else ())

# 3.2 прививки - сведения из сертификата вносятся при первом визите
vacc_plan = {}
for sid, e in sorted(main_ep.items()):
    roll = rnd.random()
    if roll < 0.06:
        continue                      # сертификат еще не принес
    missing = rnd.choice([CODE["V_MEAS"], CODE["V_RUB"], CODE["V_HEPB"]]) if roll < 0.13 else None
    adsm = date(rnd.randint(2017, 2024), rnd.randint(1, 12), rnd.randint(1, 28))
    vacc_plan[sid] = (e, missing, adsm)
# несколько АДСМ с истекающим и истекшим сроком (10 лет)
some = rnd.sample(sorted(vacc_plan), 6)
for i, sid in enumerate(some):
    e, missing, _ = vacc_plan[sid]
    adsm = date(2016, 11, rnd.randint(1, 15)) if i < 3 else date(2016, rnd.randint(3, 9), rnd.randint(1, 28))
    vacc_plan[sid] = (e, None, adsm)


def add_vaccinations(ep_hash, opened, adsm, missing=None, others=None):
    for k, code in enumerate(VACC):
        if code == missing:
            continue
        vd = adsm if code == CODE["V_ADSM"] else (others or {}).get(code, date(rnd.randint(2004, 2012), rnd.randint(1, 12), rnd.randint(1, 28)))
        when = datetime.combine(opened, datetime.min.time()) + timedelta(hours=9, minutes=5 + k)
        add_usluga(ep_hash, code, when, when, extra_rows=[
            ("Дата вакцинации", vd.strftime("%d.%m.%Y")),
            ("Документ", "Сертификат о профилактических прививках (скан прикреплен)")])


for sid, (e, missing, adsm) in vacc_plan.items():
    add_vaccinations(ep_hash_by_num[e["Номер_эпизода"]], e["Дата_открытия"].date(), adsm, missing)

# 3.3 ФЛГ прошлого года (делали вне кампании)
ep_seq = 1
for sid, p in sorted(person.items()):
    if not p["inqms"]:
        continue
    chance = 0.75 if sid not in flg_done_this_year else 0.3
    if rnd.random() < chance:
        d = date(2025, 9, 1) + timedelta(days=rnd.randint(0, 105))
        t = datetime.combine(d, datetime.min.time()) + timedelta(hours=10, minutes=rnd.randint(0, 300))
        eh = add_episode(sid, f"Э-2025-{ep_seq:06d}", d, d)
        ep_seq += 1
        add_usluga(eh, CODE["FLG"], t, t + timedelta(minutes=20), concl=NORMAL_CONCL[CODE["FLG"]])

# 3.4 одна ФЛГ с изменениями, требующими дообследования у фтизиатра
cand = sorted(s for s in flg_done_this_year if s in main_ep)
bad_flg_sid = rnd.choice(cand)
for u in u186:
    if u["Код_услуги"] == CODE["FLG"] and u["Эпизод_хэш"] == ep_hash_by_num[main_ep[bad_flg_sid]["Номер_эпизода"]]:
        st = [s for s in u293 if s["Услуга186_хэш"] == u["Услуга186_хэш"] and s["Статус"] == "Выполнена"][0]
        for r in u294:
            if r["Услуга293_хэш"] == st["Услуга293_хэш"] and r["Статус"] == "Заключение":
                r["Данные"] = "Очаговые изменения в верхней доле правого легкого, направлен к фтизиатру"

# ---------------------------------------------------------------- 4. тестовые студенты (группа ЛФ-301)
TESTS = [
    # id, ФИО в 1С, ФИО в qMS (None = нет в qMS), сценарий, ожидаемый итог, что проверяем
    ("T01", "Иванов Илья Игоревич", "same", "all_ok", "Допуск", "Все 14 обследований в норме", "FR-05, БП-1"),
    ("T02", "Петрова Анна Андреевна", "same", "no_hiv", "Недопуск", "Анализ на ВИЧ не назначен: «Нет данных»", "FR-06, БП-1"),
    ("T03", "Сидоров Павел Петрович", None, "no_qms", "Недопуск", "Студента нет в qMS: «Нет данных qMS»", "FR-03, FR-06"),
    ("T04", "Кузнецова Елена Викторовна", "same", "flg_20d", "Допуск", "ФЛГ 07.11.2025, до конца срока 20 дн.: «Скоро закончится», итог не меняется", "FR-07, БП-2"),
    ("T05", "Орлов Дмитрий Сергеевич", "same", "flg_overdue10", "Недопуск", "ФЛГ 08.10.2025, просрочено на 10 дн.", "FR-08, FR-06"),
    ("T06", "Смирнова Мария Олеговна", "same", "adsm_25d", "Допуск", "АДСМ 12.11.2016 (срок 10 лет), осталось 25 дн.: «Скоро закончится»", "FR-07, БП-2"),
    ("T07", "Волков Артем Андреевич", "same", "rw_retest_ok", "Допуск", "RW сначала «сомнительно», пересдача «отрицательно»: считается последний результат", "БП-1"),
    ("T08", "Федорова Дарья Ильинична", "same", "rw_pending", "Недопуск", "Кровь на RW взята, результата еще нет", "FR-06, БП-1"),
    ("T09", "Белов Никита Романович", "same", "ter_dooobsl", "Недопуск", "Терапевт: «направлен на дообследование»", "FR-06, БП-1"),
    ("T10", "Морозова Анна Игоревна", "snils_typo", "partial", "Недопуск", "В qMS СНИЛС с опечаткой: совпали только ФИО и дата рождения, запись не связывается", "FR-03"),
    ("T11", "Ковалев Петр Ильич", "Ковалёв Пётр Ильич", "all_ok", "Допуск", "В qMS ФИО через «ё»: должна сработать нормализация ё/е", "FR-03, сопоставление"),
    ("T12", "Лебедев Глеб Андреевич", "same", "flg_30d", "Допуск", "ФЛГ 17.11.2025, осталось ровно 30 дн. (граница правила ≤ 30)", "FR-07, БП-2"),
]
test_rows = []
REASON = {"T02": "ВИЧ", "T03": "Нет данных qMS", "T05": "ФЛГ", "T08": "RW", "T09": "дообследование", "T10": "частичное совпадение"}
for i, (tid, fio, qfio, scen, exp, what, req) in enumerate(TESTS):
    sid = f"S{176 + i}"
    p = dict(fio=fio, dob=dob_for_age(21), snils=snils_digits(), in1c=True, inqms=qfio is not None,
             reg=f"МП-2026-{900 + i:06d}", pat=h("pat", sid), level="Специалитет", kurs=3,
             fac="Лечебный факультет", grp="ЛФ-301")
    person[sid] = p
    test_rows.append(dict(ID_теста=tid, ID_студента=sid, ФИО=fio, Группа="ЛФ-301", Причина_содержит=REASON.get(tid, ""),
                          Что_проверяем=what, Требование=req, Ожидаемый_итог=exp))
    if not p["inqms"]:
        continue
    p["qfio"] = fio if qfio in ("same", "snils_typo") else qfio
    if qfio == "snils_typo":
        d = list(p["snils"])
        d[4] = str((int(d[4]) + 3) % 10)
        p["qsnils"] = "".join(d)
    opened = date(2026, 9, 14) + timedelta(days=i)
    closed = opened + timedelta(days=9) if exp == "Допуск" else None
    num = f"Э-2026-{900 + i:06d}"
    eh = add_episode(sid, num, opened, closed)
    t0 = datetime.combine(opened, datetime.min.time()) + timedelta(hours=8, minutes=30)

    def doc(code, day, concl=None):
        t = t0 + timedelta(days=day, hours=2)
        add_usluga(eh, code, t0 + timedelta(minutes=day), t, concl=concl or NORMAL_CONCL.get(code))

    for day, code in enumerate([CODE["SUR"], CODE["NEU"], CODE["OPH"], CODE["ENT"], CODE["DEN"], CODE["ECG"]]):
        doc(code, day + 1)
    if scen not in ("flg_20d", "flg_overdue10", "flg_30d"):
        doc(CODE["FLG"], 1)
    doc(CODE["TER"], 8, "Выявлены отклонения, направлен на дообследование" if scen == "ter_dooobsl" else None)
    # кровь: ОАК + инфекции
    blood = t0 + timedelta(days=1, minutes=10)
    add_usluga(eh, CODE["OAK"], t0, blood, blood + timedelta(hours=6),
               analyses=[("HGB", 135), ("WBC", 6.1), ("RBC", 4.6), ("PLT", 250), ("ESR", 6)])
    for k, code in enumerate([CODE["HIV"], CODE["HBS"], CODE["HCV"], CODE["RW"]]):
        if scen == "no_hiv" and code == CODE["HIV"]:
            continue
        val = NEG[code]
        res = blood + timedelta(hours=30)
        if code == CODE["RW"] and scen == "rw_retest_ok":
            val = "сомнительно"
        if code == CODE["RW"] and scen == "rw_pending":
            blood_rw = datetime(2026, 10, 17, 9, 15)
            add_usluga(eh, code, blood_rw - timedelta(minutes=5), blood_rw, None)
            continue
        add_usluga(eh, code, t0 + timedelta(minutes=k + 1), blood, res, analyses=[(INF_ANALYZ[code][0], val)])
    if scen == "rw_retest_ok":
        rnum = f"Э-2026-{950 + i:06d}"
        r_open = opened + timedelta(days=12)
        reh = add_episode(sid, rnum, r_open, r_open + timedelta(days=2))
        rt = datetime.combine(r_open, datetime.min.time()) + timedelta(hours=8, minutes=40)
        add_usluga(reh, CODE["RW"], rt, rt + timedelta(minutes=10), rt + timedelta(days=1, hours=3),
                   analyses=[(INF_ANALYZ[CODE["RW"]][0], "отрицательно")])
    # прививки
    adsm = date(2016, 11, 12) if scen == "adsm_25d" else date(2019, 5, 20)
    add_vaccinations(eh, opened, adsm, others={CODE["V_MEAS"]: date(2006, 4, 10), CODE["V_RUB"]: date(2006, 4, 10),
                                               CODE["V_HEPB"]: date(2005, 9, 1)})
    # ФЛГ прошлого года для сценариев со сроком
    flg_old = {"flg_20d": date(2025, 11, 7), "flg_overdue10": date(2025, 10, 8), "flg_30d": date(2025, 11, 17)}.get(scen)
    if flg_old:
        oeh = add_episode(sid, f"Э-2025-{900 + i:06d}", flg_old, flg_old)
        ot = datetime.combine(flg_old, datetime.min.time()) + timedelta(hours=11)
        add_usluga(oeh, CODE["FLG"], ot, ot + timedelta(minutes=15), concl=NORMAL_CONCL[CODE["FLG"]])

# ---------------------------------------------------------------- 5. «грязь» реальных выгрузок
dirty = rnd.sample(sorted(s for s, p in person.items() if p["in1c"] and p["inqms"] and not s >= "S176"), 4)
for sid in dirty:
    p = person[sid]
    p["qfio"] = p["fio"].upper() if dirty.index(sid) < 2 else p["fio"].replace(" ", "  ", 1)

# ---------------------------------------------------------------- 6. запись выгрузок
for sid, p in person.items():
    if p["in1c"]:
        one_c.append(dict(ФИО=p["fio"], Дата_рождения=ds(p["dob"]), СНИЛС=snils_fmt(p["snils"]),
                          Уровень_образования=p["level"], Факультет=p["fac"], Курс=p["kurs"], Группа=p["grp"]))
    if p["inqms"]:
        patients.append(dict(Пациент_хэш=p["pat"], Регистрационный_номер=p["reg"], ФИО=p.get("qfio", p["fio"]),
                             Дата_рождения=ds(p["dob"]), СНИЛС=p.get("qsnils", p["snils"])))

ref_usluga = [dict(Код_услуги=r["Код_услуги"], Наименование=r["Наименование"], Тип_услуги=r["Тип_услуги"]) for r in ref_us]
ref_usluga += [dict(Код_услуги=c, Наименование=n, Тип_услуги=t) for c, n, t in NEW_USLUGI]
units = {}
for d in detail:
    units[d["Код_анализа"]] = (d["Название_анализа"], d["Единица_измерения"])
for code, (ac, an, un) in INF_ANALYZ.items():
    units[ac] = (an, un)
ref_analyz = [dict(Код_анализа=k, Название_анализа=v[0], Единица_измерения=v[1]) for k, v in units.items()]

rnd.shuffle(one_c)   # в 1С порядок не совпадает с qMS


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()), delimiter=";")
        w.writeheader()
        w.writerows(rows)


write(OUT_1C / "one_c_imo.csv", one_c)
for name, rows in [("obj_patient_wh", patients), ("obj_episode_wh", eps), ("obj_usluga186_wh", u186),
                   ("obj_usluga293_wh", u293), ("obj_usluga294_wh", u294), ("obj_analyz_wh", analyz),
                   ("ref_usluga", ref_usluga), ("ref_analyz", ref_analyz)]:
    write(OUT_QMS / f"{name}.csv", rows)
write(ROOT / "tests" / "acceptance_cases.csv", test_rows)
(ROOT / "data" / "source" / "export_meta.json").write_text(json.dumps(
    {"Дата_выгрузки": ts(SREZ), "Источник": "синтетические учебные данные, люди вымышленные"},
    ensure_ascii=False, indent=2), encoding="utf-8")

print("1С:", len(one_c), "| пациентов qMS:", len(patients), "| эпизодов:", len(eps),
      "| услуг:", len(u186), "| статусов:", len(u293), "| данных статусов:", len(u294),
      "| значений анализов:", len(analyz), "| RW сомнительно (фон):", rw_doubtful,
      "| ФЛГ с очагами:", bad_flg_sid, "| грязные ФИО:", dirty)
