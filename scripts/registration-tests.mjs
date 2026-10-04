import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import { test } from 'node:test';

// Execute the actual TypeScript helpers and React event handlers using synthetic data.
// No server, production identity, email delivery or browser storage is used.
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const ts = createRequire(path.join(root, 'apps/web/package.json'))('typescript');
const file = relative => readFileSync(path.join(root, 'apps/web/src', relative), 'utf8');
const jsx = (type, props) => ({ type, props });
const locale = { locale: 'ru', tr: value => value, t: { city: 'Город', timezone: 'Часовой пояс', login: 'Войти' } };
function compile(relative, modules = {}, globals = {}, extra = '') {
  const module = { exports: {} };
  const code = ts.transpileModule(file(relative) + extra, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const common = { 'react/jsx-runtime': { jsx, jsxs: jsx, Fragment: 'fragment' }, '@/lib/i18n': { useLocale: () => locale, translatePhrase: value => value } };
  vm.runInNewContext(`(function(require,exports,module){${code}\n})`, { URL, URLSearchParams, Intl, Date, Event, ...globals })(name => {
    assert.ok(Object.hasOwn(modules, name) || Object.hasOwn(common, name), `Unexpected import ${name}`);
    return modules[name] || common[name];
  }, module.exports, module);
  return module.exports;
}
const helpers = compile('lib/registration.ts');
function nodes(tree) { return Array.isArray(tree) ? tree.flatMap(nodes) : tree && typeof tree === 'object' ? [tree, ...nodes(tree.props?.children)] : []; }
const directions = [{ id: 'it', name_ru: 'IT from API', name_kk: 'IT from API', name_en: 'IT from API' }];
const mentor = { ...helpers.emptyRegistration('mentor'), full_name: 'Synthetic Mentor', email: 'mentor@example.test', city: 'Oral', phone: '+77000000000', bio: 'Synthetic introduction', organization: 'Synthetic organization', expertise: 'Synthetic professional experience', evidence_urls: ['https://example.test/portfolio'], direction_ids: ['it'], mentor_commitment: true };
const mentee = { ...helpers.emptyRegistration('mentee'), full_name: 'Synthetic Mentee', email: 'mentee@example.test', city: 'Oral', bio: 'Synthetic idea and motivation', birth_date: '2002-01-01', direction_ids: ['it'] };
const fields = compile('components/registration-fields.tsx', { '@/lib/registration': helpers, './ui': { Button: 'button', Field: 'field' } });
function fieldNodes(draft, preview = false, update = () => {}) { return nodes(fields.RegistrationFields({ draft, directions, preview, update, reloadDirections: () => {} })); }

test('only participant roles are accepted as registration hints', () => {
  for (const value of [null, undefined, 'admin', 'MENTOR', 'mentor&admin=true', '//evil.test']) assert.equal(helpers.participantRole(value), undefined);
  for (const value of ['mentor', 'mentee']) assert.equal(helpers.participantRole(value), value);
});
test('role suggestions never change a previously saved role', () => {
  for (const existing of ['mentor', 'mentee', 'admin']) for (const hint of ['mentor', 'mentee', 'admin']) assert.equal(helpers.requestedRole(existing, hint), existing);
  assert.equal(helpers.requestedRole('unchosen', 'mentor'), 'mentor');
  assert.equal(helpers.requestedRole('unchosen', 'mentee'), 'mentee');
  assert.equal(helpers.requestedRole('unchosen', 'admin'), 'unchosen');
});
test('OTP handoff encodes return destination and includes only a valid role', () => {
  const target = new URL(helpers.onboardingPath('mentor', '/catalog?direction=it&search=x'), 'https://example.test');
  assert.equal(target.pathname, '/onboarding'); assert.equal(target.searchParams.get('role'), 'mentor'); assert.equal(target.searchParams.get('returnTo'), '/catalog?direction=it&search=x');
  assert.equal(new URL(helpers.onboardingPath('admin', '/dashboard'), 'https://example.test').searchParams.has('role'), false);
});
test('new mentor commitment starts unchecked and capacity zero remains valid', () => {
  assert.equal(helpers.emptyRegistration('mentor').mentor_commitment, false);
  assert.equal(helpers.registrationProblem({ ...mentor, capacity: 0 }, directions), '');
  for (const capacity of [-1, 51, 1.5, undefined]) assert.ok(helpers.registrationProblem({ ...mentor, capacity }, directions));
});
test('mentor phone, organization, experience, links and explicit commitment are required', () => {
  assert.equal(helpers.registrationProblem(mentor, directions), '');
  for (const changes of [{ phone: '' }, { organization: ' ' }, { expertise: 'short' }, { evidence_urls: [] }, { mentor_commitment: false }, { mentor_commitment: 'true' }]) assert.ok(helpers.registrationProblem({ ...mentor, ...changes }, directions));
});
test('mentee phone and organization stay optional while birth date and motivation are required', () => {
  assert.equal(helpers.registrationProblem(mentee, directions), '');
  for (const changes of [{ birth_date: '' }, { birth_date: '2002-02-31' }, { birth_date: '2999-01-01' }, { bio: '' }]) assert.ok(helpers.registrationProblem({ ...mentee, ...changes }, directions));
});
test('registration validates current API directions, time zone and organization length', () => {
  assert.ok(helpers.registrationProblem(mentor, [])); assert.ok(helpers.registrationProblem({ ...mentor, direction_ids: ['inactive'] }, directions));
  assert.ok(helpers.registrationProblem({ ...mentor, timezone: 'Not/AZone' }, directions));
  assert.equal(helpers.registrationProblem({ ...mentor, organization: 'x'.repeat(300) }, directions), '');
  assert.ok(helpers.registrationProblem({ ...mentor, organization: 'x'.repeat(301) }, directions));
});
test('shared mentor fields expose required phone, organization, experience and an unchecked commitment', () => {
  const inputs = fieldNodes({ ...mentor, mentor_commitment: false });
  for (const name of ['phone', 'organization', 'bio', 'expertise', 'evidence_urls', 'capacity', 'mentor_commitment']) assert.equal(inputs.find(node => node.props?.name === name).props.required, true, name);
  assert.equal(inputs.find(node => node.props?.name === 'mentor_commitment').props.checked, false);
  assert.ok(!inputs.some(node => node.props?.name === 'birth_date'));
});
test('shared mentee fields expose required birth date and optional contact/workplace', () => {
  const inputs = fieldNodes(mentee);
  assert.equal(inputs.find(node => node.props?.name === 'birth_date').props.required, true);
  for (const name of ['phone', 'organization']) assert.equal(inputs.find(node => node.props?.name === name).props.required, false);
  for (const name of ['expertise', 'evidence_urls', 'capacity', 'mentor_commitment']) assert.ok(!inputs.some(node => node.props?.name === name));
});
test('email is read-only after sign-in and is not collected in the public preview', () => {
  const authenticated = fieldNodes(mentor).find(node => node.props?.name === 'email'); assert.equal(authenticated.props.readOnly, true); assert.equal(authenticated.props.disabled, false);
  const preview = fieldNodes(helpers.emptyRegistration('mentor'), true).find(node => node.props?.name === 'email'); assert.equal(preview.props.disabled, true); assert.equal(preview.props.value, '');
});
test('shared fields render API direction names and toggle their actual identifiers', () => {
  const changes = []; const tree = fieldNodes({ ...mentor, direction_ids: [] }, true, (...values) => changes.push(values));
  const direction = tree.find(node => node.props?.name === 'direction_ids'); direction.props.onChange({ target: { checked: true } });
  assert.equal(changes[0][0], 'direction_ids'); assert.deepEqual(Array.from(changes[0][1]), ['it']);
  assert.ok(tree.some(node => node.type === 'label' && node.props.children.includes('IT from API')));
});
test('public preview has no saving action, does not prevent fields rendering while API is unavailable', () => {
  let requested; const preview = compile('components/registration-preview.tsx', {
    react: { useState: initial => [initial(), () => {}] }, '@/lib/api': { api: path => { requested = path; } }, '@/lib/registration': helpers,
    './shell': { AppShell: 'shell' }, './ui': { Button: 'button' }, './registration-fields': { RegistrationFields: 'shared-fields' },
    './workflows/common': { useLoad: loader => { loader(); return { loading: false, error: new Error('Synthetic unavailable'), reload: () => {} }; }, LoadState: 'load-state' },
  });
  const tree = nodes(preview.RegistrationPreview({ role: 'mentor' })); assert.equal(requested, '/directions'); assert.ok(tree.some(node => node.type === 'shared-fields'));
  assert.ok(!tree.some(node => node.props?.type === 'submit'));
  let prevented = false; tree.find(node => node.type === 'form').props.onSubmit({ preventDefault: () => { prevented = true; } }); assert.equal(prevented, true);
  assert.ok(tree.some(node => node.props?.href === '/login?role=mentor'));
  for (const relative of ['components/registration-preview.tsx', 'components/registration-fields.tsx', 'lib/registration.ts']) assert.ok(!/localStorage|sessionStorage|fetch\(|mutate\(/.test(file(relative)), relative);
});

function loginFixture(user, role = 'mentor', destination = '/catalog') {
  const navigation = []; const requests = []; const values = ['mentor@example.test', '123456', { challenge_id: 'synthetic' }, undefined]; let cursor = 0;
  const module = compile('app/login/page.tsx', {
    react: { Suspense: 'suspense', useState: () => [values[cursor++], () => {}] },
    'next/navigation': { useRouter: () => ({ push: value => navigation.push(value), refresh: () => {} }), useSearchParams: () => new URLSearchParams({ role, returnTo: destination }) },
    '@/components/shell': { AppShell: 'shell' }, '@/components/ui': { Button: 'button', Field: 'field' }, '@/components/platform-status': { usePlatformStatus: () => ({ health: null }) },
    '@/lib/registration': helpers, '@/lib/api': { api: async path => { requests.push(path); return { authorization_url: 'https://accounts.google.com/o/oauth2/v2/auth?fixture=1' }; } },
    '@/components/workflows/common': { ActionNotice: 'notice', LoadState: 'load-state', useAction: () => ({ run: async work => work() }), useLoad: () => ({ data: { google: true }, loading: false }), safeReturnTo: value => value?.startsWith('/') && !value.startsWith('//') ? value : '/dashboard', mutate: async () => user },
  }, { window: { location: { assign: value => navigation.push(value) } } }, '\nexports.__Login=Login;');
  return { tree: nodes(module.__Login()), navigation, requests };
}
test('actual email verification sends unchosen users to the selected role form', async () => {
  const fixture = loginFixture({ role: 'unchosen', account_status: 'draft' }); await fixture.tree.find(node => node.type === 'form').props.onSubmit({ preventDefault() {} });
  const target = new URL(fixture.navigation[0], 'https://example.test'); assert.equal(target.pathname, '/onboarding'); assert.equal(target.searchParams.get('role'), 'mentor');
});
test('existing users and administrators cannot change their saved role through login hints', async () => {
  for (const role of ['mentee', 'mentor', 'admin']) {
    const fixture = loginFixture({ role, account_status: 'draft' }, 'mentor'); await fixture.tree.find(node => node.type === 'form').props.onSubmit({ preventDefault() {} });
    assert.equal(new URL(fixture.navigation[0], 'https://example.test').searchParams.has('role'), false);
  }
  const active = loginFixture({ role: 'mentee', account_status: 'active' }); await active.tree.find(node => node.type === 'form').props.onSubmit({ preventDefault() {} }); assert.equal(active.navigation[0], '/catalog');
});
test('active participants with newly incomplete profiles return to onboarding after OTP', async () => {
  const fixture = loginFixture({ role: 'mentor', account_status: 'active', profile_completed: false }, 'mentee');
  await fixture.tree.find(node => node.type === 'form').props.onSubmit({ preventDefault() {} });
  const target = new URL(fixture.navigation[0], 'https://example.test'); assert.equal(target.pathname, '/onboarding'); assert.equal(target.searchParams.has('role'), false);
});
test('Google start passes the same validated role and return destination to backend OAuth state', async () => {
  const fixture = loginFixture({ role: 'unchosen' }); await fixture.tree.find(node => node.props?.children === 'Войти через Google').props.onClick();
  const query = new URL(fixture.requests[0], 'https://example.test'); assert.equal(query.searchParams.get('role'), 'mentor'); assert.equal(query.searchParams.get('return_to'), '/catalog');
  const invalid = loginFixture({}, 'admin', '//evil.test'); await invalid.tree.find(node => node.props?.children === 'Войти через Google').props.onClick(); const invalidQuery = new URL(invalid.requests[0], 'https://example.test'); assert.equal(invalidQuery.searchParams.has('role'), false); assert.equal(invalidQuery.searchParams.get('return_to'), '/dashboard');
});
test('all new registration copy has nonempty Kazakh and English equivalents', () => {
  const { registrationTranslations } = compile('lib/registration-translations.ts'); assert.ok(Object.keys(registrationTranslations).length >= 55);
  for (const [russian, alternatives] of Object.entries(registrationTranslations)) { assert.ok(russian); assert.equal(alternatives.length, 2); for (const value of alternatives) assert.ok(typeof value === 'string' && value.trim()); }
});
test('all public registration routes reuse the form and onboarding excludes the deferred AI UI', () => {
  for (const role of ['mentor', 'mentee']) assert.ok(file(`app/register/${role}/page.tsx`).includes(`<RegistrationPreview role="${role}" />`));
  const onboarding = file('app/onboarding/page.tsx'); assert.ok(onboarding.includes('<RegistrationFields')); assert.ok(!/AITextAssistant|AIReviewPreference|ai-assistant/.test(onboarding));
  assert.ok(onboarding.includes('registrationValues(draft)')); assert.ok(onboarding.includes('profilePendingChanges(draft, load.data.user)'));
  assert.ok(onboarding.includes('<fieldset disabled={action.busy}'));
});

test('dirty comparison normalizes server text, links and defaults while excluding acceptance timestamp', () => {
  const saved = { ...mentor, evidence_urls: ['https://example.test/'], phone: null, mentor_commitment_accepted_at: '2000-01-01T00:00:00Z' };
  const draft = { ...saved, evidence_urls: ['  https://example.test  ', ''], phone: '', full_name: ` ${saved.full_name} `, mentor_commitment_accepted_at: null };
  assert.equal(helpers.profilePendingChanges(draft, saved), false);
  for (const change of [{ organization: 'Changed workplace' }, { phone: '+7' }, { capacity: 0 }, { capacity: undefined }, { mentor_commitment: false }]) assert.equal(helpers.profilePendingChanges({ ...draft, ...change }, saved), true);
});

function onboardingFixture(initialUser, suggestion = '') {
  let data = { user: initialUser, directions, documents: [], notifications: [], requirements: { documents_configured: true, required_version_ids: [], unaccepted_version_ids: [] } };
  const values = []; const effects = []; let cursor = 0; let dirty = false; let queued = []; let tree;
  const calls = [];
  const react = {
    useState(initial) { const position = cursor++; if (!(position in values)) values[position] = typeof initial === 'function' ? initial() : initial; return [values[position], next => { values[position] = typeof next === 'function' ? next(values[position]) : next; dirty = true; }]; },
    useEffect(callback, deps) { const position = cursor++; const previous = effects[position]; if (!previous || deps.some((value, index) => value !== previous[index])) { effects[position] = deps; queued.push(callback); } },
  };
  const module = compile('app/onboarding/page.tsx', {
    react, '@/lib/api': { api: async () => {} }, '@/lib/registration': helpers, '@/components/shell': { AppShell: 'shell' }, '@/components/ui': { Badge: 'badge', Button: 'button', Field: 'field' },
    '@/components/platform-status': { usePlatformStatus: () => ({ health: { demo_mode: false } }) }, '@/components/registration-fields': { RegistrationFields: 'shared-fields' },
    '@/components/workflows/common': { ActionNotice: 'notice', LoadState: 'load-state', useAction: () => ({ busy: false, run: async work => work() }), safeReturnTo: () => '/dashboard', statusText: value => value,
      useLoad: () => ({ data, loading: false, reload: async () => {} }), mutate: async (path, body) => { calls.push({ path, body }); if (path === '/me/profile') { const saved = { ...data.user, ...body, profile_completed: true }; data = { ...data, user: saved }; return saved; } return {}; } },
  }, { window: { location: { search: suggestion ? `?role=${suggestion}` : '' }, dispatchEvent: () => {} } });
  function render() { for (let pass = 0; pass < 10; pass++) { cursor = 0; dirty = false; queued = []; tree = nodes(module.default()); for (const effect of queued) effect(); if (!dirty) return; } throw new Error('Onboarding did not settle'); }
  function submit() { return tree.find(node => node.props?.children === 'Сохранить согласия и отправить анкету'); }
  render();
  return { calls, submit, nodes: () => tree, update(name, value) { tree.find(node => node.type === 'shared-fields').props.update(name, value); render(); }, refresh(user = data.user) { data = { ...data, user }; render(); }, async save() { await tree.find(node => node.type === 'form').props.onSubmit({ preventDefault() {} }); render(); } };
}

test('unsaved edits block document submission, stay blocked through refresh and unlock only after save', async () => {
  const user = { ...mentor, id: 'synthetic', account_status: 'draft', profile_completed: true, mentor_commitment_accepted_at: '2026-01-01T00:00:00Z' };
  const fixture = onboardingFixture(user); assert.equal(Boolean(fixture.submit().props.disabled), false);
  fixture.update('organization', 'Changed organization'); assert.equal(Boolean(fixture.submit().props.disabled), true);
  await assert.rejects(fixture.submit().props.onClick(), /Сначала сохраните/); assert.equal(fixture.calls.length, 0);
  fixture.refresh({ ...user }); assert.equal(Boolean(fixture.submit().props.disabled), true); assert.ok(fixture.nodes().some(node => node.props?.children === 'Сначала сохраните изменения анкеты.'));
  await fixture.save(); assert.equal(fixture.calls.length, 1); assert.equal(fixture.calls[0].path, '/me/profile'); assert.equal(fixture.calls[0].body.organization, 'Changed organization'); assert.equal(Boolean(fixture.submit().props.disabled), false);
  await fixture.submit().props.onClick(); assert.equal(fixture.calls.at(-1).path, '/me/submit-registration');
});

test('onboarding respects server role changes and resets stale mentor commitment from the previous role', () => {
  const user = { ...mentor, id: 'synthetic', account_status: 'draft', profile_completed: true };
  const fixture = onboardingFixture(user, 'mentor'); fixture.update('organization', 'Unsaved old mentor edit');
  fixture.refresh({ ...user, role: 'mentee', organization: '', mentor_commitment: false, birth_date: '2002-01-01' });
  const draft = fixture.nodes().find(node => node.type === 'shared-fields').props.draft; assert.equal(draft.role, 'mentee'); assert.equal(draft.organization, ''); assert.equal(draft.mentor_commitment, false);
});

test('clearing mentor capacity keeps the field blank and blocks submission until a valid value is saved', async () => {
  const changes = [];
  const capacity = fieldNodes(mentor, false, (...values) => changes.push(values)).find(node => node.props?.name === 'capacity');
  capacity.props.onChange({ target: { value: '' } });
  assert.equal(changes[0][0], 'capacity'); assert.equal(changes[0][1], undefined);
  const blank = fieldNodes({ ...mentor, capacity: undefined }).find(node => node.props?.name === 'capacity'); assert.equal(blank.props.value, '');
  const fixture = onboardingFixture({ ...mentor, id: 'synthetic', account_status: 'draft', profile_completed: true });
  fixture.update('capacity', undefined); assert.equal(Boolean(fixture.submit().props.disabled), true);
  await assert.rejects(fixture.submit().props.onClick(), /Сначала сохраните/);
  await assert.rejects(fixture.save(), /число менти от 0 до 50/); assert.equal(fixture.calls.length, 0);
  fixture.update('capacity', 0); await fixture.save(); assert.equal(fixture.calls[0].body.capacity, 0); assert.equal(Boolean(fixture.submit().props.disabled), false);
});
