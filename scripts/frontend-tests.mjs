import assert from 'node:assert/strict';
import {readFileSync, existsSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
import vm from 'node:vm';
import {test} from 'node:test';

// Small deterministic checks of the actual TypeScript source. No production requests,
// OTP generation, enrollment credentials, or additional test dependencies are used.
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const ts=createRequire(path.join(root,'apps/web/package.json'))('typescript');
function runtime(app, overrides={}) {
  const effects=[];
  let stateIndex=0;
  const react={
    createContext:value=>({value,Provider:'provider'}), createElement:(type,props)=>({type,props}),
    useState:value=>[overrides.states&&stateIndex<overrides.states.length?overrides.states[stateIndex++]:overrides.locale??value,()=>{}],useEffect:effect=>effects.push(effect),
    useCallback:value=>value,useMemo:callback=>callback(),useRef:value=>({current:value}),
    useContext:context=>context.value,
  };
  const context=vm.createContext({URL,Headers,Response,FormData,AbortSignal,AbortController,Error,console,
    process:{env:{NEXT_PUBLIC_ADMIN_BASE_PATH:'/admin'},cwd:()=>path.join(root,`apps/${app}`)},Event,URLSearchParams,
    document:{documentElement:{lang:'ru'}},localStorage:{getItem:()=>null,setItem:()=>{}},...overrides});
  const cache=new Map();
  function load(relative) {
    const filename=path.resolve(root,`apps/${app}/src`,relative);
    if(cache.has(filename))return cache.get(filename).exports;
    const module={exports:{}};cache.set(filename,module);
    const extra=overrides.privateFunctions?.[relative]?.map(name=>`\nexports.__${name}=${name};`).join('')??'';
    const code=ts.transpileModule(readFileSync(filename,'utf8')+extra,{compilerOptions:{
      target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,
    }}).outputText;
    function require(name) {
      if(overrides.modules&&Object.hasOwn(overrides.modules,name))return overrides.modules[name];
      if(name==='react')return react;
      if(name==='react/jsx-runtime')return {jsx:react.createElement,jsxs:react.createElement,Fragment:'fragment'};
      if(name.startsWith('next/')||name==='lucide-react')return {};
      const base=name.startsWith('@/')?path.resolve(root,`apps/${app}/src`,name.slice(2)):
        name.startsWith('.')?path.resolve(path.dirname(filename),name):null;
      if(!base)throw new Error(`Unexpected dependency ${name}`);
      const candidate=['.ts','.tsx','/index.ts','/index.tsx'].map(suffix=>base+suffix).find(existsSync);
      if(!candidate)throw new Error(`Missing dependency ${name}`);
      return load(path.relative(path.resolve(root,`apps/${app}/src`),candidate));
    }
    vm.runInContext(`(function(exports,require,module){${code}\n})`,context,{filename})(module.exports,require,module);
    return module.exports;
  }
  return {load,effects,context};
}
function nodes(tree) {
  if(Array.isArray(tree))return tree.flatMap(nodes);
  if(tree&&typeof tree==='object')return [tree,...nodes(tree.props?.children)];
  return tree===undefined||tree===null?[]:[tree];
}
function sourceFunction(app,file,name) {
  const filename=path.resolve(root,`apps/${app}/src`,file);
  const source=ts.createSourceFile(filename,readFileSync(filename,'utf8'),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
  const node=source.statements.find(item=>ts.isFunctionDeclaration(item)&&item.name?.text===name);
  assert.ok(node,`Missing source function ${name}`);
  const js=ts.transpileModule(node.getText(source),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
  return vm.runInNewContext(`${js};${name}`,{URL,process:{env:{NEXT_PUBLIC_ADMIN_BASE_PATH:'/admin'}}});
}

test('calendar keeps recurring forms mounted during refresh after initial loading',()=>{
  for(const [data,expectedLoading] of [[undefined,true],[{user:{role:'mentor',timezone:'Asia/Oral'},slots:[],bookings:[],participations:[],mentors:[]},false]]){
    const rt=runtime('web',{modules:{
      '@/components/workflows/common':{LoadState:'load-state',useAction:()=>({busy:false}),useLoad:()=>({data,loading:true,error:undefined,reload:()=>{}})},
      '@/components/calendar-rules':{RecurringAvailability:'recurring',MeetingControls:'meeting'},
      '@/components/calendar-export':{CalendarExport:'export'},
    }});
    const tree=nodes(rt.load('app/calendar/page.tsx').default());
    assert.equal(tree.find(node=>node?.type==='load-state').props.loading,expectedLoading);
    if(data)assert.ok(tree.some(node=>node?.type==='recurring'));
  }
});

test('mentor evidence requires valid HTTP(S) links and at most ten',()=>{
  const validate=runtime('web').load('lib/registration.ts').evidenceProblem;
  for(const values of [[],['  '],['аавва'],['javascript:alert(1)'],['https://x.test/'+ 'a'.repeat(2083)],Array(11).fill('https://example.test')])assert.ok(validate(values));
  for(const values of [['https://github.com/username'],['  https://example.test/portfolio  ',''],['http://example.test'],Array(10).fill('https://example.test')])assert.equal(validate(values),'');
});
test('admin return path accepts only local admin routes',()=>{
  const safe=sourceFunction('admin','app/login/page.tsx','returnPath');
  for(const value of [null,'https://evil.test','//evil.test','/\\evil.test','/api/v1/admin','/unknown','/users\n'])assert.equal(safe(value),'/');
  assert.equal(safe('/admin/users?status=active'),'/users?status=active');
  assert.equal(safe('/admin/operations'),'/operations');
});
test('web navigation rejects unsafe return URLs and login loops',()=>{
  const {safeReturnTo,safeUrl}=runtime('web').load('components/workflows/common.tsx');
  for(const value of [null,'//evil.test','https://evil.test','/login','/api/v1/auth/me','/\\evil.test'])assert.equal(safeReturnTo(value),'/dashboard');
  assert.equal(safeReturnTo('/catalog?direction=IT#results'),'/catalog?direction=IT#results');
  assert.equal(safeUrl('javascript:alert(1)'),undefined);
  assert.equal(safeUrl('https://example.test'), 'https://example.test/');
});
test('admin external links reject credentials and non-web protocols',()=>{
  const {safeUrl}=runtime('admin').load('lib/api.ts');
  for(const value of ['javascript:alert(1)','https://user:pass@example.test',null])assert.equal(safeUrl(value),undefined);
  assert.equal(safeUrl('https://example.test'),'https://example.test/');
});
test('web onboarding, readiness and evidence messages translate into all three locales',()=>{
  const {translatePhrase,dictionaries}=runtime('web').load('lib/i18n.ts');
  const messages=['Обязательные документы ещё не опубликованы командой платформы. Отправка анкеты станет доступна после публикации.',
    'Прочитайте обязательные документы ниже и отметьте подтверждение ознакомления с каждым из них.',
    'Добавьте хотя бы одну ссылку на ваш опыт.','Выберите от 1 до 10 доступных направлений.'];
  for(const phrase of messages){assert.equal(translatePhrase(phrase,'ru'),phrase);for(const locale of ['kk','en']){const translated=translatePhrase(phrase,locale);assert.notEqual(translated,phrase);assert.equal(translatePhrase(translated,'ru'),phrase);}}
  const keys=Object.keys(dictionaries.ru);for(const locale of ['kk','en']){assert.deepEqual(Object.keys(dictionaries[locale]),keys);for(const key of keys)assert.ok(dictionaries[locale][key]);}
});
test('admin MFA and navigation labels exist in all three locales',()=>{
  for(const locale of ['ru','kk','en']){
    const rt=runtime('admin',{locale});const module=rt.load('lib/i18n.tsx');
    const provider=module.LocaleProvider({children:null});const {t}=provider.props.value;
    for(const label of ['mfa','mfaCode','mfaExpired','mfaInvalid','mfaTimeLeft','directions','documents','registrations','operations'])assert.ok(t(label));
  }
});

test('public login shows only the verified enrollment QR and retains manual setup if the image fails',()=>{
  const manualKey='SYNTHETIC-SETUP-KEY';
  const dataUrl='data:image/svg+xml;base64,PHN2Zy8+';
  const mfa={mfa_required:true,mfa_challenge_id:'test-challenge',method:'totp',expires_in:300,deadline:Date.now()+300000};
  for(const [qr,failed,expectedImage,expectedKey] of [
    [undefined,false,false,false],
    [dataUrl,false,true,true],
    [dataUrl,true,false,true],
    ['https://example.invalid/qr.png',false,false,true],
  ]){
    const response=qr?{...mfa,enrollment:{qr_data_url:qr,manual_entry_key:manualKey}}:mfa;
    const rt=runtime('web',{
      states:['admin@example.test','',{challenge_id:'test-email'},response,false,failed],
      privateFunctions:{'app/login/page.tsx':['Login']},
      modules:{
        'next/navigation':{useRouter:()=>({}),useSearchParams:()=>new URLSearchParams()},
        '@/components/shell':{AppShell:'shell'},
        '@/components/platform-status':{usePlatformStatus:()=>({})},
        '@/lib/i18n':{useLocale:()=>({locale:'ru',t:{},tr:value=>value})},
        '@/components/workflows/common':{useAction:()=>({}),useLoad:()=>({}),safeReturnTo:()=>'/dashboard'},
      },
    });
    const tree=nodes(rt.load('app/login/page.tsx').__Login());
    const img=tree.find(node=>node?.type==='img');
    assert.equal(Boolean(img),expectedImage);
    if(img){assert.equal(img.props.src,dataUrl);assert.equal(img.props.referrerPolicy,'no-referrer');}
    assert.equal(tree.includes(manualKey),expectedKey);
  }
});
test('admin locale settings keep working when browser storage is blocked',()=>{
  const rt=runtime('admin',{localStorage:{getItem:()=>{throw new Error('Storage blocked');},setItem:()=>{throw new Error('Storage blocked');}}});
  rt.load('lib/i18n.tsx').LocaleProvider({children:null});
  for(const effect of rt.effects)assert.doesNotThrow(effect);
});
test('admin MFA component shows expiry and disables expired confirmation',()=>{
  for(const remaining of [0,300]){
    const rt=runtime('admin',{states:['admin@example.test','', {challenge_id:'email-challenge'},
      {mfa_required:true,mfa_challenge_id:'mfa-challenge',method:'totp',expires_in:300,deadline:Date.now()+300000},remaining],
      privateFunctions:{'app/login/page.tsx':['Login']},modules:{
        'next/navigation':{useRouter:()=>({push:()=>{},refresh:()=>{}}),useSearchParams:()=>new URLSearchParams()},
        '@/components/common':{useAction:()=>({busy:false,error:undefined,clear:()=>{},run:()=>{}}),webUrl:'http://127.0.0.1:3100'},
      }});
    const tree=nodes(rt.load('app/login/page.tsx').__Login());
    const submit=tree.find(node=>node?.props?.type==='submit');
    assert.equal(submit.props.disabled,remaining===0);
    if(!remaining)assert.ok(tree.some(node=>typeof node==='string'&&node.startsWith('Время подтверждения истекло.')));
  }
});
test('onboarding component blocks unconfigured or unchecked required documents',()=>{
  for(const [configured,checked,expectedDisabled] of [[false,[],true],[true,[],true],[true,['doc-1'],false]]){
    const user={id:'fixture-user',role:'mentor',account_status:'draft',profile_completed:true,direction_ids:['direction-1'],full_name:'Fixture mentor',timezone:'Asia/Oral',city:'Oral',phone:'+77000000000',organization:'Fixture organization',mentor_commitment:true,bio:'Fixture introduction',expertise:'Fixture expertise',capacity:3,evidence_urls:['https://example.test']};
    const data={user,directions:[{id:'direction-1',name_ru:'IT'}],documents:[{id:'doc-1',required:true,accepted:false,title:'Fixture rules',version:1}],notifications:[],requirements:{documents_configured:configured,unaccepted_version_ids:['doc-1'],required_version_ids:['doc-1']}};
    const rt=runtime('web',{states:[user,checked],modules:{
      '@/components/workflows/common':{useAction:()=>({busy:false}),useLoad:()=>({data,loading:false,reload:()=>{}}),safeReturnTo:()=>'/dashboard',statusText:value=>value},
      '@/components/platform-status':{usePlatformStatus:()=>({health:{demo_mode:false}})},
      '@/components/ai-assistant':{},
    }});
    const tree=nodes(rt.load('app/onboarding/page.tsx').default());
    const submit=tree.find(node=>node?.props?.children==='Сохранить согласия и отправить анкету');
    assert.ok(submit);assert.equal(Boolean(submit.props.disabled),expectedDisabled);
    if(!configured)assert.ok(tree.some(node=>typeof node==='string'&&node.startsWith('Обязательные документы ещё не опубликованы')));
  }
});
test('web sidebar exposes admin navigation only to administrators',()=>{
  for(const role of ['unchosen','mentor','mentee','admin']){
    const rt=runtime('web',{states:[false,{role,full_name:'Fixture user'}],modules:{
      'next/navigation':{usePathname:()=>'/onboarding'},
      '@/components/platform-status':{usePlatformStatus:()=>({health:{demo_mode:false}})},
      './notification-center':{},
    }});
    const tree=nodes(rt.load('components/shell.tsx').AppShell({children:null,dashboard:true}));
    assert.equal(tree.some(node=>node?.props?.href==='/admin'),role==='admin');
  }
});
test('web shell refreshes its user after profile save and removes the listener',async()=>{
  const events=new Map();const calls=[];
  const rt=runtime('web',{modules:{
    'next/navigation':{usePathname:()=>'/onboarding'},
    '@/lib/api':{api:async path=>{calls.push(path);return {role:'mentor'};}},
    '@/components/platform-status':{usePlatformStatus:()=>({health:{demo_mode:false}})},
    './notification-center':{},
  },window:{addEventListener:(name,callback)=>events.set(name,callback),removeEventListener:(name,callback)=>{if(events.get(name)===callback)events.delete(name);}}});
  rt.load('components/shell.tsx').AppShell({children:null,dashboard:true});
  const cleanup=rt.effects.at(-1)();
  assert.equal(calls.length,1);events.get('danaconnect:profile-updated')();assert.equal(calls.length,2);
  cleanup();assert.equal(events.size,0);
});
test('profile save publishes its refresh event only after a successful API update',async()=>{
  for(const fail of [false,true]){
    const steps=[];const user={id:'fixture-user',role:'mentor',account_status:'draft',profile_completed:true,direction_ids:['direction-1'],full_name:'Fixture mentor',timezone:'Asia/Oral',city:'Oral',phone:'+77000000000',organization:'Fixture organization',mentor_commitment:true,bio:'Fixture introduction',expertise:'Fixture expertise',capacity:3,evidence_urls:['https://example.test']};
    const data={user,directions:[{id:'direction-1',name_ru:'IT'}],documents:[],notifications:[],requirements:{documents_configured:false,unaccepted_version_ids:[],required_version_ids:[]}};
    const rt=runtime('web',{states:[user,[]],window:{location:{search:''},dispatchEvent:event=>steps.push(event.type)},modules:{
      '@/components/workflows/common':{useAction:()=>({busy:false,run:async work=>work()}),useLoad:()=>({data,loading:false,reload:async()=>steps.push('reload')}),safeReturnTo:()=>'/dashboard',statusText:value=>value,mutate:async(path,body,method)=>{steps.push(`${method} ${path}`);if(fail)throw new Error('Expected API failure');}},
      '@/components/platform-status':{usePlatformStatus:()=>({health:{demo_mode:false}})},'@/components/ai-assistant':{},
    }});
    const form=nodes(rt.load('app/onboarding/page.tsx').default()).find(node=>node?.type==='form');
    if(fail){await assert.rejects(form.props.onSubmit({preventDefault:()=>{}}));assert.deepEqual(steps,['PUT /me/profile']);}
    else{await form.props.onSubmit({preventDefault:()=>{}});assert.deepEqual(steps,['PUT /me/profile','danaconnect:profile-updated','reload']);}
  }
});
test('opted-in directions reads recover from temporary server and network failures',async()=>{
  for(const first of ['network',500,502,503,504]){
    let calls=0;
    const rt=runtime('web',{setTimeout:callback=>setTimeout(callback,0),fetch:async(url,options)=>{
      calls++;assert.equal(options.retry,undefined);
      if(calls===1){if(first==='network')throw new Error('Disconnected');return Response.json({detail:'Unavailable'},{status:first});}
      return Response.json([{id:'live-direction'}]);
    }});
    assert.equal((await rt.load('lib/api.ts').api('/directions',{retry:true}))[0].id,'live-direction');
    assert.equal(calls,2);
  }
});
test('a tablet without AbortSignal.any can load directions and cancel a pending read', async () => {
  const caller = new AbortController();
  const deadline = new AbortController();
  let pending = false;
  const rt = runtime('web', {
    AbortSignal: { timeout: () => deadline.signal },
    fetch: async (url, { signal }) => {
      if (!pending) return Response.json([{ id: 'test-direction' }]);
      return new Promise((resolve, reject) => {
        signal.addEventListener('abort', () => reject(new Error('Aborted')), { once: true });
      });
    },
  });
  const { api } = rt.load('lib/api.ts');
  const options = { signal: caller.signal, retry: true };
  assert.equal((await api('/directions', options))[0].id, 'test-direction');
  pending = true;
  const read = api('/directions', options);
  caller.abort();
  await assert.rejects(read, error => error.status === 0);
  const timedRead = api('/directions', { ...options, signal: new AbortController().signal });
  deadline.abort();
  await assert.rejects(timedRead, error => error.status === 0);
});
test('directions retries are bounded and retain the final request ID',async()=>{
  let calls=0;const requestId='553ac0cf-319a-42ce-ac27-aa78a3b43353';
  const rt=runtime('web',{setTimeout:callback=>setTimeout(callback,0),fetch:async()=>{
    calls++;return Response.json({detail:'Still unavailable'},{status:503,headers:{'X-Request-ID':requestId}});
  }});
  await assert.rejects(rt.load('lib/api.ts').api('/directions',{retry:true}),e=>e.status===503&&e.requestId===requestId);
  assert.equal(calls,3);
});
test('reads without opt-in, validation errors and mutations are never retried',async()=>{
  for(const [status,options] of [[500,{}],[403,{retry:true}],[422,{retry:true}],[500,{retry:true,method:'POST',body:'{}'}]]){
    let calls=0;
    const rt=runtime('web',{fetch:async()=>{calls++;return Response.json({detail:'Failure'},{status});}});
    await assert.rejects(rt.load('lib/api.ts').api('/directions',options));
    assert.equal(calls,1);
  }
});
test('cancelling a directions load during backoff prevents further requests',async()=>{
  let calls=0;const controller=new AbortController();
  const rt=runtime('web',{setTimeout:callback=>{controller.abort();callback();},fetch:async()=>{
    calls++;return Response.json({detail:'Unavailable'},{status:503});
  }});
  await assert.rejects(rt.load('lib/api.ts').api('/directions',{retry:true,signal:controller.signal}),e=>e.status===0);
  assert.equal(calls,1);
});
for(const app of ['web','admin']){
  test(`${app} config protects HTML responses with conservative headers`,async()=>{
    const config=runtime(app).load('../next.config.ts').default;
    const rules=await config.headers();assert.equal(rules[0].source,'/:path*');
    const headers=Object.fromEntries(rules[0].headers.map(({key,value})=>[key.toLowerCase(),value]));
    assert.equal(headers['x-content-type-options'],'nosniff');assert.equal(headers['x-frame-options'],'DENY');assert.equal(headers['referrer-policy'],'strict-origin-when-cross-origin');
  });
  test(`${app} API includes cookie credentials and chosen language`,async()=>{
    let request;const rt=runtime(app,{document:{documentElement:{lang:'kk'}},fetch:async(url,options)=>{request={url,options};return Response.json({ok:true});}});
    await rt.load('lib/api.ts').api('/auth/me');
    assert.equal(request.url,'/api/v1/auth/me');assert.equal(request.options.credentials,'include');assert.equal(request.options.cache,'no-store');assert.equal(request.options.headers.get('Accept-Language'),'kk');
  });
  test(`${app} API rejects arbitrary and prefixed destinations`,async()=>{
    const {api}=runtime(app).load('lib/api.ts');for(const value of ['https://evil.test','//evil.test','/api/v1/auth/me'])await assert.rejects(api(value));
  });
  test(`${app} API preserves safe request IDs on expected failures`,async()=>{
    const requestId='553ac0cf-319a-42ce-ac27-aa78a3b43353';
    const rt=runtime(app,{fetch:async()=>Response.json({detail:'Expected validation failure'},{status:400,headers:{'X-Request-ID':requestId}})});
    await assert.rejects(rt.load('lib/api.ts').api('/example'),error=>error.status===400&&error.requestId===requestId&&error.message==='Expected validation failure');
  });
  test(`${app} API discards malformed request IDs and wraps network errors`,async()=>{
    const rt=runtime(app,{fetch:async()=>Response.json({detail:'Expected failure'},{status:400,headers:{'X-Request-ID':'untrusted-id'}})});
    await assert.rejects(rt.load('lib/api.ts').api('/example'),error=>error.requestId===undefined);
    const network=runtime(app,{fetch:async()=>{throw new Error('Fetch failed');}}).load('lib/api.ts');
    await assert.rejects(network.api('/example'),error=>error.status===0);
  });
}

test('admin direction and document slugs match API limits using HTML pattern syntax',()=>{
  for(const [page,form,max] of [['directions','DirectionForm',60],['documents','DocumentForm',80]]){
    const file=`app/${page}/page.tsx`;
    const rt=runtime('admin',{privateFunctions:{[file]:[form]}});
    const tree=nodes(rt.load(file)[`__${form}`]({directions:[],onSaved:async()=>{}}));
    const slug=tree.find(node=>node?.type==='input' && node.props.maxLength===max);
    assert.equal(typeof slug?.props.pattern,'string');
    const accepts=new RegExp(`^(?:${slug.props.pattern})$`,'v');
    for(const valid of ['az','tablet-check','t2','a'.repeat(max)]) assert.ok(accepts.test(valid));
    for(const invalid of ['a','1a','Two Words','a/b','a_2','a'.repeat(max+1)]) assert.equal(accepts.test(invalid),false);
  }
});
