'use client';
import {Suspense,useEffect,useRef,useState,type FormEvent} from 'react';
import {useRouter,useSearchParams} from 'next/navigation';
import Link from 'next/link';
import {BrandLogo} from '@/components/brand-logo';
import {ShieldCheck} from 'lucide-react';
import {ApiError,mutate} from '@/lib/api';
import type {User} from '@/lib/types';
import {useLocale} from '@/lib/i18n';
import {Button,Field} from '@/components/ui';
import {ActionNotice,LocalePicker,useAction,webUrl} from '@/components/common';
import {localQrImage} from '@/lib/admin-invitations';
type MfaChallenge={mfa_required:true;mfa_challenge_id:string;method:string;expires_in:number;deadline:number;enrollment?:{qr_data_url:string;manual_entry_key:string};setup?:boolean};
function returnPath(value:string|null){if(!value||!value.startsWith('/')||value.startsWith('//')||/[\\\u0000-\u001f]/.test(value))return '/';try{const url=new URL(value,'https://local.invalid');if(url.origin!=='https://local.invalid')return '/';const base=process.env.NEXT_PUBLIC_ADMIN_BASE_PATH||'';const path=base&&url.pathname.startsWith(base+'/')?url.pathname.slice(base.length):url.pathname;return ['/','/launch','/users','/registrations','/projects','/activity','/growth','/ai-review','/directions','/documents','/comments','/reports','/privacy','/audit','/results','/analytics','/operations'].includes(path)?path+url.search:'/';}catch{return '/';}}
function Login(){const {locale,t}=useLocale();const router=useRouter();const search=useSearchParams();const action=useAction();const [email,setEmail]=useState('');const [code,setCode]=useState('');const [challenge,setChallenge]=useState<{challenge_id:string;debug_code?:string;delivery_status?:'queued'|'sent'|'development'}>();const [mfa,setMfa]=useState<MfaChallenge>();
const [remaining,setRemaining]=useState(0);
const [qrFailed,setQrFailed]=useState(false);
const attempt=useRef(0);
function clearChallenge(){attempt.current++;setChallenge(undefined);setMfa(undefined);setCode('');setRemaining(0);setQrFailed(false);}
useEffect(()=>{
  const leave=()=>{clearChallenge();action.clear();};
  const restore=(event:PageTransitionEvent)=>{if(event.persisted)leave();};
  window.addEventListener('pagehide',leave);
  window.addEventListener('pageshow',restore);
  return ()=>{attempt.current++;window.removeEventListener('pagehide',leave);window.removeEventListener('pageshow',restore);};
},[]);
useEffect(()=>{
  if(!mfa)return;
  const update=()=>{
    const left=Math.max(0,Math.ceil((mfa.deadline-Date.now())/1000));
    setRemaining(left);
    if(!left){setCode('');setMfa(current=>current?.enrollment?{...current,enrollment:undefined}:current);}
  };
  update();
  const timer=window.setInterval(update,1000);
  window.addEventListener('pageshow',update);
  document.addEventListener('visibilitychange',update);
  return ()=>{window.clearInterval(timer);window.removeEventListener('pageshow',update);document.removeEventListener('visibilitychange',update);};
},[mfa]);
const expired=!!mfa&&remaining===0;
const enrollment=!expired?mfa?.enrollment:undefined;
const qr=enrollment&&!qrFailed?localQrImage(enrollment.qr_data_url):undefined;
const expiredMessage=t(mfa?.setup?'inviteEnrollmentExpired':'mfaExpired');
function restart(){clearChallenge();action.clear();}

async function submit(event:FormEvent){
  event.preventDefault();
  const currentAttempt=attempt.current;
  await action.run(async()=>{
    if(mfa){
      if(Date.now()>=mfa.deadline){setMfa({...mfa,enrollment:undefined});setRemaining(0);setCode('');throw new ApiError(410,expiredMessage);}
      let user:User;
      try{
        user=await mutate<User>('/auth/mfa/verify',{mfa_challenge_id:mfa.mfa_challenge_id,code});
      }catch(error){
        if(currentAttempt!==attempt.current)return;
        if(error instanceof ApiError&&error.status===410){
          setMfa({...mfa,enrollment:undefined,deadline:0});setRemaining(0);setCode('');
        }
        throw error;
      }
      if(currentAttempt!==attempt.current)return;
      if(user.role!=='admin')throw new ApiError(403,t('denied'));
      clearChallenge();
      router.push(returnPath(search.get('returnTo')));router.refresh();return;
    }
    if(!challenge){const response=await mutate<{challenge_id:string;debug_code?:string;delivery_status?:'queued'|'sent'|'development'}>('/auth/request-code',{email,locale});if(currentAttempt===attempt.current)setChallenge(response);return;}
    const response=await mutate<User|Omit<MfaChallenge,'deadline'|'setup'>>('/auth/verify-code',{challenge_id:challenge.challenge_id,code});
    if(currentAttempt!==attempt.current)return;
    if('mfa_required' in response){
      setRemaining(response.expires_in);
      setMfa({...response,setup:!!response.enrollment,deadline:Date.now()+response.expires_in*1000});setQrFailed(false);setCode('');return;
    }
    if(response.role!=='admin'){await mutate('/auth/logout');throw new ApiError(403,t('denied'));}
    clearChallenge();
    router.push(returnPath(search.get('returnTo')));router.refresh();
  });
}
return <div className="auth-screen"><aside className="auth-brand"><Link href="/" className="brand"><BrandLogo preload/><span>{t('administration')}</span></Link><div><ShieldCheck size={52} strokeWidth={1}/><h1>{t('workspace')}</h1><p>{t('loginNote')}</p></div><p>DanaConnect · {t('security')}</p></aside><div className="auth-body"><div className="row"><Link href="/" className="auth-mobile-brand" aria-label="DanaConnect"><BrandLogo preload/></Link><LocalePicker/></div><div className="auth-card"><p className="eyebrow">DANACONNECT · ADMIN</p><h1>{mfa?t('mfa'):t('login')}</h1><p>{enrollment?t('inviteWelcomeNote'):mfa?t('mfaLoginNote'):t('loginNote')}</p><details><summary>{t('mfaSetup')}</summary><p>{t('inviteLoginSetup')}</p></details>{Boolean(action.error)&&<><ActionNotice action={{...action,success:false}}/>{action.error instanceof ApiError&&action.error.status===410&&!expired&&<p role="status">{expiredMessage}</p>}{mfa&&action.error instanceof ApiError&&action.error.status===400&&<p>{t('mfaInvalid')}</p>}</>}{mfa&&<div className="notice">{expired?<p role="status">{expiredMessage}</p>:<p>{t('mfaTimeLeft')}: {Math.floor(remaining/60)}:{String(remaining%60).padStart(2,'0')}</p>}</div>}{enrollment&&<section aria-labelledby="login-qr-heading"><h2 id="login-qr-heading">{t('inviteScanQr')}</h2><p>{t('inviteScanNote')}</p>{qr?<img className="enrollment-qr" src={qr} alt={t('inviteQrAlt')} width={280} height={280} referrerPolicy="no-referrer" onError={()=>setQrFailed(true)}/>:<p role="status">{t('inviteQrUnavailable')}</p>}<details><summary>{t('inviteManualSetup')}</summary><p>{t('inviteManualNote')}</p><p className="code-block" aria-label={t('secret')}>{enrollment.manual_entry_key}</p></details></section>}<form className="form-stack" onSubmit={submit}><Field label={t('email')}><input required type="email" autoComplete="email" maxLength={254} disabled={!!challenge} value={email} onChange={e=>setEmail(e.target.value)}/></Field>{challenge&&<><Field label={t(mfa?'mfaCode':'otp')}><input key={mfa?'mfa':'otp'} required inputMode="numeric" pattern="[0-9]{6}" maxLength={6} autoComplete="one-time-code" value={code} onChange={e=>setCode(e.target.value)}/></Field>{!mfa&&<div className="notice">{t(challenge.delivery_status==='queued'?'inviteCodeQueued':'codeSent')}{challenge.debug_code&&<p><strong>{t('debugCode')}: {challenge.debug_code}</strong></p>}</div>}</>}<Button type="submit" disabled={action.busy||expired}>{action.busy?t('loading'):mfa?t('mfaVerify'):challenge?t('login'):t('requestCode')}</Button>{challenge&&<Button variant="ghost" disabled={action.busy} onClick={restart}>{t('changeEmail')}</Button>}</form><hr className="divider"/><a href={webUrl} className="text-link">{t('backToPlatform')}</a></div></div></div>;
}
export default function LoginPage(){return <Suspense><Login/></Suspense>;}


