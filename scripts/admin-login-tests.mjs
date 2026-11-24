import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import vm from 'node:vm';
import {test} from 'node:test';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const ts=createRequire(path.join(root,'apps/admin/package.json'))('typescript');
const source=readFileSync(path.join(root,'apps/admin/src/app/login/page.tsx'),'utf8');
const helper={exports:{}};
vm.runInNewContext(ts.transpileModule(readFileSync(path.join(root,'apps/admin/src/lib/admin-invitations.ts'),'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText,{exports:helper.exports,module:helper});
function nodes(tree){if(Array.isArray(tree))return tree.flatMap(nodes);return tree&&typeof tree==='object'?[tree,...nodes(tree.props?.children)]:[];}
function loginScreen(){
  const values=[],effects=[],calls=[],navigation=[];let cursor=0,dirty=false,queued=[],clock=10000,nextTimer=1,reply;
  const timers=new Map(),listeners=new Map();
  const events={addEventListener(type,callback){if(!listeners.has(type))listeners.set(type,new Set());listeners.get(type).add(callback);},removeEventListener(type,callback){listeners.get(type)?.delete(callback);}};
  class ApiError extends Error{constructor(status,message){super(message);this.status=status;}}
  const action={busy:false,error:undefined,clear(){this.error=undefined;},async run(work){this.busy=true;this.error=undefined;try{await work();}catch(error){this.error=error;}finally{this.busy=false;}}};
  const react={
    useState(initial){const index=cursor++;if(!(index in values))values[index]=initial;return [values[index],next=>{const actual=typeof next==='function'?next(values[index]):next;if(actual!==values[index])dirty=true;values[index]=actual;}];},
    useRef(initial){const index=cursor++;if(!(index in values))values[index]={current:initial};return values[index];},
    useEffect(callback,deps){const index=cursor++,previous=effects[index];if(!previous||deps.some((value,i)=>value!==previous.deps[i]))queued.push(()=>{previous?.cleanup?.();effects[index]={deps,cleanup:callback()};});},
  };
  const jsx=(type,props)=>({type,props});
  const modules={react,'react/jsx-runtime':{jsx,jsxs:jsx},'next/link':{default:'link'},'next/navigation':{useRouter:()=>({push:href=>navigation.push(href),refresh:()=>navigation.push('refresh')}),useSearchParams:()=>new URLSearchParams()},'lucide-react':{ShieldCheck:'shield'},
    '@/lib/api':{ApiError,mutate:async(path,body)=>{calls.push({path,body});if(reply instanceof Error)throw reply;return typeof reply==='function'?reply(path,body):reply;}},
    '@/lib/admin-invitations':helper.exports,'@/lib/i18n':{useLocale:()=>({locale:'ru',t:key=>key})},'@/components/brand-logo':{BrandLogo:'brand-logo'},'@/components/common':{ActionNotice:'notice',LocalePicker:'locale',useAction:()=>action,webUrl:'http://fixture.local'},'@/components/ui':{Button:'button',Field:'field'},
  };
  class FixtureDate extends Date{static now(){return clock;}}
  const module={exports:{}};
  const code=ts.transpileModule(source+'\nexports.__Login=Login;',{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
  vm.runInNewContext(`(function(require,exports,module){${code}\n})`,{Date:FixtureDate,URL,URLSearchParams,process:{env:{}},window:{...events,setInterval:callback=>{const id=nextTimer++;timers.set(id,callback);return id;},clearInterval:id=>timers.delete(id)},document:events})(name=>{assert.ok(Object.hasOwn(modules,name),`Unexpected dependency ${name}`);return modules[name];},module.exports,module);
  let tree;
  function render(){for(let pass=0;pass<10;pass++){cursor=0;dirty=false;queued=[];tree=module.exports.__Login();for(const effect of queued)effect();if(!dirty)return;}throw new Error('Component did not settle');}
  function input(value){nodes(tree).filter(node=>node.type==='input').at(-1).props.onChange({target:{value}});render();}
  const fixture={calls,navigation,action,ApiError,nodes:()=>nodes(tree),text:()=>JSON.stringify(nodes(tree)),reply:value=>{reply=value;},input,async submit(){await nodes(tree).find(node=>node.type==='form').props.onSubmit({preventDefault(){}});render();},restart(){nodes(tree).find(node=>node.type==='button'&&node.props.children==='changeEmail').props.onClick();render();},advance(ms,runTimers=true){clock+=ms;if(runTimers)for(const callback of Array.from(timers.values()))callback();render();},emit(type,event={}){for(const callback of Array.from(listeners.get(type)??[]))callback(event);render();},unmount(){for(const effect of effects)effect?.cleanup?.();}};
  render();input('admin@example.test');return fixture;
}
const emailChallenge={challenge_id:'fixture-email-proof',delivery_status:'sent'};
const enrollment={qr_data_url:'data:image/svg+xml;base64,PHN2Zy8+',manual_entry_key:'FIXTURE_MANUAL_KEY'};
const mfa={mfa_required:true,mfa_challenge_id:'fixture-mfa-proof',method:'totp',expires_in:300};
async function emailProof(fixture,response={...mfa,enrollment}){fixture.reply(emailChallenge);await fixture.submit();fixture.input('123456');fixture.reply(response);await fixture.submit();}
function noSecret(fixture){assert.equal(fixture.nodes().filter(node=>node.type==='img').length,0);assert.ok(!fixture.text().includes(enrollment.manual_entry_key));}

test('first setup reveals only a local QR and accessible manual key after email proof',async()=>{
  const f=loginScreen();noSecret(f);f.reply({...emailChallenge,enrollment});await f.submit();noSecret(f);
  f.input('123456');f.reply({...mfa,enrollment});await f.submit();
  const image=f.nodes().find(node=>node.type==='img');assert.equal(image.props.src,enrollment.qr_data_url);assert.equal(image.props.referrerPolicy,'no-referrer');assert.equal(image.props.alt,'inviteQrAlt');
  assert.ok(f.nodes().some(node=>node.props['aria-label']==='secret'&&node.props.children===enrollment.manual_entry_key));assert.ok(f.text().includes('inviteScanNote'));
  assert.deepEqual(f.calls.map(call=>call.path),['/auth/request-code','/auth/verify-code']);
});
test('regular MFA sign-in never displays enrollment controls',async()=>{const f=loginScreen();await emailProof(f,mfa);noSecret(f);assert.ok(f.text().includes('mfaLoginNote'));assert.ok(!f.text().includes('inviteManualSetup'));});
test('wrong TOTP preserves the QR; successful verification clears it before navigation',async()=>{
  const f=loginScreen();await emailProof(f);f.input('000000');f.reply(new f.ApiError(400,'Wrong code'));await f.submit();assert.equal(f.nodes().filter(node=>node.type==='img').length,1);assert.equal(f.action.error.status,400);
  f.input('654321');f.reply({role:'admin'});await f.submit();noSecret(f);assert.deepEqual(f.navigation,['/','refresh']);assert.equal(f.calls.at(-1).path,'/auth/mfa/verify');assert.equal(f.calls.at(-1).body.mfa_challenge_id,mfa.mfa_challenge_id);
});
test('local setup expiry clears QR/key/code without requests and requires a fresh email proof',async()=>{
  const f=loginScreen();await emailProof(f);f.input('123456');const count=f.calls.length;f.advance(300001);noSecret(f);assert.equal(f.calls.length,count);assert.ok(f.text().includes('inviteEnrollmentExpired'));assert.equal(f.nodes().find(node=>node.props.type==='submit').props.disabled,true);
  f.restart();f.reply(emailChallenge);await f.submit();assert.equal(f.calls.at(-1).path,'/auth/request-code');noSecret(f);
});
test('server expiry clears enrollment and uses first-setup restart instructions',async()=>{const f=loginScreen();await emailProof(f);f.input('654321');f.reply(new f.ApiError(410,'Expired'));await f.submit();noSecret(f);assert.ok(f.text().includes('inviteEnrollmentExpired'));});
test('restart clears enrollment immediately',async()=>{const f=loginScreen();await emailProof(f);f.restart();noSecret(f);assert.ok(!f.text().includes('mfa_challenge_id'));assert.equal(f.nodes().filter(node=>node.type==='input').length,1);});
test('unsafe or failed QR images fall back to manual setup without remote loads',async()=>{
  for(const qr_data_url of ['https://fixture.invalid/secret',enrollment.qr_data_url]){const f=loginScreen();await emailProof(f,{...mfa,enrollment:{...enrollment,qr_data_url}});const image=f.nodes().find(node=>node.type==='img');if(image){image.props.onError();f.emit('fixture-render');}assert.equal(f.nodes().filter(node=>node.type==='img').length,0);assert.ok(f.text().includes('inviteQrUnavailable'));assert.ok(f.text().includes(enrollment.manual_entry_key));}
});
test('pagehide drops enrollment and pageshow cannot restore it',async()=>{const f=loginScreen();await emailProof(f);f.emit('pagehide');noSecret(f);f.emit('pageshow');noSecret(f);assert.equal(f.nodes().filter(node=>node.type==='input').length,1);});
test('restoring a cached document discards setup even if pagehide updates were suspended',async()=>{const f=loginScreen();await emailProof(f);f.emit('pageshow',{persisted:true});noSecret(f);assert.equal(f.nodes().filter(node=>node.type==='input').length,1);});
test('resuming a suspended tab checks its absolute deadline before the next timer',async()=>{const f=loginScreen();await emailProof(f);f.advance(300001,false);f.emit('visibilitychange');noSecret(f);assert.ok(f.text().includes('inviteEnrollmentExpired'));});
test('submitting after the absolute deadline clears setup without an extra verification request',async()=>{const f=loginScreen();await emailProof(f);f.advance(300001,false);const count=f.calls.length;await f.submit();noSecret(f);assert.equal(f.calls.length,count);assert.equal(f.action.error.status,410);});
test('late email-proof responses after pagehide or unmount cannot resurrect QR or navigate',async()=>{
  for(const leave of [f=>f.emit('pagehide'),f=>f.unmount()]){const f=loginScreen();f.reply(emailChallenge);await f.submit();f.input('123456');let resolve;f.reply(()=>new Promise(done=>{resolve=done;}));const pending=f.submit();leave(f);resolve({...mfa,enrollment});await pending;noSecret(f);assert.equal(f.navigation.length,0);}
});
test('a late successful MFA response after leaving cannot navigate or restore enrollment',async()=>{const f=loginScreen();await emailProof(f);f.input('654321');let resolve;f.reply(()=>new Promise(done=>{resolve=done;}));const pending=f.submit();f.emit('pagehide');resolve({role:'admin'});await pending;noSecret(f);assert.equal(f.navigation.length,0);});
