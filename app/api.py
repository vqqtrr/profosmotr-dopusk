"""
5. Сервер: отдает экрану методиста данные из витрины.

Запросы:
  GET /api/meta                         дата данных
  GET /api/filters                      уровни -> курсы -> группы для каскадных фильтров
  GET /api/group/{группа}               таблица группы, сводка, несопоставленные
  GET /api/cell/{студент}/{обследование}  на основании какой записи qMS поставлен статус
Список всех запросов с описанием: http://127.0.0.1:8000/docs
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .db import DB_PATH, connect
from .pipeline import run_all

ROOT = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def lifespan(_app):
    # если базы еще нет (первый запуск), сначала загружаем данные и считаем допуск
    if not DB_PATH.exists():
        run_all()
    yield


app = FastAPI(title="Допуск к практике", description="Прототип: FR-03, FR-05, FR-06 (US-1, UC-01)",
              lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


def db():
    return connect()


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/meta")
def meta():
    con = db()
    m = {r["key"]: r["value"] for r in con.execute("SELECT * FROM load_meta")}
    return {"srez_date": m.get("srez_date"), "export_at": m.get("export_at")}


# привычный порядок уровней обучения (не по алфавиту); неизвестные уровни идут в конец
LEVEL_ORDER = ["СПО", "Специалитет", "Ординатура"]


@app.get("/api/filters")
def filters():
    con = db()
    tree = {}
    for r in con.execute("SELECT DISTINCT level, course, group_name FROM student ORDER BY course, group_name"):
        tree.setdefault(r["level"], {}).setdefault(r["course"], []).append(r["group_name"])
    levels = sorted(tree, key=lambda l: LEVEL_ORDER.index(l) if l in LEVEL_ORDER else len(LEVEL_ORDER))
    return [{"level": lvl, "courses": [{"course": c, "groups": g} for c, g in tree[lvl].items()]}
            for lvl in levels]


@app.get("/api/group/{group_name}")
def group(group_name: str):
    con = db()
    exams = [dict(r) for r in con.execute(
        "SELECT exam_id, section, name FROM rule_exam ORDER BY sort_order")]
    students = con.execute("""
        SELECT s.student_id, s.fio, a.result, a.reason, m.match_type, m.note
        FROM student s JOIN admission a USING (student_id) JOIN student_match m USING (student_id)
        WHERE s.group_name = ? ORDER BY s.fio""", (group_name,)).fetchall()
    if not students:
        raise HTTPException(404, f"Группа {group_name} не найдена")
    cells = {}
    for r in con.execute("""SELECT e.* FROM exam_status e JOIN student s USING (student_id)
                            WHERE s.group_name = ?""", (group_name,)):
        cells.setdefault(r["student_id"], {})[r["exam_id"]] = {
            "status": r["status"], "label": r["label"], "color": r["color"]}
    rows = [{"id": s["student_id"], "fio": s["fio"], "result": s["result"], "reason": s["reason"],
             "match_type": s["match_type"], "match_note": s["note"],
             "cells": cells.get(s["student_id"], {})} for s in students]
    unmatched = [{"fio": s["fio"], "match_type": s["match_type"], "note": s["note"]}
                 for s in students if s["match_type"] != "полное"]
    admitted = sum(1 for r in rows if r["result"] == "Допуск")
    return {"group": group_name, "exams": exams, "students": rows, "unmatched": unmatched,
            "summary": {"total": len(rows), "admitted": admitted, "not_admitted": len(rows) - admitted}}


@app.get("/api/cell/{student_id}/{exam_id}")
def cell(student_id: int, exam_id: str):
    con = db()
    r = con.execute("""SELECT e.*, s.fio, x.name AS exam_name, x.service_code
                       FROM exam_status e JOIN student s USING (student_id)
                       JOIN rule_exam x USING (exam_id)
                       WHERE e.student_id = ? AND e.exam_id = ?""", (student_id, exam_id)).fetchone()
    if not r:
        raise HTTPException(404, "Нет такой ячейки")
    return dict(r)
