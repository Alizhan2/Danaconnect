import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import vm from 'node:vm';
import {test} from 'node:test';

// Execute the actual TSX handlers with deterministic React state and mocked
// API dependencies. No network, production sessions, email, or database access.
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const ts=createRequire(path.join(root,'apps/web/package.json'))('typescript');
const project={id:'idea',owner_id:'mentee',owner_role:'mentee',mentor_id:null,visibility_status:'published',title:'Synthetic idea'};
const mentor={id:'mentor',role:'mentor',account_status:'active',intake_open:true,full_name:'Synthetic mentor',timezone:'UTC',capacity:3};
const mentee={id:'mentee',role:'mentee',account_status:'active',full_name:'Synthetic mentee',timezone:'UTC'};
const pending={id:'offer',project_id:'idea',mentor_id:'mentor',mentee_id:'mentee',initiator_role:'mentor',initiator_id:'mentor',decision_user_id:'mentee',mentor_name:'Synthetic mentor',mentee_name:'Synthetic mentee',status:'pending',motivation:'Synthetic mentor support proposal'};
function nodes(tree){if(Array.isArray(tree))return tree.flatMap(nodes);if(tree&&typeof tree==='object')return [tree,...nodes(tree.props?.children)];return tree===undefined||tree===null?[]:[tree];}
function fixture({file='components/workflows/mentor-offers.tsx',name='MentorOffers',data=[],states=[],props={project,user:mentor}}={}){
  const values=[...states],calls=[],steps=[],reads=[];let cursor=0,loadCursor=0,tree,reply,loaders=[];
  const react={useState(initial){const position=cursor++;if(!(position in values))values[position]=initial;return [values[position],next=>{values[position]=typeof next==='function'?next(values[position]):next;}];},Suspense:'suspense'};
  const jsx=(type,props)=>({type,props});
  const action={busy:false,error:undefined,async run(work){this.busy=true;this.error=undefined;try{await work();return true;}catch(error){this.error=error;return false;}finally{this.busy=false;}}};
  const load={data,loading:false,reload:async()=>steps.push('reload')};
  const common={ActionNotice:'action-notice',LoadState:'load-state',statusText:value=>value,safeUrl:value=>value,dateTime:value=>value,useAction:()=>action,
    useLoad:loader=>{loaders.push(loader);return loadCursor++===0?load:{data:null,loading:false,reload:async()=>{}};},
    mutate:async(path,body,method)=>{calls.push({path,body,method});steps.push('mutation');if(reply instanceof Error)throw reply;return reply;}};
  const modules={react,'react/jsx-runtime':{jsx,jsxs:jsx,Fragment:'fragment'},
    '@/lib/api':{api:async path=>{reads.push(path);return data;}},'@/lib/i18n':{useLocale:()=>({locale:'ru',tr:value=>value,t:{}}),translatePhrase:value=>value},
    '@/components/ui':{Button:'button',Field:'field',Badge:'badge',EmptyState:'empty',SectionHeading:'heading'},
    './common':common,'@/components/workflows/common':common,'@/components/shell':{AppShell:'shell'},
    '@/components/notification-center':{NextStepCards:'next-steps'},
    'next/navigation':{useSearchParams:()=>new URLSearchParams(),useRouter:()=>({push:()=>{},refresh:()=>{}})}};
  const source=readFileSync(path.join(root,'apps/web/src',file),'utf8')+`\nexports.__target=${name};`;
  const code=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
  const module={exports:{}};
  vm.runInNewContext(`(function(require,exports,module){${code}\n})`,{Date,URLSearchParams,encodeURIComponent})(dependency=>{
    assert.ok(Object.hasOwn(modules,dependency),`Unexpected dependency ${dependency}`);return modules[dependency];
  },module.exports,module);
  const result={calls,steps,reads,action,load,runLoad:()=>loaders[0](),reply:value=>{reply=value;},render(){cursor=0;loadCursor=0;loaders=[];tree=module.exports.__target({...props,onChanged:async()=>steps.push('project-refresh')});return tree;},nodes:()=>nodes(tree),button:label=>nodes(tree).find(node=>node?.type==='button'&&node.props.children===label),form:()=>nodes(tree).find(node=>node?.type==='form'),input(value){nodes(tree).find(node=>node?.type==='textarea').props.onChange({target:{value}});this.render();},reason(value){nodes(tree).find(node=>node?.type==='select').props.onChange({target:{value}});this.render();},async submit(){await this.form().props.onSubmit({preventDefault(){}});this.render();}};
  result.render();return result;
}

