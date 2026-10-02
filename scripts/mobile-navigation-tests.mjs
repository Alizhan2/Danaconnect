import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import vm from 'node:vm';
import { test } from 'node:test';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const ts = createRequire(path.join(root, 'apps/web/package.json'))('typescript');
const source = readFileSync(path.join(root, 'apps/web/src/lib/navigation.ts'), 'utf8');
const module = { exports: {} };
vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, { exports: module.exports, module, Set });
const { mobileNavigation } = module.exports;
const publicItems = [{ href: '/catalog', label: 'Менторы' }, { href: '/projects', label: 'Проекты' }];
const accountItems = ['/dashboard', '/catalog', '/projects', '/calendar', '/messages', '/team', '/resources', '/achievements', '/privacy'].map(href => ({ href, label: href }));
const login = { href: '/login', label: 'Войти' };
const hrefs = items => Array.from(items, item => item.href);

test('signed-in mobile menu includes every account destination once', () => {
  const items = mobileNavigation(publicItems, accountItems, true, login);
  assert.deepEqual(hrefs(items), ['/catalog', '/projects', '/dashboard', '/calendar', '/messages', '/team', '/resources', '/achievements', '/privacy']);
  assert.equal(items[0].label, 'Менторы');
});
test('anonymous mobile menu exposes public pages and sign-in', () => {
  assert.deepEqual(hrefs(mobileNavigation(publicItems, accountItems, false, login)), ['/catalog', '/projects', '/login']);
});
test('admin link is included only when supplied by account permissions', () => {
  const adminItems = [...accountItems, { href: '/admin', label: 'Admin' }];
  assert.ok(hrefs(mobileNavigation(publicItems, adminItems, true, login)).includes('/admin'));
  assert.ok(!hrefs(mobileNavigation(publicItems, accountItems, true, login)).includes('/admin'));
});
test('navigation does not mutate localized input arrays', () => {
  const before = JSON.stringify([publicItems, accountItems]);
  mobileNavigation(publicItems, accountItems, true, login);
  assert.equal(JSON.stringify([publicItems, accountItems]), before);
});
