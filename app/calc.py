"""
4. Расчет статусов обследований и итога допуска (FR-03, FR-05, FR-06, БП-1, БП-2).

Для каждого студента:
  1) берем все услуги qMS по всем эпизодам его пациента;
  2) для каждого из 14 обязательных обследований находим последнее событие и ставим статус;
  3) итог «Допуск», если все 14 в норме или «Скоро закончится», иначе «Недопуск»;
  4) причину собираем из всех статусов, которые не в норме.
Результат пишется в витрину (exam_status, admission), экран только читает из нее.
"""
from collections import defaultdict
from datetime import date, datetime

from .rules import get_rules

# статус -> (цвет ячейки, считается ли нормой для итога)
STATUS_STYLE = {
    "Норма": ("green", True),
    "Скоро закончится": ("yellow", True),
    "Просрочено": ("red", False),
    "Не в норме": ("red", False),
    "Ждёт результата": ("grey", False),
    "Назначено, не выполнено": ("grey", False),
    "Нет данных": ("grey", False),
    "Нет данных qMS": ("grey", False),
}


def add_months(d, months):
    """Прибавить месяцы к дате (31 января + 1 мес. = 28/29 февраля)."""
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue


def parse_date(s):
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def load_qms(con):
    """Загрузить нужные данные qMS в память одним проходом (их немного, так быстрее)."""
    episodes = defaultdict(list)                     # пациент -> [эпизоды]
    for r in con.execute("SELECT * FROM src_episode"):
        episodes[r["patient_hash"]].append(dict(r))
    services = defaultdict(list)                     # эпизод -> [услуги]
    for r in con.execute("SELECT * FROM src_usluga186"):
        services[r["episode_hash"]].append(dict(r))
    statuses = defaultdict(dict)                     # услуга -> {статус: строка}
    for r in con.execute("SELECT * FROM src_usluga293"):
        statuses[r["usluga_hash"]][r["status"]] = dict(r)
    data = defaultdict(dict)                         # статус -> {поле: значение}
    for r in con.execute("SELECT * FROM src_usluga294"):
        data[r["status_hash"]][r["field"]] = r["value"]
    analyses = defaultdict(list)                     # статус -> [значения анализа]
    for r in con.execute("SELECT * FROM src_analyz"):
        analyses[r["status_hash"]].append(r["value"])
    return episodes, services, statuses, data, analyses


def service_event(srv, kind, statuses, data, analyses):
    """
    Что известно об одной назначенной услуге.
    Возвращает словарь: state (done / waiting / assigned / cancelled), when, value, text.
    """
    st = statuses.get(srv["usluga_hash"], {})
    if "Отменена" in st:
        return {"state": "cancelled"}
    if kind == "анализ":
        if "Результат готов" in st:
            s = st["Результат готов"]
            vals = analyses.get(s["status_hash"], [])
            value = vals[0] if vals else ""
            return {"state": "done", "when": parse_date(s["status_at"]), "value": value,
                    "text": f"Результат: {value}"}
        if "Выполнена" in st:
            return {"state": "waiting", "when": parse_date(st["Выполнена"]["status_at"]),
                    "text": "Биоматериал взят, результата еще нет"}
    else:
        if "Выполнена" in st:
            s = st["Выполнена"]
            d = data.get(s["status_hash"], {})
            if kind == "прививка":
                when = parse_date(d.get("Дата вакцинации")) or parse_date(s["status_at"])
                return {"state": "done", "when": when, "value": "",
                        "text": f"Дата вакцинации: {d.get('Дата вакцинации', '?')}. {d.get('Документ', '')}".strip()}
            concl = d.get("Заключение", "")
            return {"state": "done", "when": parse_date(s["status_at"]), "value": concl,
                    "text": f"Заключение: {concl}" if concl else "Выполнено, заключения нет"}
    return {"state": "assigned", "when": parse_date(srv["assigned_at"]), "text": "Назначено, не выполнено"}


