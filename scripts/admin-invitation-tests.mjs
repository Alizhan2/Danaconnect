import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import vm from 'node:vm';
import {test} from 'node:test';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const ts=createRequire(path.join(root,'apps/admin/package.json'))('typescript');
const source=readFileSync(path.join(root,'apps/admin/src/lib/admin-invitations.ts'),'utf8');
const module={exports:{}};
vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText,{exports:module.exports,module,URLSearchParams,Date});
const {invitationToken,consumeInvitationFragment,localQrImage,secondsRemaining,canRevokeInvitation}=module.exports;
const token='aB_9-'.repeat(12)+'A123';

test('reads an opaque invitation token only from a fragment',()=>{
  assert.equal(invitationToken(`#token=${token}`),token);
  assert.equal(invitationToken('#'),null);
  assert.equal(invitationToken('#unrelated=value'),null);
});
test('rejects duplicate, oversized and unsafe invitation tokens',()=>{
  for(const fragment of [`#token=${token}&token=${token}`,'#token=short',`#token=${'a'.repeat(129)}`,`#token=${'a'.repeat(32)}%0A`,`#token=${'a'.repeat(32)}%2F`])assert.equal(invitationToken(fragment),null);
});
test('consuming a token removes fragment and query, preserving path and history state',()=>{
  const state={existing:'router-state'};const calls=[];
  const location={hash:`#token=${token}`,pathname:'/admin/accept-invite',search:'?lang=kk'};
  const actual=consumeInvitationFragment(location,{state,replaceState:(...args)=>calls.push(args)});
  assert.equal(actual,token);assert.equal(calls.length,1);assert.equal(calls[0][0],state);assert.equal(calls[0][2],'/admin/accept-invite');
  assert.ok(!JSON.stringify(calls).includes(token));
});
test('invalid fragments are removed too and a query token is never accepted',()=>{
  const calls=[];
  assert.equal(consumeInvitationFragment({hash:'#invalid',pathname:'/accept-invite',search:`?token=${token}`},{state:null,replaceState:(...args)=>calls.push(args)}),null);
  assert.equal(calls.length,1);
  const absent=[];
  assert.equal(consumeInvitationFragment({hash:'',pathname:'/accept-invite',search:`?token=${token}`},{state:null,replaceState:(...args)=>absent.push(args)}),null);
  assert.equal(absent.length,1);assert.equal(absent[0][2],'/accept-invite');
});
test('only bounded locally generated base64 SVG data is accepted for the QR image',()=>{
  const local='data:image/svg+xml;base64,PHN2Zy8+';
  assert.equal(localQrImage(local),local);
  for(const url of ['https://qr.example/secret','//qr.example/secret','javascript:alert(1)','data:text/html;base64,PHN2Zy8+','data:image/svg+xml,%3Csvg%2F%3E',`data:image/svg+xml;base64,${'a'.repeat(200001)}`])assert.equal(localQrImage(url),undefined);
});
test('deadlines round up seconds and never become negative',()=>{
  assert.equal(secondsRemaining(12001,10000),3);assert.equal(secondsRemaining(10001,10000),1);assert.equal(secondsRemaining(10000,10000),0);assert.equal(secondsRemaining(9000,10000),0);
});
test('only invitations awaiting acceptance expose revocation',()=>{
  assert.equal(canRevokeInvitation('pending'),true);
  for(const status of ['accepted','revoked','expired','unknown'])assert.equal(canRevokeInvitation(status),false);
});
test('invitation screen keeps secrets out of browser storage and uses the three backend endpoints',()=>{
  const component=readFileSync(path.join(root,'apps/admin/src/components/accept-admin-invitation.tsx'),'utf8');
  assert.ok(!/localStorage|sessionStorage|console\./.test(component));
  for(const endpoint of ['request-code','verify-code','accept'])assert.ok(component.includes(`/auth/admin-invitations/${endpoint}`));
  assert.ok(component.includes('consumeInvitationFragment(window.location,window.history)'));
  assert.ok(component.includes("error.status===410"));assert.ok(component.includes('setEnrollment(undefined)'));
});

