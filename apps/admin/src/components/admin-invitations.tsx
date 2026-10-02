'use client';
import {useState,type FormEvent} from 'react';
import {api,ApiError,mutate} from '@/lib/api';
import type {AdminInvitation} from '@/lib/admin-types';
import {canRevokeInvitation} from '@/lib/admin-invitations';
import {dateTime,useLocale,type Label,type Locale} from '@/lib/i18n';
import {ActionNotice,DataState,NoData,useAction,useLoad} from './common';
import {Badge,Button,Field,SectionHeading} from './ui';

const invitationLabels:Record<AdminInvitation['status'],Label>={pending:'invitePending',accepted:'inviteAccepted',revoked:'inviteRevoked',expired:'inviteExpired'};
const deliveryLabels:Record<NonNullable<AdminInvitation['delivery_status']>,Label>={pending:'inviteMailQueued',leased:'inviteMailSending',sent:'inviteMailSent',failed:'inviteMailFailed'};

export function AdminInvitations(){
  const {locale,t}=useLocale();
  const load=useLoad(()=>api<{items:AdminInvitation[]}>('/admin/invitations'));
  const action=useAction();
  const [email,setEmail]=useState('');
  const [name,setName]=useState('');
  const [invitationLocale,setInvitationLocale]=useState<Locale>(locale);
  const [confirmed,setConfirmed]=useState(false);
  const [revokeId,setRevokeId]=useState('');
  const [lastCreated,setLastCreated]=useState<AdminInvitation>();
  async function create(event:FormEvent){
    event.preventDefault();
    if(!confirmed)return;
    await action.run(async()=>{
      const invitation=await mutate<AdminInvitation>('/admin/invitations',{email:email.trim(),full_name:name.trim(),locale:invitationLocale});
      setLastCreated(invitation);setEmail('');setName('');setConfirmed(false);
      await load.reload();
    });
  }
  if(load.error instanceof ApiError&&(load.error.status===401||load.error.status===403))return <section className="panel" aria-label={t('adminInvitations')}><SectionHeading title={t('adminInvitations')}/><p>{t('inviteAssuredLogin')}</p><Button href="/login?returnTo=%2Fusers">{t('login')}</Button></section>;
  return <section className="panel stack" aria-label={t('adminInvitations')}>
    <SectionHeading title={t('adminInvitations')} description={t('inviteNote')} action={<Button variant="secondary" disabled={action.busy||load.loading} onClick={load.reload}>{t('refresh')}</Button>}/>
    <ActionNotice action={{...action,success:false}}/>
    {action.error instanceof ApiError&&action.error.status===409&&<p role="status">{t('inviteConflict')}</p>}
    {lastCreated&&<div className="success" role="status"><strong>{t('inviteCreated')}: {lastCreated.email}</strong><p>{t('inviteMailQueuedNote')}</p></div>}
    <form className="form-stack" onSubmit={create}>
      <div className="form-grid">
        <Field label={t('name')}><input required minLength={2} maxLength={160} autoComplete="off" value={name} onChange={e=>setName(e.target.value)} disabled={action.busy}/></Field>
        <Field label={t('email')}><input required type="email" maxLength={254} autoComplete="off" value={email} onChange={e=>setEmail(e.target.value)} disabled={action.busy}/></Field>
        <Field label={t('inviteLanguage')}><select value={invitationLocale} onChange={e=>setInvitationLocale(e.target.value as Locale)} disabled={action.busy}><option value="ru">Русский</option><option value="kk">Қазақша</option><option value="en">English</option></select></Field>
      </div>
      <div className="notice"><strong>{t('inviteFullAccess')}</strong><p>{t('inviteMfaRequired')}</p></div>
      <label className="check-row"><input required type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)} disabled={action.busy}/><span>{t('inviteConfirmAccess')}</span></label>
      <div><Button type="submit" disabled={action.busy||!confirmed||name.trim().length<2}>{action.busy?t('loading'):t('inviteSend')}</Button></div>
    </form>
    <DataState {...load} retry={load.reload}>
      {!load.data?.items.length?<NoData/>:<div className="table-wrap"><table><thead><tr><th>{t('users')}</th><th>{t('status')}</th><th>{t('mail')}</th><th>{t('inviteDeadline')}</th><th>{t('action')}</th></tr></thead><tbody>{load.data.items.map(invitation=><tr key={invitation.id}>
        <td><strong>{invitation.full_name}</strong><small className="word-break">{invitation.email}</small><small>{t('created')}: {dateTime(invitation.created_at,locale)}</small></td>
        <td><Badge tone={invitation.status==='accepted'?'success':invitation.status==='pending'?'warning':'neutral'}>{t(invitationLabels[invitation.status])}</Badge></td>
        <td><Badge tone={invitation.delivery_status==='failed'?'danger':invitation.delivery_status==='sent'?'blue':'neutral'}>{invitation.delivery_status?t(deliveryLabels[invitation.delivery_status]):t('unavailable')}</Badge></td>
        <td>{dateTime(invitation.expires_at,locale)}{invitation.accepted_at&&<small>{t('inviteAccepted')}: {dateTime(invitation.accepted_at,locale)}</small>}</td>
        <td>{canRevokeInvitation(invitation.status)&&(revokeId===invitation.id?<div className="form-stack"><p>{t('inviteRevokeNote')}</p><Button variant="danger" disabled={action.busy} onClick={()=>action.run(async()=>{await mutate(`/admin/invitations/${invitation.id}`,undefined,'DELETE');setRevokeId('');setLastCreated(undefined);await load.reload();})}>{t('inviteConfirmRevoke')}</Button><Button variant="ghost" disabled={action.busy} onClick={()=>setRevokeId('')}>{t('cancel')}</Button></div>:<Button variant="secondary" disabled={action.busy} onClick={()=>{action.clear();setRevokeId(invitation.id);}}>{t('inviteRevoke')}</Button>)}</td>
      </tr>)}</tbody></table></div>}
      <p className="muted">{t('inviteMailStatusNote')}</p>
    </DataState>
  </section>;
}