test('an eligible mentor submits trimmed support to the idea owner then refreshes',async()=>{
  const screen=fixture();assert.ok(screen.form());assert.equal(screen.button('Предложить поддержку').props.disabled,true);
  const input=screen.nodes().find(node=>node?.type==='textarea');assert.equal(input.props.minLength,10);assert.equal(input.props.maxLength,5000);assert.equal(input.props.required,true);
  screen.input('  I can mentor this project  ');assert.equal(screen.button('Предложить поддержку').props.disabled,false);
  await screen.submit();assert.equal(screen.calls.length,1);assert.equal(screen.calls[0].path,'/projects/idea/mentor-offers');assert.equal(screen.calls[0].body.motivation,'I can mentor this project');
  assert.deepEqual(screen.steps,['mutation','reload','project-refresh']);assert.equal(screen.nodes().find(node=>node?.type==='textarea').props.value,'');
});

test('failed offer preserves entered motivation and does not refresh',async()=>{
  const screen=fixture();screen.input('A detailed mentoring proposal');screen.reply(new Error('Synthetic rejection'));
  await screen.submit();assert.equal(screen.action.error.message,'Synthetic rejection');assert.equal(screen.nodes().find(node=>node?.type==='textarea').props.value,'A detailed mentoring proposal');assert.deepEqual(screen.steps,['mutation']);
});

test('form is hidden for owners, nonmentors, inactive mentors, unpublished and assigned ideas',()=>{
  const cases=[{user:mentee},{user:{...mentor,id:'mentee'}},{user:{...mentor,role:'admin'}},{user:{...mentor,account_status:'pending'}},{user:{...mentor,account_status:'suspended'}},{user:{...mentor,intake_open:false}},
    ...['draft','pending','hidden'].map(visibility_status=>({project:{...project,visibility_status}})),{project:{...project,mentor_id:'mentor2'}}];
  for(const changes of cases){const screen=fixture({props:{project,user:mentor,...changes}});assert.equal(screen.form(),undefined);}
});

test('pending and accepted own offers prevent duplicate submission, other projects do not',()=>{
  for(const status of ['pending','accepted'])assert.equal(fixture({data:[{...pending,status}]}).form(),undefined);
  for(const status of ['rejected','withdrawn'])assert.ok(fixture({data:[{...pending,status}]}).form());
  assert.ok(fixture({data:[{...pending,project_id:'different-idea'}]}).form());
  assert.equal(fixture({data:[{...pending,initiator_role:'mentee',initiator_id:'mentee',decision_user_id:'mentor'}]}).form(),undefined);
});

test('a pending mentee request guides the mentor to their existing dashboard inbox',()=>{
  const screen=fixture({data:[{...pending,initiator_role:'mentee',initiator_id:'mentee',decision_user_id:'mentor'}]});
  assert.equal(screen.form(),undefined);
  assert.ok(screen.nodes().some(node=>typeof node==='string'&&node.includes('По этой идее у вас уже есть заявка менти.')));
  assert.ok(screen.nodes().some(node=>node?.type==='button'&&node.props.href==='/dashboard'));
});

test('owner accepts incoming mentor support and refreshes both inbox and project',async()=>{
  const screen=fixture({data:[pending],props:{project,user:mentee}});
  assert.ok(screen.button('Принять поддержку'));assert.equal(screen.button('Отозвать предложение'),undefined);assert.equal(screen.button('Отклонить').props.disabled,true);
  await screen.button('Принять поддержку').props.onClick();assert.equal(screen.calls[0].path,'/applications/offer/decision');assert.equal(screen.calls[0].body.decision,'accepted');assert.deepEqual(screen.steps,['mutation','reload','project-refresh']);
});