function nodes(tree){if(Array.isArray(tree))return tree.flatMap(nodes);return tree&&typeof tree==='object'?[tree,...nodes(tree.props?.children)]:[];}
function invitationScreen(){
  const values=[];const effects=[];let cursor=0;let dirty=false;let queued=[];let clock=10000;let nextTimer=1;const timers=new Map();
  const calls=[];const replaced=[];const navigation=[];let reply;
  class ApiError extends Error{constructor(status,message){super(message);this.status=status;}}
  const action={busy:false,error:undefined,success:false,clear(){this.error=undefined;this.success=false;},async run(work){this.busy=true;this.error=undefined;try{await work();this.success=true;return true;}catch(error){this.error=error;return false;}finally{this.busy=false;}}};
  const react={
    useState(initial){const position=cursor++;if(!(position in values))values[position]=typeof initial==='function'?initial():initial;return [values[position],next=>{const actual=typeof next==='function'?next(values[position]):next;if(actual!==values[position])dirty=true;values[position]=actual;}];},
    useRef(initial){const position=cursor++;if(!(position in values))values[position]={current:initial};return values[position];},
    useEffect(callback,deps){const position=cursor++;const previous=effects[position];if(!previous||deps.some((value,index)=>value!==previous.deps[index])){queued.push(()=>{previous?.cleanup?.();effects[position]={deps,cleanup:callback()};});}},
  };
  const location={hash:`#token=${token}`,pathname:'/admin/accept-invite',search:''};
  const history={state:{fixture:'router'},replaceState(state,unused,url){replaced.push(url);location.hash='';location.search='';}};
  const jsx=(type,props)=>({type,props});
  const modules={react,'react/jsx-runtime':{jsx,jsxs:jsx},'next/link':{default:'link'},'next/navigation':{useRouter:()=>({replace:href=>navigation.push(href),refresh:()=>navigation.push('refresh')})},'lucide-react':{ShieldCheck:'shield'},
    '@/lib/api':{ApiError,mutate:async(path,body)=>{calls.push({path,body});if(reply instanceof Error)throw reply;return typeof reply==='function'?reply(path,body):reply;}},
    '@/lib/admin-invitations':{consumeInvitationFragment,localQrImage,secondsRemaining:deadline=>secondsRemaining(deadline,clock)},
    '@/lib/i18n':{useLocale:()=>({t:key=>key})},'@/components/brand-logo':{BrandLogo:'brand-logo'},'./common':{ActionNotice:'notice',LocalePicker:'locale',useAction:()=>action,webUrl:'http://fixture.local'},'./ui':{Button:'button',Field:'field'},
  };
  class FixtureDate extends Date{static now(){return clock;}}
  const module={exports:{}};
  const component=readFileSync(path.join(root,'apps/admin/src/components/accept-admin-invitation.tsx'),'utf8');
  const code=ts.transpileModule(component,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
  vm.runInNewContext(`(function(require,exports,module){${code}\n})`,{Date:FixtureDate,window:{location,history,setInterval:callback=>{const id=nextTimer++;timers.set(id,callback);return id;},clearInterval:id=>timers.delete(id)}})(name=>{assert.ok(Object.hasOwn(modules,name),`Unexpected dependency ${name}`);return modules[name];},module.exports,module);
  let tree;
  function render(){for(let pass=0;pass<10;pass++){cursor=0;dirty=false;queued=[];tree=module.exports.AcceptAdminInvitation();for(const effect of queued)effect();if(!dirty)return tree;}throw new Error('Component did not settle');}
  function find(type){return nodes(tree).find(node=>node.type===type);}
  const fixture={calls,replaced,navigation,action,ApiError,render,nodes:()=>nodes(tree),reply:value=>{reply=value;},async submit(){await find('form').props.onSubmit({preventDefault(){}});render();},input(value){find('input').props.onChange({target:{value}});render();},advance(ms){clock+=ms;for(const callback of Array.from(timers.values()))callback();render();}};
  render();return fixture;
}
const challenge={challenge_id:'fixture-email-proof',delivery_status:'pending',email:'admin@example.test',full_name:'Fixture Administrator',expires_in:300};
const enrollment={enrollment_token:'fixture-enrollment-token',totp_uri:'otpauth://totp/fixture',qr_data_url:'data:image/svg+xml;base64,PHN2Zy8+',manual_entry_key:'FIXTURE_MANUAL_SECRET',expires_in:300,email:challenge.email,full_name:challenge.full_name};
async function setupQr(fixture){fixture.reply(challenge);await fixture.submit();fixture.input('123456');fixture.reply(enrollment);await fixture.submit();}

test('QR stays hidden until email proof and the fragment is removed before requests',async()=>{
  const fixture=invitationScreen();assert.deepEqual(fixture.replaced,['/admin/accept-invite']);assert.equal(fixture.nodes().filter(node=>node.type==='img').length,0);
  await setupQr(fixture);assert.equal(fixture.nodes().filter(node=>node.type==='img').length,1);
  assert.deepEqual(fixture.calls.map(call=>call.path),['/auth/admin-invitations/request-code','/auth/admin-invitations/verify-code']);
  assert.equal(fixture.calls[0].body.token,token);assert.equal(fixture.calls[1].body.code,'123456');
});
test('a wrong Authenticator code keeps the same QR and enrollment proof',async()=>{
  const fixture=invitationScreen();await setupQr(fixture);fixture.input('000000');fixture.reply(new fixture.ApiError(400,'Fixture wrong code'));await fixture.submit();
  assert.equal(fixture.nodes().filter(node=>node.type==='img').length,1);assert.equal(fixture.calls.at(-1).body.enrollment_token,enrollment.enrollment_token);assert.equal(fixture.action.error.status,400);
  fixture.input('654321');fixture.reply({role:'admin'});await fixture.submit();assert.equal(fixture.calls.at(-1).body.enrollment_token,enrollment.enrollment_token);assert.deepEqual(fixture.navigation,['/','refresh']);assert.equal(fixture.nodes().filter(node=>node.type==='img').length,0);
});
test('server-expired enrollment clears its QR and restarts email proof',async()=>{
  const fixture=invitationScreen();await setupQr(fixture);fixture.input('654321');fixture.reply(new fixture.ApiError(410,'Fixture expired'));await fixture.submit();assert.equal(fixture.nodes().filter(node=>node.type==='img').length,0);
  fixture.reply(challenge);await fixture.submit();assert.equal(fixture.calls.at(-1).path,'/auth/admin-invitations/request-code');assert.equal(fixture.calls.at(-1).body.token,token);
  fixture.input('123456');fixture.reply(enrollment);await fixture.submit();assert.ok(fixture.nodes().some(node=>node.type==='p'&&node.props.children==='inviteReplaceQr'));
});
test('the setup deadline clears the QR locally without any network request',async()=>{
  const fixture=invitationScreen();await setupQr(fixture);const count=fixture.calls.length;fixture.advance(300001);assert.equal(fixture.calls.length,count);assert.equal(fixture.nodes().filter(node=>node.type==='img').length,0);assert.ok(!JSON.stringify(fixture.nodes()).includes(enrollment.manual_entry_key));
});
test('expired invitation cannot request repeated codes and offers existing sign-in',async()=>{
  const fixture=invitationScreen();fixture.reply(new fixture.ApiError(410,'Fixture inactive invitation'));await fixture.submit();assert.equal(fixture.nodes().filter(node=>node.type==='form').length,0);assert.ok(fixture.nodes().some(node=>node.type==='link'&&node.props.href==='/login'));assert.equal(fixture.navigation.length,0);
});
test('every invitation phrase has nonempty Russian, Kazakh and English text',()=>{
  const text=readFileSync(path.join(root,'apps/admin/src/lib/i18n.tsx'),'utf8');
  const syntax=ts.createSourceFile('i18n.tsx',text,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
  let phrases;
  function visit(node){if(ts.isVariableDeclaration(node)&&node.name.getText(syntax)==='phrases')phrases=node.initializer;ts.forEachChild(node,visit);}
  visit(syntax);
  const object=ts.isAsExpression(phrases)?phrases.expression:phrases;
  const entries=object.properties.filter(property=>property.name.getText(syntax).startsWith('invite')||property.name.getText(syntax)==='adminInvitations');
  assert.ok(entries.length>=40);
  for(const entry of entries){assert.ok(ts.isArrayLiteralExpression(entry.initializer));assert.equal(entry.initializer.elements.length,3);for(const element of entry.initializer.elements)assert.ok(ts.isStringLiteral(element)&&element.text.trim().length>0,entry.name.getText(syntax));}
});
test('the invitation route sends no-referrer headers and excludes search indexing',()=>{
  const config=readFileSync(path.join(root,'apps/admin/next.config.ts'),'utf8');
  assert.match(config,/source:'\/accept-invite',headers:\[\s*\{key:'Referrer-Policy',value:'no-referrer'\}/);
  const page=readFileSync(path.join(root,'apps/admin/src/app/accept-invite/page.tsx'),'utf8');
  assert.ok(page.includes("referrer:'no-referrer'"));assert.ok(page.includes('robots:{index:false,follow:false}'));
});
