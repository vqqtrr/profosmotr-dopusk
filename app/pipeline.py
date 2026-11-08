"""
Полный пересчет: загрузка -> правила -> сопоставление -> расчет.
В реальной системе это запускалось бы ночью по расписанию.

Запуск вручную: python -m app.pipeline
"""
import time
from pathlib import Path

from .calc import calculate
from .db import DB_PATH, connect
from .loader import load_sources
from .matching import build_matches
from .rules import load_rules


def run_all(db_path=None, source_dir=None, rules_dir=None, verbose=True):
    t0 = time.time()
    # База каждый раз собирается с нуля: так изменения структуры таблиц
    # и справочника правил гарантированно применяются, а старые данные не мешают.
    Path(db_path or DB_PATH).unlink(missing_ok=True)
    con = connect(db_path)
    counts = load_sources(con, source_dir)
    load_rules(con, rules_dir)
    matches = build_matches(con)
    totals = calculate(con)
    con.close()
    if verbose:
        print(f"Загружено: 1С {counts['src_one_c_imo']} студентов, qMS {counts['src_patient']} пациентов, "
              f"{counts['src_usluga186']} услуг")
        print(f"Сопоставление: {matches}")
        print(f"Итог: {totals}. Время: {time.time() - t0:.1f} с")
    return {"counts": counts, "matches": matches, "totals": totals}


if __name__ == "__main__":
    run_all()
