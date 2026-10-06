import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import vm from 'node:vm';
import { test } from 'node:test';

// Exercise the actual demo data and TSX handlers with deterministic React state.
// This VM exposes no network, browser storage, production identity or API module.
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const ts = createRequire(path.join(root, 'apps/web/package.json'))('typescript');
const source = relative => readFileSync(path.join(root, 'apps/web/src', relative), 'utf8');
function compile(relative, modules = {}) {
  const module = { exports: {} };
  const code = ts.transpileModule(source(relative), { compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText;
  vm.runInNewContext(`(function(require,exports,module){${code}\n})`, { Date, Intl, URL, URLSearchParams })(name => {
    assert.ok(Object.hasOwn(modules, name), `Unexpected demo dependency ${name}`);
    return modules[name];
  }, module.exports, module);
  return module.exports;
}
function nodes(tree) {
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  if (tree && typeof tree === 'object') return [tree, ...nodes(tree.props?.children), ...nodes(tree.props?.action)];
  return tree === null || tree === undefined ? [] : [tree];
}
function text(tree) { return nodes(tree).filter(value => typeof value === 'string' || typeof value === 'number').join(' '); }
function screen(name, { locale = 'ru', props = {} } = {}) {
  const values = []; let cursor = 0; let tree;
  const react = {
    useState(initial) {
      const position = cursor++;
      if (!(position in values)) values[position] = typeof initial === 'function' ? initial() : initial;
      return [values[position], next => { values[position] = typeof next === 'function' ? next(values[position]) : next; }];
    },
    useMemo: work => work(), useCallback: work => work(),
  };
  const jsx = (type, props) => typeof type === 'function' ? type(props) : ({ type, props });
  const ui = { Button: 'button', Badge: 'badge', Field: 'field', EmptyState: 'empty', SectionHeading: 'heading', TextLink: 'link' };
  const icons = new Proxy({}, { get: (_, key) => `icon-${String(key)}` });
  const modules = {
    react, 'react/jsx-runtime': { jsx, jsxs: jsx, Fragment: 'fragment' },
    '@/lib/i18n': { useLocale: () => ({ locale, tr: value => value, t: {} }), translatePhrase: value => value },
    '@/lib/demo-mentors': data, './ui': ui, '@/components/ui': ui,
    './shell': { AppShell: 'shell' }, '@/components/shell': { AppShell: 'shell' },
    'next/link': { default: 'link' }, 'lucide-react': icons,
  };
  modules['./mentor-discovery'] = compile('components/mentor-discovery.tsx', modules);
  const component = compile('components/demo-mentors.tsx', modules)[name];
  assert.equal(typeof component, 'function', `${name} is exported`);
  const result = {
    render() { cursor = 0; tree = component(props); return tree; },
    nodes: () => nodes(tree), text: () => text(tree),
    find: predicate => nodes(tree).find(predicate),
    change(predicate, value) {
      const control = this.find(predicate); assert.ok(control, 'control exists');
      control.props.onChange({ target: { value } }); this.render();
    },
    toggle(predicate, checked) {
      const control = this.find(predicate); assert.ok(control, 'checkbox exists');
      control.props.onChange({ target: { checked } }); this.render();
    },
    click(label) {
      const button = this.find(node => node?.type === 'button' && text(node) === label);
      assert.ok(button, `button ${label} exists`); button.props.onClick(); this.render();
    },
    async submit() {
      const form = this.find(node => node?.type === 'form'); assert.ok(form, 'form exists');
      let prevented = false;
      await form.props.onSubmit({ preventDefault() { prevented = true; } });
      assert.equal(prevented, true); this.render();
    },
  };
  result.render(); return result;
}

const data = compile('lib/demo-mentors.ts');

test('demo contains six unique fictional mentors, two in each supported direction', () => {
  assert.equal(data.demoMentors.length, 6);
  assert.equal(new Set(data.demoMentors.map(mentor => mentor.id)).size, 6);
  assert.deepEqual(Array.from(data.demoDirections, direction => direction.id).sort(), ['education', 'it', 'psychology']);
  for (const direction of data.demoDirections) assert.equal(data.demoMentors.filter(mentor => mentor.direction === direction.id).length, 2);
  for (const mentor of data.demoMentors) {
    assert.match(mentor.id, /^[a-z]+-[a-z]+$/);
    assert.doesNotMatch(mentor.id, /^[0-9a-f]{8}-[0-9a-f-]{27}$/i);
    assert.match(mentor.name, /Demo/);
    assert.equal(data.getDemoMentor(mentor.id), mentor);
  }
  assert.equal(data.getDemoMentor('not-a-demo-profile'), undefined);
});

test('fictional mentor capacity is valid and includes both open and closed examples', () => {
  for (const mentor of data.demoMentors) {
    assert.ok(Number.isInteger(mentor.capacity) && mentor.capacity > 0);
    assert.ok(Number.isInteger(mentor.occupied) && mentor.occupied >= 0 && mentor.occupied <= mentor.capacity);
    assert.ok(Number.isInteger(mentor.experienceYears) && mentor.experienceYears > 0);
  }
  assert.ok(data.demoMentors.some(mentor => mentor.capacity === mentor.occupied));
  assert.ok(data.demoMentors.some(mentor => mentor.capacity > mentor.occupied));
});

test('all mentor content and demo interface keys exist in Russian, Kazakh and English', () => {
  const keys = Object.keys(data.demoText.ru).sort();
  for (const locale of ['ru', 'kk', 'en']) {
    assert.deepEqual(Object.keys(data.demoText[locale]).sort(), keys);
    for (const key of keys) assert.ok(data.demoText[locale][key].trim(), `${locale}.${key}`);
    for (const direction of data.demoDirections) {
      assert.ok(direction.label[locale].trim());
      assert.equal(data.getDemoDirectionLabel(direction.id, locale), direction.label[locale]);
    }
    for (const mentor of data.demoMentors) {
      for (const key of ['city', 'title', 'bio', 'format']) assert.ok(mentor[key][locale].trim(), `${mentor.id}.${key}.${locale}`);
      for (const key of ['expertise', 'help']) assert.ok(mentor[key][locale].length > 0 && mentor[key][locale].every(item => item.trim()), `${mentor.id}.${key}.${locale}`);
      assert.match(mentor.bio[locale], { ru: /вымышлен/i, kk: /ойдан шығарылған/i, en: /fictional/i }[locale]);
    }
  }
});

test('demo sources cannot load live API, credentials, email, legal collection or browser persistence', () => {
  for (const relative of ['lib/demo-mentors.ts', 'components/demo-mentors.tsx']) {
    assert.doesNotMatch(source(relative), /@\/lib\/api|workflows\/common|fetch\s*\(|XMLHttpRequest|sendBeacon|localStorage|sessionStorage|indexedDB|document\.cookie|process\.env/);
    assert.doesNotMatch(source(relative), /type=["'](?:email|password)["']|name=["'](?:email|password|phone|consent)["']/);
  }
});

function profileLinks(fixture) {
  return fixture.nodes().filter(node => node?.props?.href?.startsWith('/demo/mentors/')).map(node => node.props.href);
}
const searchInput = node => node?.type === 'input' && node.props.type !== 'checkbox';
const directionSelect = node => node?.type === 'select';
const availableCheckbox = node => node?.type === 'input' && node.props.type === 'checkbox';

test('catalog renders six demo profiles and explicit fictional disclaimer in every locale', () => {
  for (const locale of ['ru', 'kk', 'en']) {
    const fixture = screen('DemoMentorCatalog', { locale });
    assert.ok(fixture.text().includes(data.demoText[locale].disclaimer));
    assert.equal(new Set(profileLinks(fixture)).size, 6);
    assert.ok(fixture.text().includes(data.demoText[locale].badge));
    for (const mentor of data.demoMentors) assert.ok(fixture.text().includes(mentor.name));
  }
});

test('catalog direction filter uses demo tracks and offers two mentors per track', () => {
  const fixture = screen('DemoMentorCatalog');
  for (const direction of data.demoDirections) {
    fixture.change(directionSelect, direction.id);
    assert.deepEqual(profileLinks(fixture).sort(), Array.from(data.demoMentors.filter(mentor => mentor.direction === direction.id), mentor => `/demo/mentors/${mentor.id}`).sort());
  }
});

test('catalog searches localized skill and city text case-insensitively with trimmed query', () => {
  const fixture = screen('DemoMentorCatalog');
  fixture.change(searchInput, '  PYTHON  ');
  assert.deepEqual(profileLinks(fixture), ['/demo/mentors/dana-backend']);
  fixture.change(searchInput, 'SHYMKENT');
  assert.deepEqual(profileLinks(fixture), ['/demo/mentors/sara-edtech']);
  fixture.change(searchInput, '  ');
  assert.equal(new Set(profileLinks(fixture)).size, 6);
});

test('available-only filter excludes the closed mentor and combines with direction', () => {
  const fixture = screen('DemoMentorCatalog');
  fixture.toggle(availableCheckbox, true);
  assert.equal(new Set(profileLinks(fixture)).size, 5);
  assert.ok(!profileLinks(fixture).includes('/demo/mentors/aiya-communication'));
  fixture.change(directionSelect, 'psychology');
  assert.deepEqual(profileLinks(fixture), ['/demo/mentors/mira-development']);
});

test('empty search displays a reset action that clears all catalog filters', () => {
  const fixture = screen('DemoMentorCatalog');
  fixture.change(directionSelect, 'education');
  fixture.toggle(availableCheckbox, true);
  fixture.change(searchInput, 'no-such-synthetic-mentor');
  assert.equal(profileLinks(fixture).length, 0);
  const empty = fixture.find(node => node?.type === 'empty');
  assert.equal(empty?.props.title, data.demoText.ru.noResults);
  fixture.click(data.demoText.ru.resetFilters);
  assert.equal(new Set(profileLinks(fixture)).size, 6);
  assert.equal(fixture.find(searchInput).props.value, '');
  assert.equal(fixture.find(directionSelect).props.value, '');
  assert.equal(fixture.find(availableCheckbox).props.checked, false);
});

test('profile displays its demo label and complete localized content, with demo-only links', () => {
  for (const locale of ['ru', 'kk', 'en']) {
    const mentor = data.demoMentors[0];
    const fixture = screen('DemoMentorProfile', { locale, props: { id: mentor.id } });
    const rendered = fixture.text();
    for (const content of [mentor.name, mentor.bio[locale], mentor.title[locale], data.demoText[locale].demoNotice, data.demoText[locale].disclaimer]) assert.ok(rendered.includes(content), content);
    for (const item of mentor.help[locale]) assert.ok(rendered.includes(item));
    for (const node of fixture.nodes()) if (node?.props?.href) assert.ok(!node.props.href.startsWith('/mentors/'), node.props.href);
  }
});

test('unknown demo identifier displays a localized missing-profile state without application form', () => {
  for (const locale of ['ru', 'kk', 'en']) {
    const fixture = screen('DemoMentorProfile', { locale, props: { id: 'unknown-demo-id' } });
    const empty = fixture.find(node => node?.type === 'empty');
    assert.equal(empty?.props.title, data.demoText[locale].notFound);
    assert.equal(fixture.find(node => node?.type === 'form'), undefined);
    assert.ok(fixture.nodes().some(node => node?.props?.href === '/demo/mentors'));
  }
});

test('closed demo mentor disables the form and rejects a directly invoked submitting handler', async () => {
  const mentor = data.demoMentors.find(item => item.capacity === item.occupied);
  const fixture = screen('DemoMentorProfile', { props: { id: mentor.id } });
  assert.ok(fixture.text().includes(data.demoText.ru.full));
  assert.equal(fixture.find(node => node?.type === 'textarea').props.disabled, true);
  assert.equal(fixture.find(node => node?.props?.type === 'submit').props.disabled, true);
  fixture.change(node => node?.type === 'textarea', 'Synthetic project motivation');
  await fixture.submit();
  assert.ok(!fixture.text().includes(data.demoText.ru.applicationSuccess));
  assert.ok(!fixture.text().includes(data.demoText.ru.applicationSuccessDescription));
});

test('valid mock application is trimmed, previewed and explicitly never sent in all locales', async () => {
  for (const locale of ['ru', 'kk', 'en']) {
    const fixture = screen('DemoMentorProfile', { locale, props: { id: data.demoMentors[0].id } });
    const input = fixture.find(node => node?.type === 'textarea');
    assert.equal(input.props.minLength, 10); assert.equal(input.props.maxLength, 1000);
    assert.equal(input.props.required, true); assert.equal(input.props.disabled, false);
    fixture.change(node => node?.type === 'textarea', '   Synthetic project motivation   ');
    await fixture.submit();
    assert.ok(fixture.text().includes(data.demoText[locale].applicationSuccess));
    assert.ok(fixture.text().includes(data.demoText[locale].applicationSuccessDescription));
    const preview = fixture.find(node => node?.type === 'p' && node.props.className === 'pre-line');
    assert.equal(preview.props.children, 'Synthetic project motivation');
    assert.equal(fixture.find(node => node?.type === 'form'), undefined);
    fixture.click(data.demoText[locale].tryAgain);
    assert.equal(fixture.find(node => node?.type === 'textarea').props.value, '');
    assert.ok(!fixture.text().includes(data.demoText[locale].applicationSuccess));
  }
});

test('mock application validates trimmed lengths even when native browser validation is bypassed', async () => {
  for (const motivation of ['', '         ', 'x'.repeat(9), `  ${'x'.repeat(9)}  `, 'x'.repeat(1001)]) {
    const fixture = screen('DemoMentorProfile', { props: { id: data.demoMentors[0].id } });
    fixture.change(node => node?.type === 'textarea', motivation);
    await fixture.submit();
    assert.ok(fixture.text().includes(data.demoText.ru.motivationError));
    assert.equal(fixture.find(node => node?.type === 'textarea').props['aria-invalid'], true);
    assert.ok(!fixture.text().includes(data.demoText.ru.applicationSuccessDescription));
  }
  for (const motivation of ['x'.repeat(10), 'x'.repeat(1000)]) {
    const fixture = screen('DemoMentorProfile', { props: { id: data.demoMentors[0].id } });
    fixture.change(node => node?.type === 'textarea', motivation);
    await fixture.submit();
    assert.ok(fixture.text().includes(data.demoText.ru.applicationSuccessDescription));
  }
});
