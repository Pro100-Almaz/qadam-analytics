/**
 * Curriculum Sheet Builder — Qadam Analytics
 *
 * One-click Google Apps Script that turns a blank Google Sheet into a
 * curriculum-import template ready to hand to a teacher.
 *
 * HOW TO USE
 *   1. Open https://sheets.google.com and create a new blank sheet.
 *   2. Extensions → Apps Script.
 *   3. Delete any boilerplate code in the editor and paste this whole file.
 *   4. Edit the CONFIG block below (offering_id, subject, class group, year).
 *   5. Save (Ctrl+S), then run the function `setupCurriculumSheet`.
 *      First run will prompt for Google authorization — accept it.
 *   6. Return to the sheet — it is now formatted, protected, and shareable.
 *   7. Share with the teacher's email as Editor.
 *
 * What the script does
 *   - Names the sheet Curriculum_<id>_<subject>_<class>
 *   - Writes the 4-row metadata block and protects it
 *   - Writes the Russian column headers in row 5
 *   - Applies dropdowns for Quarter (1-4), Unit (1-15), Status
 *   - Sets the date column to plain text (avoids US-format coercion)
 *   - Adds conditional formatting: "ОШИБКА" rows turn red, "ОК" rows turn green
 *   - Freezes rows 1-5
 *   - Optionally inserts a worked example so teachers see the pattern
 *
 * Re-running the script will WIPE the current tab. A confirmation dialog
 * fires before any destructive action.
 */

// ─── CONFIG — edit these four lines per offering ────────────────────────────
const OFFERING_ID    = 42;
const SUBJECT_NAME   = 'Математика';
const CLASS_GROUP    = '7А';
const ACADEMIC_YEAR  = '2024-2025';
const SHOW_EXAMPLES  = true;   // set to false to start with an empty data area
// ────────────────────────────────────────────────────────────────────────────


function setupCurriculumSheet() {
  const ui = SpreadsheetApp.getUi();
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getActiveSheet();

  if (sheet.getLastRow() > 0 || sheet.getLastColumn() > 0) {
    const resp = ui.alert(
      'Очистить текущий лист?',
      'Скрипт перепишет содержимое активной вкладки. Продолжить?',
      ui.ButtonSet.OK_CANCEL
    );
    if (resp !== ui.Button.OK) return;
  }

  sheet.clear();
  sheet.clearConditionalFormatRules();
  sheet.clearNotes();

  const safeSubject = SUBJECT_NAME.replace(/[\\/?*\[\]]/g, '').slice(0, 40);
  const safeClass   = CLASS_GROUP.replace(/[\\/?*\[\]]/g, '').slice(0, 20);
  sheet.setName(`Curriculum_${OFFERING_ID}_${safeSubject}_${safeClass}`);

  writeMetadata_(sheet);
  writeHeaders_(sheet);
  setColumnWidths_(sheet);
  setDateColumnPlainText_(sheet);
  applyDropdowns_(sheet);
  applyConditionalFormatting_(sheet);
  sheet.setFrozenRows(5);
  protectMetadata_(sheet);

  if (SHOW_EXAMPLES) writeExamples_(sheet);

  ss.toast('Шаблон создан. Поделитесь ссылкой с учителем.', 'Готово', 6);
}


function writeMetadata_(sheet) {
  const rows = [
    ['offering_id',   OFFERING_ID],
    ['subject',       SUBJECT_NAME],
    ['class_group',   CLASS_GROUP],
    ['academic_year', ACADEMIC_YEAR],
  ];
  sheet.getRange(1, 1, 4, 2).setValues(rows);
  sheet.getRange(1, 1, 4, 1)
    .setFontWeight('bold')
    .setBackground('#E8EAF6')
    .setHorizontalAlignment('right');
  sheet.getRange(1, 2, 4, 1)
    .setBackground('#F5F5F5')
    .setHorizontalAlignment('left');
}


