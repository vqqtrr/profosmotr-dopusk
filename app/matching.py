"""
2. Сопоставление студентов из 1С с пациентами qMS.

Общего идентификатора у систем нет, поэтому связываем по трем полям сразу:
ФИО + дата рождения + СНИЛС. Перед сравнением приводим значения к одному виду.
Если совпали только два поля из трех, связь НЕ создаем (можно перепутать людей),
но помечаем студента как «частичное совпадение», чтобы администратор разобрался.
"""
import re

FIELD_NAMES = {"fio": "ФИО", "birth_date": "дата рождения", "snils": "СНИЛС"}


def norm_fio(value):
    """«ИВАНОВ  Пётр » -> «иванов петр»: регистр, лишние пробелы, ё/е."""
    value = (value or "").lower().replace("ё", "е")
    return " ".join(value.split())


def norm_snils(value):
    """«123-456-789 01» -> «12345678901»: оставляем только цифры."""
    return re.sub(r"\D", "", value or "")


def key_of(row):
    return {"fio": norm_fio(row["fio"]), "birth_date": (row["birth_date"] or "").strip(),
            "snils": norm_snils(row["snils"])}


def build_matches(con):
    """Заполнить таблицы student и student_match. Возвращает счетчики по типам совпадения."""
    with con:
        con.execute("DELETE FROM student")
        con.execute("DELETE FROM student_match")
        con.execute("""INSERT INTO student (fio, birth_date, snils, level, faculty, course, group_name)
                       SELECT fio, birth_date, snils, level, faculty, course, group_name FROM src_one_c_imo""")

        # индексы пациентов: по всем трем полям и по каждой паре полей
        full, pairs = {}, {("fio", "birth_date"): {}, ("fio", "snils"): {}, ("birth_date", "snils"): {}}
        for p in con.execute("SELECT * FROM src_patient"):
            k = key_of(p)
            full[(k["fio"], k["birth_date"], k["snils"])] = p["patient_hash"]
            for pair, index in pairs.items():
                index.setdefault(tuple(k[f] for f in pair), []).append(p["patient_hash"])

        counts = {"полное": 0, "частичное": 0, "не найден": 0}
        for s in con.execute("SELECT * FROM student").fetchall():
            k = key_of(s)
            patient = full.get((k["fio"], k["birth_date"], k["snils"]))
            if patient:
                row = ("полное", patient, None)
            else:
                note = None
                for pair, index in pairs.items():
                    if tuple(k[f] for f in pair) in index:
                        differs = [f for f in FIELD_NAMES if f not in pair][0]
                        note = f"не совпало поле «{FIELD_NAMES[differs]}»"
                        break
                row = ("частичное", None, note) if note else ("не найден", None, None)
            counts[row[0]] += 1
            con.execute("INSERT INTO student_match VALUES (?, ?, ?, ?)", (s["student_id"], *row))
    return counts
