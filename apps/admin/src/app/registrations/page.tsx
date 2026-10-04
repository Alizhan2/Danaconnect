'use client';
import {useState} from 'react';
import {api, mutate, safeUrl} from '@/lib/api';
import type {Direction, User} from '@/lib/types';
import {dateTime, useLocale} from '@/lib/i18n';
import {formatDate} from '@/lib/date-format';
import {AdminShell} from '@/components/shell';
import {Badge, Button, Field} from '@/components/ui';
import {ActionNotice, DataState, NoData, Pager, useAction, useLoad, usePaged} from '@/components/common';

function Review({user, directions, refresh}: {user: User; directions: Direction[]; refresh: () => Promise<void>}) {
  const {t, label, locale} = useLocale();
  const action = useAction();
  const [reason, setReason] = useState('');
  return <article className="card">
    <div className="row"><h3>{user.full_name}</h3><Badge tone="blue">{label(user.role)}</Badge></div>
    <p>{user.email} · {user.city} · {user.timezone}</p>
    <p>{t('phone')}: {user.phone || t('notProvided')}</p>
    {user.birth_date && <p>{t('birthDate')}: {formatDate(user.birth_date, locale)}</p>}
    <p>{t('organization')}: {user.organization || t('notProvided')}</p>
    <p>{t('directions')}: {user.direction_ids.map(id => directions.find(d => d.id === id)?.[`name_${locale}`] || id).join(', ')}</p>
    <h4>{t('bio')}</h4><p className="pre-line">{user.bio}</p>
    {user.role === 'mentor' && <>
      <h4>{t('expertise')}</h4><p className="pre-line">{user.expertise}</p>
      <p>{t('capacity')}: {user.capacity}</p>
      <p>{t('mentorCommitment')}: <strong>{t(user.mentor_commitment && user.mentor_commitment_accepted_at ? 'commitmentConfirmed' : 'commitmentMissing')}</strong>
        {user.mentor_commitment && user.mentor_commitment_accepted_at && <> · {dateTime(user.mentor_commitment_accepted_at, locale)}</>}
      </p>
      {user.evidence_urls?.map((url, index) => safeUrl(url) && <p key={index}><a className="text-link" href={safeUrl(url)} target="_blank" rel="noopener noreferrer">{t('evidence')} {index + 1}</a></p>)}
    </>}
    <hr className="divider"/><ActionNotice action={action}/>
    <Field label={t('reason')}><textarea maxLength={2000} value={reason} onChange={e => setReason(e.target.value)}/></Field>
    <div className="actions">
      <Button disabled={action.busy || !user.profile_completed} onClick={() => action.run(async () => {await mutate(`/admin/registrations/${user.id}/review`, {decision: 'approved', reason}); await refresh();})}>{t('approve')}</Button>
      <Button disabled={action.busy || !reason.trim()} variant="secondary" onClick={() => action.run(async () => {await mutate(`/admin/registrations/${user.id}/review`, {decision: 'changes_requested', reason}); await refresh();})}>{t('changesRequested')}</Button>
    </div>
  </article>;
}

function Registrations() {
  const {t, locale} = useLocale();
  const [role, setRole] = useState('');
  const [direction, setDirection] = useState('');
  const directions = useLoad(() => api<Direction[]>('/admin/directions'));
  const query = new URLSearchParams();
  if (role) query.set('role', role);
  if (direction) query.set('direction_id', direction);
  const load = usePaged<User>(`/admin/registrations?${query}`);
  return <div className="stack">
    <div className="filters">
      <Field label={t('role')}><select value={role} onChange={e => setRole(e.target.value)}>
        <option value="">{t('allRoles')}</option><option value="mentee">{t('mentee')}</option><option value="mentor">{t('mentor')}</option>
      </select></Field>
      <Field label={t('directions')}><select value={direction} onChange={e => setDirection(e.target.value)}>
        <option value="">{t('allDirections')}</option>
        {directions.data?.map(item => <option key={item.id} value={item.id}>{item[`name_${locale}`]}</option>)}
      </select></Field>
      <Button variant="secondary" onClick={load.reload}>{t('refresh')}</Button>
    </div>
    {Boolean(directions.error) && <DataState {...directions} retry={directions.reload}>{null}</DataState>}
    <DataState {...load} retry={load.reload}>
      {load.data?.length ? <div className="grid-2">{load.data.map(user => <Review key={user.id} user={user} directions={directions.data || []} refresh={load.reload}/>)}</div> : <NoData/>}
      <Pager {...load} hasNext={load.data?.length === 25}/>
    </DataState>
  </div>;
}

export default function Page() {return <AdminShell title="registrations" description="registrationNote"><Registrations/></AdminShell>;}