def exam_status(exam, srv_list, rules, srez, statuses, data, analyses):
    """Статус одного обследования. Возвращает (статус, подпись, источник)."""
    events = []
    for srv in srv_list:
        ev = service_event(srv, exam["kind"], statuses, data, analyses)
        if ev["state"] != "cancelled":
            ev["srv"] = srv
            events.append(ev)
    if not events:
        return "Нет данных", "нет данных", None

    # Учитывается последний ЗАВЕРШЕННЫЙ результат. Если завершенных нет, показываем,
    # что обследование в процессе (ждет результата или только назначено).
    done = [e for e in events if e["state"] == "done"]
    if not done:
        ev = max(events, key=lambda e: e["when"] or datetime.min)
        if ev["state"] == "waiting":
            return "Ждёт результата", "ждёт результата", ev
        return "Назначено, не выполнено", "назначено", ev
    ev = max(done, key=lambda e: e["when"] or datetime.min)

    if exam["kind"] == "анализ":
        if ev["value"].strip().lower() not in rules.ok_results:
            return "Не в норме", ev["value"], ev
    else:
        for phrase, label, reason in rules.bad_phrases.get(exam["service_code"], []):
            if phrase in (ev["value"] or "").lower():
                ev["reason"] = reason          # текст для причины берем из справочника
                return "Не в норме", label, ev

    if exam["valid_months"]:
        expires = add_months(ev["when"].date(), exam["valid_months"])
        left = (expires - srez).days
        ev["text"] += f". Действует до {expires:%d.%m.%Y}"
        if left < 0:
            return "Просрочено", f"просрочено {-left} дн.", ev
        if left <= rules.soon_days:
            return "Скоро закончится", f"{left} дн. осталось", ev
    return "Норма", "норма", ev


# Как статус выглядит в причине. Серые статусы (еще не готово) объединяются в одну фразу.
GROUPED = {"Назначено, не выполнено": "не выполнено", "Ждёт результата": "ждёт результата",
           "Нет данных": "нет данных"}


def build_reason(problems):
    """
    problems: [(обследование, статус, подпись, текст причины из справочника)] в порядке колонок.
    Сначала реальные проблемы по одной («ФЛГ: просрочено 10 дн.», «Терапевт: направлен на дообследование»),
    потом однотипные серые одной фразой («не выполнено: ВИЧ, HBsAg»).
    """
    red, grey = [], {}
    for exam, status, label, reason in problems:
        if status in GROUPED:
            grey.setdefault(GROUPED[status], []).append(exam["name"])
        elif status == "Не в норме" and exam["kind"] == "анализ":
            red.append(f"{exam['name']}: результат «{label}»")
        elif status == "Не в норме":
            red.append(f"{exam['name']}: {reason or label}")
        else:
            red.append(f"{exam['name']}: {label}")
    parts = red + [f"{kind}: {', '.join(names)}" for kind, names in grey.items()]
    return "; ".join(parts)


def calculate(con):
    """Пересчитать витрину для всех студентов. Возвращает {итог: количество}."""
    rules = get_rules(con)
    srez = date.fromisoformat(con.execute("SELECT value FROM load_meta WHERE key='srez_date'").fetchone()[0])
    episodes, services, statuses, data, analyses = load_qms(con)
    totals = defaultdict(int)

    with con:
        con.execute("DELETE FROM exam_status")
        con.execute("DELETE FROM admission")
        rows = con.execute("""SELECT s.student_id, m.match_type, m.patient_hash, m.note
                              FROM student s JOIN student_match m USING (student_id)""").fetchall()
        for st in rows:
            sid = st["student_id"]
            if st["match_type"] != "полное":
                # FR-03: студента нет в qMS
                note = f" (частичное совпадение: {st['note']})" if st["match_type"] == "частичное" else ""
                for exam in rules.exams:
                    con.execute("INSERT INTO exam_status VALUES (?,?,?,?,?,?,?,?)",
                                (sid, exam["exam_id"], "Нет данных qMS", "—", "grey", None, None, None))
                con.execute("INSERT INTO admission VALUES (?,?,?,?)",
                            (sid, "Недопуск", "Нет данных qMS" + note, srez.isoformat()))
                totals["Недопуск"] += 1
                continue

            # все услуги пациента за все эпизоды, разложенные по кодам
            by_code = defaultdict(list)
            ep_number = {}
            for ep in episodes.get(st["patient_hash"], []):
                for srv in services.get(ep["episode_hash"], []):
                    by_code[srv["service_code"]].append(srv)
                    ep_number[srv["usluga_hash"]] = ep["episode_number"]

            problems, all_ok = [], True
            for exam in rules.exams:
                status, label, ev = exam_status(exam, by_code.get(exam["service_code"], []),
                                                rules, srez, statuses, data, analyses)
                color, ok = STATUS_STYLE[status]
                if not ok:
                    all_ok = False
                    problems.append((exam, status, label, (ev or {}).get("reason")))
                src_text = None
                if ev:
                    src_text = f"Эпизод {ep_number.get(ev['srv']['usluga_hash'], '?')}. {ev['text']}"
                con.execute("INSERT INTO exam_status VALUES (?,?,?,?,?,?,?,?)", (
                    sid, exam["exam_id"], status, label, color,
                    ev["srv"]["usluga_hash"] if ev else None,
                    ev["when"].strftime("%d.%m.%Y") if ev and ev.get("when") else None, src_text))

            result = "Допуск" if all_ok else "Недопуск"
            con.execute("INSERT INTO admission VALUES (?,?,?,?)",
                        (sid, result, build_reason(problems), srez.isoformat()))
            totals[result] += 1
    return dict(totals)