function writeHeaders_(sheet) {
  const headers = [
    'Четверть',
    'Модуль',
    'Название урока',
    'Описание урока',
    'Дата урока (ГГГГ-ММ-ДД)',
    'Статус урока',
    'Название темы',
    'Название родительской темы',
    'Вес (%)',
    'Шаблон комментария',
    'Статус импорта',
  ];
  sheet.getRange(5, 1, 1, headers.length)
    .setValues([headers])
    .setFontWeight('bold')
    .setBackground('#3F51B5')
    .setFontColor('#FFFFFF')
    .setHorizontalAlignment('center')
    .setVerticalAlignment('middle')
    .setWrap(true);
  sheet.setRowHeight(5, 42);

  const notes = [
    'Четверть (1-4)',
    'Модуль / юнит (1-15)',
    'Обязательно. Название урока.',
    'Краткое описание урока.',
    'Формат: ГГГГ-ММ-ДД (например 2025-09-01).',
    'Запланирован / Проведён / Перенесён / По плану',
    'Название темы. Корневые темы в одном уроке должны суммироваться до 100%.',
    'Если это подтема — название родительской темы. Иначе оставить пустым.',
    'Вес в процентах (число). Сумма по корневым темам = 100. Сумма подтем в одном родителе = 100.',
    'Шаблон комментария для оценки.',
    'Заполняется автоматически после импорта. Не редактировать.',
  ];
  sheet.getRange(5, 1, 1, notes.length).setNotes([notes]);
}


function setColumnWidths_(sheet) {
  const widths = [70, 70, 220, 250, 150, 140, 220, 220, 80, 220, 140];
  widths.forEach((w, i) => sheet.setColumnWidth(i + 1, w));
}


function setDateColumnPlainText_(sheet) {
  sheet.getRange('E6:E1000').setNumberFormat('@');
}


function applyDropdowns_(sheet) {
  const build = (values) => SpreadsheetApp.newDataValidation()
    .requireValueInList(values, true)
    .setAllowInvalid(true)
    .build();

  sheet.getRange('A6:A1000').setDataValidation(build(['1', '2', '3', '4']));

  const units = [];
  for (let i = 1; i <= 15; i++) units.push(String(i));
  sheet.getRange('B6:B1000').setDataValidation(build(units));

  sheet.getRange('F6:F1000').setDataValidation(build([
    'Запланирован', 'Проведён', 'Перенесён', 'По плану',
  ]));
}


function applyConditionalFormatting_(sheet) {
  const range = sheet.getRange('A6:K1000');

  const errorRule = SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=REGEXMATCH($K6, "^ОШИБКА")')
    .setBackground('#FFD0D0')
    .setRanges([range])
    .build();

  const okRule = SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=$K6="ОК"')
    .setBackground('#D9EAD3')
    .setRanges([range])
    .build();

  sheet.setConditionalFormatRules([errorRule, okRule]);
}


function protectMetadata_(sheet) {
  const protections = sheet.getProtections(SpreadsheetApp.ProtectionType.RANGE) || [];
  protections.forEach(p => p.remove());

  const protection = sheet.getRange('A1:B4').protect()
    .setDescription('Метаданные урока — не редактировать');
  const me = Session.getEffectiveUser();
  protection.addEditor(me);
  protection.removeEditors(protection.getEditors().filter(e => e.getEmail() !== me.getEmail()));
  if (protection.canDomainEdit()) protection.setDomainEdit(false);
  protection.setWarningOnly(false);
}


function writeExamples_(sheet) {
  const rows = [
    [1, 1, 'Введение в алгебру', 'Обзор базовых понятий',           '2025-09-01', 'Запланирован', 'Устный ответ', '',        100, 'Отвечает на вопросы',    ''],
    [1, 2, 'Линейные уравнения', 'Решение уравнений первой степени', '2025-09-08', 'Запланирован', 'Теория',       '',         60, 'Объясняет правило',      ''],
    [1, 2, 'Линейные уравнения', 'Решение уравнений первой степени', '2025-09-08', 'Запланирован', 'Объяснение',   'Теория',   40, 'Слушает и записывает',   ''],
    [1, 2, 'Линейные уравнения', 'Решение уравнений первой степени', '2025-09-08', 'Запланирован', 'Демонстрация', 'Теория',   60, 'Разбор примера у доски', ''],
    [1, 2, 'Линейные уравнения', 'Решение уравнений первой степени', '2025-09-08', 'Запланирован', 'Практика',     '',         40, 'Решает самостоятельно',  ''],
  ];
  sheet.getRange(6, 1, rows.length, rows[0].length).setValues(rows);

  const note = [
    'ПРИМЕР. Урок 1: одна корневая тема (100%). Урок 2: две корневые темы (Теория 60% + Практика 40% = 100). У темы "Теория" две подтемы (Объяснение 40% + Демонстрация 60% = 100). Удалите эти строки перед заполнением.',
  ];
  sheet.getRange(6, 3).setNote(note[0]);
}