test('owner rejection requires a reason and sends the selected value',async()=>{
  const screen=fixture({data:[pending],props:{project,user:mentee}});screen.reason('not_a_fit');assert.equal(screen.button('Отклонить').props.disabled,false);
  await screen.button('Отклонить').props.onClick();assert.equal(screen.calls[0].path,'/applications/offer/decision');assert.equal(screen.calls[0].body.decision,'rejected');assert.equal(screen.calls[0].body.reason,'not_a_fit');
});

test('initiating mentor can withdraw and cannot decide their own offer',async()=>{
  const screen=fixture({data:[pending]});assert.equal(screen.button('Принять поддержку'),undefined);assert.equal(screen.button('Отклонить'),undefined);
  await screen.button('Отозвать предложение').props.onClick();assert.equal(screen.calls[0].path,'/applications/offer/withdraw');assert.deepEqual(screen.steps,['mutation','reload','project-refresh']);
});

test('unrelated and inactive viewers never get offer decision controls',()=>{
  for(const user of [{...mentee,id:'stranger'},{...mentor,id:'mentor2'},{...mentee,account_status:'suspended'}]){
    const screen=fixture({data:[pending],props:{project,user}});for(const label of ['Принять поддержку','Отклонить','Отозвать предложение'])assert.equal(screen.button(label),undefined);
  }
});

test('accepted offers expose participation and chat links without decision buttons',()=>{
  const screen=fixture({data:[{...pending,status:'accepted'}],props:{project:{...project,mentor_id:'mentor'},user:mentee}});
  assert.equal(screen.button('Открыть участие').props.href,'/dashboard');assert.equal(screen.button('Открыть диалог').props.href,'/messages');assert.equal(screen.button('Принять поддержку'),undefined);
});

function dashboard(user,application){return fixture({file:'app/dashboard/page.tsx',name:'Dashboard',data:{user,applications:[application],participations:[],bookings:[],projects:[],results:[],notifications:[]}});}
test('dashboard gives mentor-offer decisions to mentees and withdrawal to mentors',()=>{
  const owner=dashboard(mentee,pending);assert.ok(owner.button('Принять'));assert.ok(owner.button('Отклонить'));assert.equal(owner.button('Отозвать заявку'),undefined);
  const initiator=dashboard(mentor,pending);assert.ok(initiator.button('Отозвать заявку'));assert.equal(initiator.button('Принять'),undefined);
});

test('dashboard retains old mentee application role fallbacks',()=>{
  const ordinary={...pending,initiator_role:'mentee'};delete ordinary.initiator_id;delete ordinary.decision_user_id;
  assert.ok(dashboard(mentor,ordinary).button('Принять'));assert.equal(dashboard(mentor,ordinary).button('Отозвать заявку'),undefined);
  assert.ok(dashboard(mentee,ordinary).button('Отозвать заявку'));assert.equal(dashboard(mentee,ordinary).button('Принять'),undefined);
});

test('forum route shares the project feed and shell navigation exposes it',()=>{
  const route=readFileSync(path.join(root,'apps/web/src/app/forum/page.tsx'),'utf8');assert.match(route,/export\s*\{\s*default\s*\}\s*from\s*["']\.\.\/projects\/page["']/);
  const shell=readFileSync(path.join(root,'apps/web/src/components/shell.tsx'),'utf8');assert.ok(shell.includes('"/forum"'));
});

test('offer panel requests a project-scoped inbox instead of first unrelated page',async()=>{
  const screen=fixture();await screen.runLoad();assert.deepEqual(screen.reads,['/applications?project_id=idea']);
});

test('forum kind selector sends filtering to the server',async()=>{
  for(const kind of ['ideas','projects']){
    const screen=fixture({file:'app/projects/page.tsx',name:'ProjectsPage',states:['','','',kind],data:{projects:[],directions:[],user:null}});
    await screen.runLoad();const request=new URL(screen.reads[0],'http://fixture.test');assert.equal(request.pathname,'/projects');assert.equal(request.searchParams.get('kind'),kind);
  }
});
