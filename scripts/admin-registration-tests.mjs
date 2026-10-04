import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import vm from 'node:vm';
import {test} from 'node:test';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const ts = createRequire(path.join(root, 'apps/admin/package.json'))('typescript');
const source = readFileSync(path.join(root, 'apps/admin/src/app/registrations/page.tsx'), 'utf8');
function screen(states = []) {
  const jsx = (type, props) => ({type, props});
  let cursor = 0;
  const queries = [];
  const module = {exports: {}};
  const helpers = {
    useState: initial => [states[cursor++] ?? initial, () => {}],
    api: () => {}, mutate: () => {},
    safeUrl: value => {try {return ['https:', 'http:'].includes(new URL(value).protocol) ? value : undefined;} catch {return undefined;}},
    useLocale: () => ({locale: 'ru', t: key => key, label: value => value}),
    dateTime: value => value, formatDate: value => value,
    useAction: () => ({busy: false, run: () => {}}),
    useLoad: () => ({data: [{id: 'd1', name_ru: 'IT'}], reload: () => {}}),
    usePaged: query => {queries.push(query); return {data: [], reload: () => {}, page: 0, setPage: () => {}};},
    AdminShell: 'AdminShell', Badge: 'Badge', Button: 'Button', Field: 'Field',
    ActionNotice: 'ActionNotice', DataState: 'DataState', NoData: 'NoData', Pager: 'Pager',
  };
  const code = ts.transpileModule(source + '\nexports.Review=Review;exports.Registrations=Registrations;', {compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  }}).outputText;
  vm.runInNewContext(code, {module, exports: module.exports, URLSearchParams,
    require: name => name === 'react/jsx-runtime' ? {jsx, jsxs: jsx, Fragment: 'Fragment'} : helpers});
  return {...module.exports, queries};
}
function nodes(tree) {return Array.isArray(tree) ? tree.flatMap(nodes) : tree && typeof tree === 'object' ? [tree, ...nodes(tree.props?.children)] : [];}
function text(tree) {return Array.isArray(tree) ? tree.map(text).join(' ') : tree && typeof tree === 'object' ? text(tree.props?.children) : tree == null ? '' : String(tree);}
const mentor = {id: 'synthetic', full_name: 'Synthetic Mentor', role: 'mentor', email: 'synthetic@example.test',
  phone: '+70000000000', city: 'Oral', timezone: 'Asia/Oral', organization: 'Synthetic university',
  direction_ids: ['d1'], bio: 'Synthetic biography', expertise: 'Synthetic experience', capacity: 0,
  mentor_commitment: true, mentor_commitment_accepted_at: '2026-10-04T10:00:00Z', profile_completed: true,
  evidence_urls: ['https://example.test/evidence', 'javascript:alert(1)']};
const render = user => screen().Review({user, directions: [{id: 'd1', name_ru: 'IT'}], refresh: async () => {}});

test('administrator sees phone, organization, direction name and experience', () => {
  const visible = text(render(mentor));
  for (const expected of [mentor.phone, mentor.organization, 'IT', mentor.expertise]) assert.ok(visible.includes(expected));
});
test('mentor commitment shows its server acceptance time', () => {
  const visible = text(render(mentor));
  assert.ok(visible.includes('commitmentConfirmed'));
  assert.ok(visible.includes(mentor.mentor_commitment_accepted_at));
});
test('missing commitment time is never presented as confirmed', () => {
  assert.ok(text(render({...mentor, mentor_commitment_accepted_at: null})).includes('commitmentMissing'));
});
test('mentee does not show mentor commitment and retains birth date', () => {
  const visible = text(render({...mentor, role: 'mentee', birth_date: '2000-01-01'}));
  assert.ok(!visible.includes('mentorCommitment'));
  assert.ok(visible.includes('2000-01-01'));
});
test('missing optional contact and organization are explicit', () => {
  assert.equal(text(render({...mentor, role: 'mentee', phone: '', organization: ''})).split('notProvided').length - 1, 2);
});
test('zero mentor capacity remains visible', () => {assert.match(text(render(mentor)), /capacity\s*:\s*0/);});
test('only valid supporting URLs become external links', () => {
  const links = nodes(render(mentor)).filter(node => node.type === 'a');
  assert.equal(links.length, 1);
  assert.equal(links[0].props.rel, 'noopener noreferrer');
});
test('incomplete profile cannot be approved in the UI', () => {
  const approve = nodes(render({...mentor, profile_completed: false})).find(node => node.type === 'Button' && node.props.children === 'approve');
  assert.equal(approve.props.disabled, true);
});
test('filters are sent to the paginated endpoint and encode direction IDs', () => {
  const page = screen(['mentor', 'direction&role=admin']); page.Registrations();
  const query = new URLSearchParams(page.queries[0].split('?')[1]);
  assert.equal(query.get('role'), 'mentor');
  assert.equal(query.get('direction_id'), 'direction&role=admin');
  assert.equal(query.getAll('role').length, 1);
});
test('all roles and directions do not add filter parameters', () => {
  const page = screen(); page.Registrations();
  assert.equal(page.queries[0], '/admin/registrations?');
});
