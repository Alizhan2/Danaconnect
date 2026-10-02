import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
import vm from 'node:vm';
import {test} from 'node:test';

// Deterministic source/component tests only. No browser, real accounts or providers.
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const ts=createRequire(path.join(root,'apps/web/package.json'))('typescript');
function load(file,modules={},globals={}) {
  const module={exports:{}};
  const jsx=(type,props)=>({type,props});
  const defaults={react:{useState:value=>[value,()=>{}]},'react/jsx-runtime':{jsx,jsxs:jsx}};
  const code=ts.transpileModule(readFileSync(path.join(root,'apps/web/src',file),'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
  vm.runInNewContext(`(function(require,exports,module){${code}\n})`,{Blob,URL,URLSearchParams,AbortSignal,Response,Date,...globals})(name=>{
    if(Object.hasOwn(modules,name))return modules[name];
    if(Object.hasOwn(defaults,name))return defaults[name];
    throw new Error(`Unexpected dependency: ${name}`);
  },module.exports,module);
  return module.exports;
}
function nodes(tree){if(Array.isArray(tree))return tree.flatMap(nodes);return tree&&typeof tree==='object'?[tree,...nodes(tree.props?.children)]:[tree];}
function captureAction(){
  const state={busy:false,success:'',error:''};
  state.run=(work,message)=>state.pending=(async()=>{try{await work();state.success=message;return true;}catch(error){state.error=error.message;return false;}})();
  return state;
}
function browser(failure=''){
  const steps=[];const timers=[];
  const anchor={click(){steps.push('click');if(failure==='click')throw new Error('Browser blocked');},remove(){steps.push('remove');}};
  return {steps,timers,anchor,globals:{
    URL:{createObjectURL:blob=>{steps.push(['create',blob]);return 'blob:fixture';},revokeObjectURL:url=>steps.push(['revoke',url])},
    document:{createElement:()=>{if(failure==='create')throw new Error('No document');return anchor;},body:{appendChild:a=>{assert.equal(a,anchor);steps.push('append');}}},
    setTimeout:(callback,delay)=>timers.push({callback,delay}),
  }};
}
test('download uses an attached hidden anchor and retains the URL until a later timer',()=>{
  const fixture=browser();const {downloadBlob}=load('lib/download.ts',{},fixture.globals);const blob=new Blob(['Привет']);
  downloadBlob(blob,'fixture.json');
  assert.equal(fixture.anchor.href,'blob:fixture');assert.equal(fixture.anchor.download,'fixture.json');assert.equal(fixture.anchor.hidden,true);
  assert.deepEqual(fixture.steps,[['create',blob],'append','click','remove']);assert.equal(fixture.timers[0].delay,10000);
  fixture.timers[0].callback();assert.deepEqual(fixture.steps.at(-1),['revoke','blob:fixture']);
});
for(const failure of ['create','click'])test(`download releases its URL even when ${failure} fails`,()=>{
  const fixture=browser(failure);const {downloadBlob}=load('lib/download.ts',{},fixture.globals);
  assert.throws(()=>downloadBlob(new Blob(['fixture']),'fixture.json'));
  assert.equal(fixture.timers.length,1);fixture.timers[0].callback();assert.deepEqual(fixture.steps.at(-1),['revoke','blob:fixture']);
  if(failure==='click')assert.ok(fixture.steps.includes('remove'));
});
function privacy(locale,payload){
  const action=captureAction();const downloads=[];const dates=[];const calls=[];let loader;
  const requests={items:[{id:'request-1',kind:'export',status:'pending',created_at:'2026-01-01T12:00:00Z'}],user:{timezone:'Europe/London'}};
  const page=load('app/privacy/page.tsx',{
    '@/lib/api':{api:async p=>{calls.push(p);return p==='/me/data-export'?payload:p==='/auth/me'?requests.user:requests.items;}},
    '@/lib/download':{downloadBlob:(blob,name)=>downloads.push({blob,name})},'@/lib/i18n':{useLocale:()=>({locale})},
    '@/components/shell':{AppShell:'shell'},'@/components/ui':{Badge:'badge',Button:'button',EmptyState:'empty',Field:'field'},
    '@/components/workflows/common':{useAction:()=>action,useLoad:callback=>{loader=callback;return {data:requests,reload:async()=>{}};},dateTime:(...args)=>{dates.push(args);return 'fixture date';}},
  }).default();
  return {action,downloads,dates,calls,loader,button:nodes(page).find(n=>n?.type==='button'&&n.props.onClick)};
}
for(const locale of ['ru','kk','en'])test(`privacy creates UTF-8 JSON and reports prepared, never saved (${locale})`,async()=>{
  const payload={exported_at:'2026-01-01T12:00:00Z',account:{id:'fixture-user',full_name:'Әсем Тест'},messages_authored:[]};
  const fixture=privacy(locale,payload);fixture.button.props.onClick();await fixture.action.pending;
  assert.equal(fixture.downloads.length,1);const {blob,name}=fixture.downloads[0];assert.equal(name,'danaconnect-my-data.json');assert.equal(blob.type,'application/json;charset=utf-8');
  assert.deepEqual(JSON.parse(await blob.text()),payload);assert.ok(fixture.action.success);assert.doesNotMatch(fixture.action.success,/сохран|сақтал|saved/i);
});
for(const payload of [null,{}, {account:null,exported_at:'2026-01-01'}])test(`privacy rejects an invalid export response ${JSON.stringify(payload)}`,async()=>{
  const fixture=privacy('ru',payload);fixture.button.props.onClick();await fixture.action.pending;assert.equal(fixture.downloads.length,0);assert.equal(fixture.action.success,'');assert.ok(fixture.action.error);
});
test('privacy loads account and requests together and formats the history in the account timezone',async()=>{
  const fixture=privacy('en',{});await fixture.loader();assert.deepEqual(fixture.calls,['/me/privacy-requests','/auth/me']);
  assert.deepEqual(fixture.dates,[['2026-01-01T12:00:00Z','Europe/London','en']]);
});
function calendar(locale,response){
  const action=captureAction();const downloads=[];const calls=[];
  class ApiError extends Error {constructor(status,message){super(message);this.status=status;}}
  const {CalendarExport}=load('components/calendar-export/index.tsx',{
    '@/lib/api':{ApiError},'@/lib/download':{downloadBlob:(blob,name)=>downloads.push({blob,name})},'@/lib/i18n':{useLocale:()=>({locale})},
    '@/components/ui':{Button:'button',Field:'field'},'@/components/workflows/common':{useAction:()=>action,ActionNotice:'notice'},
  },{fetch:async(...args)=>{calls.push(args);return response;}});
  const tree=CalendarExport({user:{role:'mentee'}});return {action,downloads,calls,CalendarExport,button:nodes(tree).find(n=>n?.type==='button')};
}
for(const locale of ['ru','kk','en'])test(`calendar requests an authenticated snapshot and produces ICS (${locale})`,async()=>{
  const body='BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n';
  const fixture=calendar(locale,new Response(body,{headers:{'Content-Type':'text/calendar; charset=utf-8'}}));fixture.button.props.onClick();await fixture.action.pending;
  const [url,options]=fixture.calls[0];assert.ok(url.startsWith('/api/v1/me/calendar.ics?'));assert.equal(options.credentials,'include');assert.equal(options.cache,'no-store');assert.equal(options.headers['Accept-Language'],locale);
  const params=new URL(url,'http://fixture.test').searchParams;assert.equal(params.get('include_cancelled'),'false');assert.equal(new Date(params.get('ends_before'))-new Date(params.get('starts_after')),90*86400000);
  assert.equal(fixture.downloads[0].name,'danaconnect-calendar.ics');assert.equal(await fixture.downloads[0].blob.text(),body);assert.doesNotMatch(fixture.action.success,/сохран|сақтал|saved/i);
  assert.equal(fixture.CalendarExport({user:{role:'admin'}}),null);
});
for(const response of [new Response('<html>Unexpected proxy page</html>',{headers:{'Content-Type':'text/html'}}),new Response('{"detail":"Fixture denied"}',{status:403,headers:{'Content-Type':'application/json'}})])test('calendar rejects a non-calendar or denied response',async()=>{
  const fixture=calendar('en',response);fixture.button.props.onClick();await fixture.action.pending;assert.equal(fixture.downloads.length,0);assert.equal(fixture.action.success,'');assert.ok(fixture.action.error);
});
