"""
1. Загрузка выгрузок 1С и qMS в базу.

Каждый CSV кладется в свою таблицу src_* без изменений. Перед загрузкой таблица очищается,
и все происходит в одной транзакции: если файл битый, в базе остаются прежние данные,
а повторная загрузка никогда не создает дублей.
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = ROOT / "data" / "source"

# файл -> (таблица, {колонка в CSV: колонка в базе})
FILES = {
    "1c/one_c_imo.csv": ("src_one_c_imo", {
        "ФИО": "fio", "Дата_рождения": "birth_date", "СНИЛС": "snils", "Уровень_образования": "level",
        "Факультет": "faculty", "Курс": "course", "Группа": "group_name"}),
    "qms/obj_patient_wh.csv": ("src_patient", {
        "Пациент_хэш": "patient_hash", "Регистрационный_номер": "reg_number", "ФИО": "fio",
        "Дата_рождения": "birth_date", "СНИЛС": "snils"}),
    "qms/obj_episode_wh.csv": ("src_episode", {
        "Эпизод_хэш": "episode_hash", "Пациент_хэш": "patient_hash", "Номер_эпизода": "episode_number",
        "Дата_открытия": "opened", "Дата_закрытия": "closed"}),
    "qms/obj_usluga186_wh.csv": ("src_usluga186", {
        "Услуга186_хэш": "usluga_hash", "Эпизод_хэш": "episode_hash", "Код_услуги": "service_code",
        "Дата_назначения": "assigned_at", "Дата_выполнения": "done_at"}),
    "qms/obj_usluga293_wh.csv": ("src_usluga293", {
        "Услуга293_хэш": "status_hash", "Услуга186_хэш": "usluga_hash", "Статус": "status",
        "Дата_статуса": "status_at"}),
    "qms/obj_usluga294_wh.csv": ("src_usluga294", {
        "Услуга294_хэш": "data_hash", "Услуга293_хэш": "status_hash", "Статус": "field", "Данные": "value"}),
    "qms/obj_analyz_wh.csv": ("src_analyz", {
        "Анализ_хэш": "analyz_hash", "Услуга293_хэш": "status_hash", "Код_анализа": "analyz_code",
        "Значение_анализа": "value"}),
    "qms/ref_usluga.csv": ("src_ref_usluga", {
        "Код_услуги": "service_code", "Наименование": "name", "Тип_услуги": "service_type"}),
    "qms/ref_analyz.csv": ("src_ref_analyz", {
        "Код_анализа": "analyz_code", "Название_анализа": "name", "Единица_измерения": "unit"}),
}


def read_csv(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter=";"))


def load_sources(con, source_dir=None):
    """Загрузить все выгрузки. Возвращает {таблица: число строк}."""
    source_dir = Path(source_dir or SOURCE_DIR)
    counts = {}
    with con:  # одна транзакция на всю загрузку
        for rel, (table, mapping) in FILES.items():
            rows = read_csv(source_dir / rel)
            missing = set(mapping) - set(rows[0].keys() if rows else mapping)
            if missing:
                raise ValueError(f"В файле {rel} нет колонок: {', '.join(sorted(missing))}")
            con.execute(f"DELETE FROM {table}")
            cols = list(mapping.values())
            sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
            con.executemany(sql, [[(r[c] or None) for c in mapping] for r in rows])
            counts[table] = len(rows)
        meta = json.loads((source_dir / "export_meta.json").read_text(encoding="utf-8"))
        con.execute("DELETE FROM load_meta")
        # дата среза = «сегодня» для всех расчетов (берем только дату)
        con.execute("INSERT INTO load_meta VALUES ('srez_date', ?)", (meta["Дата_выгрузки"][:10],))
        con.execute("INSERT INTO load_meta VALUES ('export_at', ?)", (meta["Дата_выгрузки"],))
    return counts
