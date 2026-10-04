'use client';
import {Suspense,useEffect,useState,type FormEvent} from 'react';
import {useRouter,useSearchParams} from 'next/navigation';
import Link from 'next/link';
import {BrandLogo} from '@/components/brand-logo';
import {ShieldCheck} from 'lucide-react';
import {ApiError,mutate} from '@/lib/api';
import type {User} from '@/lib/types';
import {useLocale} from '@/lib/i18n';
import {Button,Field} from '@/components/ui';
import {ActionNotice,LocalePicker,useAction,webUrl} from '@/components/common';
type MfaChallenge={mfa_required:true;mfa_challenge_id:string;method:string;expires_in:number;deadline:number};
function returnPath(value:string|null){if(!value||!value.startsWith('/')||value.startsWith('//')||/[\\\u0000-\u001f]/.test(value))return '/';try{const url=new URL(value,'https://local.invalid');if(url.origin!=='https://local.invalid')return '/';const base=process.env.NEXT_PUBLIC_ADMIN_BASE_PATH||'';const path=base&&url.pathname.startsWith(base+'/')?url.pathname.slice(base.length):url.pathname;return ['/','/launch','/users','/registrations','/projects','/activity','/growth','/ai-review','/directions','/documents','/comments','/reports','/privacy','/audit','/results','/analytics','/operations'].includes(path)?path+url.search:'/';}catch{return '/';}}
function Login(){const {locale,t}=useLocale();const router=useRouter();const search=useSearchParams();const action=useAction();const [email,setEmail]=useState('');const [code,setCode]=useState('');const [challenge,setChallenge]=useState<{challenge_id:string;debug_code?:string}>();const [mfa,setMfa]=useState<MfaChallenge>();
const [remaining,setRemaining]=useState(0);
useEffect(()=>{
  if(!mfa)return;
  const update=()=>setRemaining(Math.max(0,Math.ceil((mfa.deadline-Date.now())/1000)));
  update();
  const timer=window.setInterval(update,1000);
  return ()=>window.clearInterval(timer);
},[mfa]);
const expired=!!mfa&&remaining===0;
function restart(){setChallenge(undefined);setMfa(undefined);setCode('');setRemaining(0);action.clear();}

async function submit(event:FormEvent){
  event.preventDefault();
  await action.run(async()=>{
    if(mfa){
      if(Date.now()>=mfa.deadline){setRemaining(0);throw new ApiError(410,t('mfaExpired'));}
      let user:User;
      try{
        user=await mutate<User>('/auth/mfa/verify',{mfa_challenge_id:mfa.mfa_challenge_id,code});
      }catch(error){
        if(error instanceof ApiError&&error.status===410){
          setMfa({...mfa,deadline:0});setRemaining(0);setCode('');
        }
        throw error;
      }
      if(user.role!=='admin')throw new ApiError(403,t('denied'));
      router.push(returnPath(search.get('returnTo')));router.refresh();return;
    }
    if(!challenge){setChallenge(await mutate('/auth/request-code',{email,locale}));return;}
    const response=await mutate<User|Omit<MfaChallenge,'deadline'>>('/auth/verify-code',{challenge_id:challenge.challenge_id,code});
    if('mfa_required' in response){
      setRemaining(response.expires_in);
      setMfa({...response,deadline:Date.now()+response.expires_in*1000});setCode('');return;
    }
    if(response.role!=='admin'){await mutate('/auth/logout');throw new ApiError(403,t('denied'));}
    router.push(returnPath(search.get('returnTo')));router.refresh();
  });
}
return <div className="auth-screen"><aside className="auth-brand"><Link href="/" className="brand"><BrandLogo preload/><span>{t('administration')}</span></Link><div><ShieldCheck size={52} strokeWidth={1}/><h1>{t('workspace')}</h1><p>{t('loginNote')}</p></div><p>DanaConnect · {t('security')}</p></aside><div className="auth-body"><div className="row"><Link href="/" className="auth-mobile-brand" aria-label="DanaConnect"><BrandLogo preload/></Link><LocalePicker/></div><div className="auth-card"><p className="eyebrow">DANACONNECT · ADMIN</p><h1>{mfa?t('mfa'):t('login')}</h1><p>{mfa?t('mfaLoginNote'):t('loginNote')}</p><details><summary>{t('mfaSetup')}</summary><p>{t('inviteLoginSetup')}</p></details>{Boolean(action.error)&&<><ActionNotice action={{...action,success:false}}/>{action.error instanceof ApiError&&action.error.status===410&&!expired&&<p role="status">{t('mfaExpired')}</p>}{mfa&&action.error instanceof ApiError&&action.error.status===400&&<p>{t('mfaInvalid')}</p>}</>}{mfa&&<div className="notice">{expired?<p role="status">{t('mfaExpired')}</p>:<p>{t('mfaTimeLeft')}: {Math.floor(remaining/60)}:{String(remaining%60).padStart(2,'0')}</p>}</div>}<form className="form-stack" onSubmit={submit}><Field label={t('email')}><input required type="email" autoComplete="email" maxLength={254} disabled={!!challenge} value={email} onChange={e=>setEmail(e.target.value)}/></Field>{challenge&&<><Field label={t(mfa?'mfaCode':'otp')}><input key={mfa?'mfa':'otp'} required inputMode="numeric" pattern="[0-9]{6}" maxLength={6} autoComplete="one-time-code" value={code} onChange={e=>setCode(e.target.value)}/></Field>{!mfa&&<div className="notice">{t('codeSent')}{challenge.debug_code&&<p><strong>{t('debugCode')}: {challenge.debug_code}</strong></p>}</div>}</>}<Button type="submit" disabled={action.busy||expired}>{action.busy?t('loading'):mfa?t('mfaVerify'):challenge?t('login'):t('requestCode')}</Button>{challenge&&<Button variant="ghost" disabled={action.busy} onClick={restart}>{t('changeEmail')}</Button>}</form><hr className="divider"/><a href={webUrl} className="text-link">{t('backToPlatform')}</a></div></div></div>;
}
export default function LoginPage(){return <Suspense><Login/></Suspense>;}


