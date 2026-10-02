import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import { test } from 'node:test';

// Execute the actual helpers without a browser or production data. Model a
// runtime with English-only locale data, while retaining real IANA/DST rules.
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const ts = createRequire(path.join(root, 'apps/web/package.json'))('typescript');
const source = relative => readFileSync(path.join(root, relative), 'utf8');
function load(app, relative, intl = Intl) {
  const cache = new Map();
  const context = vm.createContext({ Intl: intl, Date, console });
  function file(filename) {
    if (cache.has(filename)) return cache.get(filename).exports;
    const module = { exports: {} }; cache.set(filename, module);
    const js = ts.transpileModule(readFileSync(filename, 'utf8'), { compilerOptions: {
      target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS,
    } }).outputText;
    const require = name => {
      if (name === 'react') return { createContext: value => ({ value }) };
      const base = name.startsWith('@/') ? path.join(root, `apps/${app}/src`, name.slice(2))
        : path.resolve(path.dirname(filename), name);
      const target = ['.ts', '.tsx', '/index.ts', '/index.tsx'].map(suffix => base + suffix).find(existsSync);
      assert.ok(target, `Missing dependency ${name}`);
      return file(target);
    };
    vm.runInContext(`(function(exports, require, module) { ${js}\n})`, context, { filename })(module.exports, require, module);
    return module.exports;
  }
  return file(path.join(root, `apps/${app}/src`, relative));
}
const limitedIntl = {
  DateTimeFormat: function (locale, options) {
    assert.ok(locale.startsWith('en'), 'Only English locale data is available');
    return new Intl.DateTimeFormat(locale, options);
  },
};

test('web and admin keep an identical centralized date formatter', () => {
  assert.equal(source('apps/web/src/lib/date-format.ts'), source('apps/admin/src/lib/date-format.ts'));
});

