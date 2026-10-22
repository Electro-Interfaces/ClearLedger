// Положительный контроль: узел «Телефонии» читает НОВЫЙ ответ Ядра прежними полями.
//
// Берётся настоящий адаптер узла (`node/src/adapters/core.ts` репозитория
// contact-hub, только чтение — правок в него не вносилось) и настоящий ответ
// Ядра, снятый тем же прогоном, который выносит суждение о правке
// (`evidence/summary-answers.json`). Выдуманный пример здесь ничего не доказал
// бы: контракт ломается именно на поле, которого не ждали.
//
//   node --experimental-strip-types --no-warnings=ExperimentalWarning \
//     docs/solution-audit-20261021/fixes/R11/driver/node-consumer.mjs \
//     <корень contact-hub> <каталог evidence>
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { join, resolve } from 'node:path';

const [hub, evidence] = process.argv.slice(2);
const { summaryOf } = await import(resolve(hub, 'node/src/adapters/core.ts'));
const read = (name) => JSON.parse(readFileSync(join(evidence, name), 'utf8'));

const results = [];
const check = (name, fn) => {
  try { fn(); results.push({ пункт: name, итог: 'зелено' }); }
  catch (e) { results.push({ пункт: name, итог: 'красно', ошибка: e.message }); }
};

// P-01. Сводка с тремя ответами: узел берёт свои восемь полей и не спотыкается.
const answered = read('summary-answers.json');
check('P-01 узел читает сводку с ответами Ядра', () => {
  const s = summaryOf(answered);
  assert.equal(s.ticketAvailability, 'available');
  assert.equal(s.tickets.length, 5);
  assert.deepEqual(s.tickets.map((t) => t.number).sort(),
    ['TS-1', 'TS-2', 'TS-3', 'TS-4', 'TS-5']);
  for (const t of s.tickets) {
    assert.deepEqual(Object.keys(t).sort(),
      ['category', 'number', 'objectRef', 'priority', 'ref', 'slaDeadline', 'status', 'title']);
  }
  assert.ok(s.sessions.length > 0, 'сессии Ядра на месте');
  assert.ok(s.objects.length > 0, 'объекты Ядра на месте');
});

// P-02. Новое поле `answers` не протекает в карточку узла прежней сборки.
check('P-02 новое поле не протекает в карточку', () => {
  const s = summaryOf(answered);
  assert.ok(!JSON.stringify(s).includes('"answers"'));
  assert.ok(!JSON.stringify(s).includes('work_accepted'));
});

// P-03. Прежний ответ Ядра (без новых полей) читается как и раньше: узел новой
// сборки обслуживает Ядро, которое ещё не обновили.
check('P-03 прежний ответ Ядра читается без изменений', () => {
  const legacy = {
    sessions: [{ ref: 's1', objectRef: 'loc-1', startedAt: '2026-10-20T10:00:00+03:00',
      result: 'Complete', failed: false, energyKwh: 31.5, amount: 567 }],
    objects: [{ ref: 'loc-1', code: '65.000001', name: 'ЭЗС', address: 'ул. Ленина, 1', status: 'working' }],
    tickets: [{ ref: 'r1', number: 'TS-0', title: 'Старая заявка', status: 'open',
      priority: null, category: null, objectRef: 'loc-1', slaDeadline: null }],
    ticketAvailability: 'available',
  };
  const s = summaryOf(legacy);
  assert.equal(s.ticketAvailability, 'available');
  assert.equal(s.tickets.length, 1);
  assert.equal(s.sessions.length, 1);
});

// P-04. Каждое состояние источника: узел получает то же `ticketAvailability`,
// что и до правки, и ни разу не падает на новом поле.
for (const file of readdirSync(evidence).filter((f) => f.startsWith('summary-source-')).sort()) {
  const payload = read(file);
  check(`P-04 ${file}`, () => {
    const s = summaryOf(payload);
    assert.equal(s.ticketAvailability, payload.ticketAvailability);
    assert.equal(s.tickets.length,
      payload.ticketAvailability === 'available' ? payload.tickets.length : 0);
  });
}

const red = results.filter((r) => r.итог === 'красно');
console.log(JSON.stringify({
  источник: 'настоящий адаптер узла, contact-hub node/src/adapters/core.ts (только чтение)',
  пунктов: results.length, зелёных: results.length - red.length, красных: red.length,
  результаты: results,
}, null, 1));
process.exit(red.length ? 1 : 0);
