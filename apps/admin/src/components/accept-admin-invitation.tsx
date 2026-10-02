'use client';
import Link from 'next/link';
import {useRouter} from 'next/navigation';
import {useEffect,useRef,useState,type FormEvent} from 'react';
import {ShieldCheck} from 'lucide-react';
import {ApiError,mutate} from '@/lib/api';
import type {AdminInvitationChallenge,AdminInvitationEnrollment} from '@/lib/admin-types';
import {consumeInvitationFragment,localQrImage,secondsRemaining} from '@/lib/admin-invitations';
import type {User} from '@/lib/types';
import {useLocale} from '@/lib/i18n';
import {ActionNotice,LocalePicker,useAction,webUrl} from './common';
import {Button,Field} from './ui';

type Challenge=AdminInvitationChallenge&{deadline:number};
type Enrollment=AdminInvitationEnrollment&{deadline:number};

export function AcceptAdminInvitation(){
  const {t}=useLocale();
  const router=useRouter();
  const action=useAction();
  const fragmentRead=useRef(false);
  const [loaded,setLoaded]=useState(false);
  const [token,setToken]=useState<string|null>(null);
  const [challenge,setChallenge]=useState<Challenge>();
  const [enrollment,setEnrollment]=useState<Enrollment>();
  const [code,setCode]=useState('');
  const [remaining,setRemaining]=useState(0);
  const [expiredStage,setExpiredStage]=useState<'email'|'mfa'|'invitation'|null>(null);
  const [qrFailed,setQrFailed]=useState(false);
  const [priorEnrollment,setPriorEnrollment]=useState(false);
  useEffect(()=>{
    if(fragmentRead.current)return;
    fragmentRead.current=true;
    setToken(consumeInvitationFragment(window.location,window.history));
    setLoaded(true);
  },[]);
  const deadline=enrollment?.deadline??challenge?.deadline;
  const timedStage=enrollment?'mfa':'email';
  useEffect(()=>{
    if(!deadline)return;
    const update=()=>{
      const left=secondsRemaining(deadline);setRemaining(left);
      if(!left){setExpiredStage(timedStage);if(timedStage==='mfa')setPriorEnrollment(true);setEnrollment(undefined);setChallenge(undefined);setCode('');}
    };
    update();const timer=window.setInterval(update,1000);
    return()=>window.clearInterval(timer);
  },[deadline,timedStage]);
  function restart(){if(enrollment)setPriorEnrollment(true);setChallenge(undefined);setEnrollment(undefined);setCode('');setRemaining(0);setQrFailed(false);action.clear();}
  async function submit(event:FormEvent){
    event.preventDefault();
    if(!token)return;
    await action.run(async()=>{
      try{
        if(enrollment){
          if(secondsRemaining(enrollment.deadline)===0)throw new ApiError(410,t('inviteEnrollmentExpired'));
          const user=await mutate<User>('/auth/admin-invitations/accept',{enrollment_token:enrollment.enrollment_token,code});
          if(user.role!=='admin'){await mutate('/auth/logout');throw new ApiError(403,t('denied'));}
          setEnrollment(undefined);setChallenge(undefined);setToken(null);setCode('');
          router.replace('/');router.refresh();return;
        }
        if(challenge){
          if(secondsRemaining(challenge.deadline)===0)throw new ApiError(410,t('inviteOtpExpired'));
          const result=await mutate<AdminInvitationEnrollment>('/auth/admin-invitations/verify-code',{token,challenge_id:challenge.challenge_id,code});
          setEnrollment({...result,deadline:Date.now()+result.expires_in*1000});setChallenge(undefined);setCode('');setQrFailed(false);setRemaining(result.expires_in);return;
        }
        const result=await mutate<AdminInvitationChallenge>('/auth/admin-invitations/request-code',{token});
        setChallenge({...result,deadline:Date.now()+result.expires_in*1000});setRemaining(result.expires_in);setExpiredStage(null);setCode('');
      }catch(error){
        if(error instanceof ApiError&&error.status===410){setExpiredStage(enrollment?'mfa':challenge?'email':'invitation');if(enrollment)setPriorEnrollment(true);if(!enrollment&&!challenge)setToken(null);setEnrollment(undefined);setChallenge(undefined);setCode('');setRemaining(0);}
        throw error;
      }
    });
  }
  const qr=enrollment&&!qrFailed?localQrImage(enrollment.qr_data_url):undefined;
  return <div className="auth-screen"><aside className="auth-brand"><Link href="/" className="brand">DanaConnect<span>{t('administration')}</span></Link><div><ShieldCheck size={52} strokeWidth={1}/><h1>{t('inviteWelcome')}</h1><p>{t('inviteWelcomeNote')}</p></div><p>DanaConnect · {t('security')}</p></aside><div className="auth-body"><div className="row"><LocalePicker/></div><div className="auth-card">
    <p className="eyebrow">DANACONNECT · ADMIN</p><h1>{enrollment?t('mfaSetup'):t('inviteWelcome')}</h1><p>{t('inviteWelcomeNote')}</p>
    <ol className="invite-steps" aria-label={t('inviteWelcome')}><li aria-current={!enrollment?'step':undefined}>{t('inviteEmailStep')}</li><li aria-current={enrollment?'step':undefined}>{t('inviteQrStep')}</li></ol>
    <ActionNotice action={{...action,success:false}}/>
    {action.error instanceof ApiError&&action.error.status===503&&<p role="status">{t('inviteCodeUnavailable')}</p>}
    {enrollment&&action.error instanceof ApiError&&action.error.status===400&&<p role="status">{t('mfaInvalid')}</p>}
    {expiredStage&&<div className="notice" role="status">{t(expiredStage==='mfa'?'inviteEnrollmentExpired':expiredStage==='invitation'?'inviteInactive':'inviteOtpExpired')}</div>}
    {!loaded?<p role="status">{t('loading')}</p>:!token?(!expiredStage&&<div className="notice">{t('inviteNoLink')}</div>):<>
      {(enrollment||challenge)&&<div className="notice"><strong>{t('inviteRecipient')}: {(enrollment??challenge)?.full_name}</strong><p className="word-break">{(enrollment??challenge)?.email}</p><p>{t('mfaTimeLeft')}: {Math.floor(remaining/60)}:{String(remaining%60).padStart(2,'0')}</p></div>}
      {enrollment&&<section aria-labelledby="qr-heading"><h2 id="qr-heading">{t('inviteScanQr')}</h2><p>{t('inviteScanNote')}</p>{priorEnrollment&&<p className="notice">{t('inviteReplaceQr')}</p>}{qr?<img className="enrollment-qr" src={qr} alt={t('inviteQrAlt')} width={280} height={280} referrerPolicy="no-referrer" onError={()=>setQrFailed(true)}/>:<p role="status">{t('inviteQrUnavailable')}</p>}<details><summary>{t('inviteManualSetup')}</summary><p>{t('inviteManualNote')}</p><p className="code-block" aria-label={t('secret')}>{enrollment.manual_entry_key}</p></details></section>}
      <form className="form-stack" onSubmit={submit}>
        {Boolean(enrollment||challenge)&&<Field label={t(enrollment?'mfaCode':'otp')}><input key={enrollment?'totp':'email'} required inputMode="numeric" pattern="[0-9]{6}" maxLength={6} autoComplete="one-time-code" value={code} onChange={e=>setCode(e.target.value)} disabled={action.busy}/></Field>}
        {challenge&&<div className="notice" role="status">{t('inviteCodeQueued')}{challenge.debug_code&&<p><strong>{t('debugCode')}: {challenge.debug_code}</strong></p>}</div>}
        <Button type="submit" disabled={action.busy}>{action.busy?t('loading'):enrollment?t('inviteFinish'):challenge?t('inviteVerifyEmail'):t('requestCode')}</Button>
        {Boolean(enrollment||challenge)&&<Button variant="ghost" disabled={action.busy} onClick={restart}>{t('inviteRestart')}</Button>}
      </form>
    </>}
    <hr className="divider"/><p><Link href="/login" className="text-link">{t('inviteExistingLogin')}</Link></p><a href={webUrl} className="text-link" referrerPolicy="no-referrer">{t('backToPlatform')}</a>
  </div></div></div>;
}
