// 6. Экран методиста: фильтры, таблица группы, карточка ячейки.
// Вся логика допуска считается на сервере, здесь только отображение.

const $ = (id) => document.getElementById(id);
let tree = [];

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json();
}

function fill(select, items) {
  select.innerHTML = items.map((v) => `<option value="${v}">${v}</option>`).join("");
}

// Каскадные фильтры: при смене уровня меняются курсы, при смене курса меняются группы
function onLevel() {
  const lvl = tree.find((t) => t.level === $("f-level").value);
  fill($("f-course"), lvl.courses.map((c) => c.course));
  onCourse();
}
function onCourse() {
  const lvl = tree.find((t) => t.level === $("f-level").value);
  const course = lvl.courses.find((c) => String(c.course) === $("f-course").value);
  fill($("f-group"), course.groups);
  loadGroup();
}

async function loadGroup() {
  const g = await getJSON(`/api/group/${encodeURIComponent($("f-group").value)}`);
  $("summary").hidden = false;
  $("s-total").textContent = g.summary.total;
  $("s-ok").textContent = g.summary.admitted;
  $("s-bad").textContent = g.summary.not_admitted;
  renderTable(g);
  renderUnmatched(g.unmatched);
}

function renderTable(g) {
  // первая строка заголовка: разделы, вторая: обследования
  const sections = [];
  g.exams.forEach((e) => {
    const last = sections[sections.length - 1];
    if (last && last.name === e.section) last.span++;
    else sections.push({ name: e.section, span: 1 });
  });
  let html = "<thead><tr><th rowspan='2' class='fio'>ФИО</th>";
  html += sections.map((s) => `<th colspan="${s.span}" class="sec">${s.name}</th>`).join("");
  html += "<th rowspan='2'>Итог</th><th rowspan='2' class='reason'>Причина</th></tr><tr>";
  html += g.exams.map((e) => `<th class="exam">${e.name}</th>`).join("");
  html += "</tr></thead><tbody>";
  for (const s of g.students) {
    html += `<tr><td class="fio">${s.fio}</td>`;
    if (s.match_type !== "полное") {
      // FR-03: студента нет в qMS - одна объединенная ячейка вместо 14 прочерков
      const note = s.match_type === "частичное" ? ` · частичное совпадение: ${s.match_note}` : "";
      html += `<td class="nodata" colspan="${g.exams.length}">Нет данных qMS${note}</td>`;
    } else {
      for (const e of g.exams) {
        const c = s.cells[e.exam_id] || { label: "?", color: "grey", status: "" };
        // в норме ставим галочку: цвет уже говорит, что все хорошо; подписи только там, где есть что сказать
        const text = c.status === "Норма" ? "✓" : c.label;
        html += `<td class="cell ${c.color}" title="${c.status}" data-s="${s.id}" data-e="${e.exam_id}">${text}</td>`;
      }
    }
    const cls = s.result === "Допуск" ? "res ok" : "res bad";
    const reason = s.match_type === "полное" ? s.reason || "" : "Передать администратору";
    html += `<td class="${cls}">${s.result}</td><td class="reason">${reason}</td></tr>`;
  }
  $("grid").innerHTML = html + "</tbody>";
}

function renderUnmatched(list) {
  $("unmatched").hidden = list.length === 0;
  $("unmatched-list").innerHTML = list
    .map((u) => `<li><b>${u.fio}</b>: ${u.match_type === "частичное" ? "частичное совпадение, " + u.note : "нет в qMS"}</li>`)
    .join("");
}

// Карточка ячейки: на основании какой записи qMS поставлен статус
$("grid").addEventListener("click", async (ev) => {
  const td = ev.target.closest("td.cell");
  if (!td) return;
  const c = await getJSON(`/api/cell/${td.dataset.s}/${td.dataset.e}`);
  $("d-title").textContent = `${c.fio}: ${c.exam_name}`;
  const rows = [
    ["Статус", c.status],
    ["Код услуги qMS", c.service_code],
    ["Дата события", c.source_date || "—"],
    ["Запись qMS", c.source_text || "Записей нет"],
  ];
  $("d-body").innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
  $("cell-dialog").showModal();
});

async function init() {
  const meta = await getJSON("/api/meta");
  // «2026-10-18» -> «18.10.2026» без перевода через часовые пояса
  $("srez").textContent = meta.srez_date.split("-").reverse().join(".");
  tree = await getJSON("/api/filters");
  fill($("f-level"), tree.map((t) => t.level));
  if (tree.some((t) => t.level === "Специалитет")) $("f-level").value = "Специалитет";
  $("f-level").onchange = onLevel;
  $("f-course").onchange = onCourse;
  $("f-group").onchange = loadGroup;
  onLevel();
}
init();