test('all existing dateTime wrappers preserve their argument order and defaults', () => {
  for (const [app, relative, localeSecond] of [
    ['web', 'components/workflows/common.tsx', false],
    ['admin', 'components/growth/common.tsx', false],
    ['admin', 'lib/i18n.tsx', true],
  ]) {
    const filename = path.join(root, `apps/${app}/src`, relative);
    const syntax = ts.createSourceFile(filename, readFileSync(filename, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
    const declaration = syntax.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'dateTime');
    assert.ok(declaration, `Missing wrapper ${relative}`);
    const js = ts.transpileModule(declaration.getText(syntax), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText;
    const wrapper = vm.runInNewContext(`${js}; dateTime`, { exports: {}, formatDateTime: load(app, 'lib/date-format.ts', limitedIntl).formatDateTime });
    const date = '2026-10-02T12:00:00Z';
    assert.equal(localeSecond ? wrapper(date, 'kk', 'UTC') : wrapper(date, 'UTC', 'kk'), '2026 ж. 02 қаз., 12:00');
    assert.equal(localeSecond ? wrapper(date, 'en') : wrapper(date, undefined, 'en'), '2 Oct 2026, 17:00');
  }
});

for (const app of ['web', 'admin']) {
  test(`${app}: RU, KK and EN display October when only English locale data exists`, () => {
    const { formatDateTime } = load(app, 'lib/date-format.ts', limitedIntl);
    const date = '2026-10-02T12:00:00Z';
    assert.equal(formatDateTime(date, 'Asia/Oral', 'ru'), '2 окт. 2026 г., 17:00');
    assert.equal(formatDateTime(date, 'Asia/Oral', 'kk'), '2026 ж. 02 қаз., 17:00');
    assert.equal(formatDateTime(date, 'Asia/Oral', 'en'), '2 Oct 2026, 17:00');
  });

  test(`${app}: all twelve Kazakh month names are stable across locale data support`, () => {
    const { formatDateTime } = load(app, 'lib/date-format.ts', limitedIntl);
    const names = ['қаң.', 'ақп.', 'нау.', 'сәу.', 'мам.', 'мау.', 'шіл.', 'там.', 'қыр.', 'қаз.', 'қар.', 'жел.'];
    const full = load(app, 'lib/date-format.ts');
    for (let month = 1; month <= 12; month++) {
      const date = `2026-${String(month).padStart(2, '0')}-02T12:00:00Z`;
      const result = formatDateTime(date, 'UTC', 'kk');
      assert.equal(result, `2026 ж. 02 ${names[month - 1]}, 12:00`);
      assert.equal(result, full.formatDateTime(date, 'UTC', 'kk'));
      assert.doesNotMatch(result, /\bM\d{1,2}\b/);
    }
  });

  test(`${app}: timezone date boundaries and midnight are preserved`, () => {
    const { formatDateTime } = load(app, 'lib/date-format.ts', limitedIntl);
    assert.equal(formatDateTime('2026-12-31T20:00:00Z', 'Asia/Oral', 'kk'), '2027 ж. 01 қаң., 01:00');
    assert.equal(formatDateTime('2026-10-02T19:00:00Z', 'Asia/Oral', 'en'), '3 Oct 2026, 00:00');
    assert.equal(formatDateTime('2026-01-01T01:00:00Z', 'America/New_York', 'en'), '31 Dec 2025, 20:00');
  });

  test(`${app}: daylight saving spring gap and autumn repeated hour retain IANA offsets`, () => {
    const { formatDateTime } = load(app, 'lib/date-format.ts', limitedIntl);
    assert.equal(formatDateTime('2026-03-08T06:59:00Z', 'America/New_York', 'en'), '8 Mar 2026, 01:59');
    assert.equal(formatDateTime('2026-03-08T07:00:00Z', 'America/New_York', 'en'), '8 Mar 2026, 03:00');
    assert.equal(formatDateTime('2026-11-01T05:30:00Z', 'America/New_York', 'kk'), '2026 ж. 01 қар., 01:30');
    assert.equal(formatDateTime('2026-11-01T06:30:00Z', 'America/New_York', 'kk'), '2026 ж. 01 қар., 01:30');
  });

  test(`${app}: invalid timestamps and timezones safely retain the original value`, () => {
    const { formatDateTime, formatDate } = load(app, 'lib/date-format.ts', limitedIntl);
    for (const value of ['', 'bad date']) {
      assert.equal(formatDateTime(value, 'Asia/Oral', 'kk'), value);
      assert.equal(formatDate(value, 'kk'), value);
    }
    const date = '2026-10-02T12:00:00Z';
    assert.equal(formatDateTime(date, 'Invalid/Timezone', 'en'), date);
  });

  test(`${app}: birth dates remain calendar dates and never gain a time`, () => {
    const { formatDate } = load(app, 'lib/date-format.ts', limitedIntl);
    assert.equal(formatDate('2000-01-01', 'ru'), '1 янв. 2000 г.');
    assert.equal(formatDate('2000-01-01', 'kk'), '2000 ж. 01 қаң.');
    assert.equal(formatDate('2000-01-01', 'en'), '1 Jan 2000');
  });
}

test('messages and calendar controls have Kazakh and English phrase entries', () => {
  const translations = { ...load('web', 'lib/translations.ts').phraseTranslations, ...load('web', 'lib/feature-translations.ts').featureTranslations };
  const files = ['app/messages/page.tsx', 'app/calendar/page.tsx', 'components/calendar-rules/index.tsx'];
  const phrases = new Set();
  function collect(node) {
    if (ts.isStringLiteral(node) && /[А-Яа-яЁё]/.test(node.text)) phrases.add(node.text);
    ts.forEachChild(node, collect);
  }
  for (const file of files) {
    const filename = path.join(root, 'apps/web/src', file);
    collect(ts.createSourceFile(filename, readFileSync(filename, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX));
  }
  assert.ok(phrases.size > 50, 'Expected a meaningful control coverage sample');
  for (const phrase of phrases) {
    assert.ok(translations[phrase], `Missing translation entry: ${phrase}`);
    assert.ok(translations[phrase][0]?.trim(), `Empty KK translation: ${phrase}`);
    assert.ok(translations[phrase][1]?.trim(), `Empty EN translation: ${phrase}`);
  }
});

test('privacy, calendar export and message engagement cover all locales with matching keys', () => {
  for (const [relative, variable] of [['app/privacy/page.tsx', 'copy'], ['components/calendar-export/index.tsx', 'copy'], ['components/messages-engagement/index.tsx', 'phrases']]) {
    const filename = path.join(root, 'apps/web/src', relative);
    const syntax = ts.createSourceFile(filename, readFileSync(filename, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
    let declaration;
    syntax.forEachChild(node => {
      if (ts.isVariableStatement(node)) declaration ??= node.declarationList.declarations.find(item => item.name.getText(syntax) === variable);
    });
    assert.ok(declaration?.initializer, `Missing locale dictionary ${relative}`);
    const dictionary = vm.runInNewContext(`(${declaration.initializer.getText(syntax)})`);
    if (variable === 'phrases') {
      for (const [key, values] of Object.entries(dictionary)) {
        assert.equal(values.length, 3, key);
        assert.ok(values.every(value => typeof value === 'string' && value.trim()), key);
      }
    } else {
      const keys = Object.keys(dictionary.ru);
      for (const locale of ['kk', 'en']) {
        assert.deepEqual(Object.keys(dictionary[locale]), keys);
        for (const key of keys) assert.ok(dictionary[locale][key]?.trim(), `${relative}/${locale}/${key}`);
      }
    }
  }
});
