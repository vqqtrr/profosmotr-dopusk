"""
Подключение к базе SQLite и описание всех таблиц.

База лежит в одном файле data/profosmotr.db. Таблицы делятся на три группы:
  src_*      исходные выгрузки 1С и qMS «как есть» (повторяют физическую модель);
  rule_*     справочник правил допуска (загружается из папки rules/);
  витрина    результат расчета: student, student_match, exam_status, admission.
"""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "profosmotr.db"

SCHEMA = """
-- ---------- исходные выгрузки ----------
CREATE TABLE IF NOT EXISTS src_one_c_imo (
    fio TEXT, birth_date TEXT, snils TEXT,
    level TEXT, faculty TEXT, course INTEGER, group_name TEXT
);
CREATE TABLE IF NOT EXISTS src_patient (
    patient_hash TEXT PRIMARY KEY, reg_number TEXT, fio TEXT, birth_date TEXT, snils TEXT
);
CREATE TABLE IF NOT EXISTS src_episode (
    episode_hash TEXT PRIMARY KEY, patient_hash TEXT, episode_number TEXT, opened TEXT, closed TEXT
);
CREATE TABLE IF NOT EXISTS src_usluga186 (          -- назначенная услуга
    usluga_hash TEXT PRIMARY KEY, episode_hash TEXT, service_code TEXT, assigned_at TEXT, done_at TEXT
);
CREATE TABLE IF NOT EXISTS src_usluga293 (          -- история статусов услуги
    status_hash TEXT PRIMARY KEY, usluga_hash TEXT, status TEXT, status_at TEXT
);
CREATE TABLE IF NOT EXISTS src_usluga294 (          -- данные статуса (заключение, дата вакцинации...)
    data_hash TEXT PRIMARY KEY, status_hash TEXT, field TEXT, value TEXT
);
CREATE TABLE IF NOT EXISTS src_analyz (             -- значения анализов
    analyz_hash TEXT PRIMARY KEY, status_hash TEXT, analyz_code TEXT, value TEXT
);
CREATE TABLE IF NOT EXISTS src_ref_usluga (service_code TEXT PRIMARY KEY, name TEXT, service_type TEXT);
CREATE TABLE IF NOT EXISTS src_ref_analyz (analyz_code TEXT PRIMARY KEY, name TEXT, unit TEXT);
CREATE TABLE IF NOT EXISTS load_meta (key TEXT PRIMARY KEY, value TEXT);

CREATE INDEX IF NOT EXISTS ix_episode_patient ON src_episode(patient_hash);
CREATE INDEX IF NOT EXISTS ix_usluga_episode ON src_usluga186(episode_hash);
CREATE INDEX IF NOT EXISTS ix_status_usluga ON src_usluga293(usluga_hash);
CREATE INDEX IF NOT EXISTS ix_data_status ON src_usluga294(status_hash);
CREATE INDEX IF NOT EXISTS ix_analyz_status ON src_analyz(status_hash);

-- ---------- справочник правил ----------
CREATE TABLE IF NOT EXISTS rule_exam (
    exam_id TEXT PRIMARY KEY,      -- короткий код обследования (FLG, ADSM, RW ...)
    section TEXT,                  -- раздел на экране
    name TEXT,                     -- название колонки
    service_code TEXT,             -- код услуги в qMS
    kind TEXT,                     -- осмотр / анализ / прививка / ФЛГ
    valid_months INTEGER,          -- срок действия в месяцах (NULL = без срока)
    sort_order INTEGER
);
CREATE TABLE IF NOT EXISTS rule_bad_conclusion (
    service_code TEXT, phrase TEXT,
    label TEXT,                    -- короткая подпись для ячейки («дообследование»)
    reason TEXT                    -- текст для причины («направлен на дообследование»)
);
CREATE TABLE IF NOT EXISTS rule_ok_result (value TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS rule_setting (key TEXT PRIMARY KEY, value TEXT);

-- ---------- витрина (результат расчета) ----------
CREATE TABLE IF NOT EXISTS student (
    student_id INTEGER PRIMARY KEY, fio TEXT, birth_date TEXT, snils TEXT,
    level TEXT, faculty TEXT, course INTEGER, group_name TEXT
);
CREATE INDEX IF NOT EXISTS ix_student_group ON student(group_name);
CREATE TABLE IF NOT EXISTS student_match (
    student_id INTEGER PRIMARY KEY,
    match_type TEXT,               -- полное / частичное / не найден
    patient_hash TEXT,             -- заполнен только при полном совпадении
    note TEXT                      -- что не совпало при частичном
);
CREATE TABLE IF NOT EXISTS exam_status (
    student_id INTEGER, exam_id TEXT,
    status TEXT,                   -- Норма / Скоро закончится / Просрочено / Не в норме / ...
    label TEXT,                    -- короткий текст в ячейке
    color TEXT,                    -- green / yellow / red / grey
    source_usluga TEXT, source_date TEXT, source_text TEXT,
    PRIMARY KEY (student_id, exam_id)
);
CREATE TABLE IF NOT EXISTS admission (
    student_id INTEGER PRIMARY KEY, result TEXT, reason TEXT, calc_date TEXT
);
"""


def connect(path=None):
    """Открыть базу. path можно передать в тестах, чтобы не трогать рабочую базу."""
    p = Path(path) if path else DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con
