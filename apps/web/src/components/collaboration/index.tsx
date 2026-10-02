'use client';

import { useEffect, useState, type FormEvent } from 'react';
import { api } from '@/lib/api';
import { useLocale } from '@/lib/i18n';
import type { User } from '@/lib/types';
import { Badge, Button, EmptyState, Field, SectionHeading } from '@/components/ui';
import { ActionNotice, dateTime, LoadState, mutate, statusText, useAction, useLoad } from '@/components/workflows/common';
import { collaborationTranslations } from './translations';

type Comment = { id: string; author_id: string; author_name: string; body: string; scope: string; status: string; created_at: string };
type Attachment = { id: string; uploader_id: string; filename: string; size_bytes: number; created_at: string; download_path: string };
type Invitation = { id: string; project_id: string; project_title: string; target_email: string; status: string; expires_at: string; incoming: boolean; email_queued: boolean };
type Member = { user_id: string; full_name: string; role: string; member_role: string; active: boolean; can_remove: boolean; is_self_leave: boolean };

export function ProjectDiscussion({ projectId, user, scope = 'public' }: { projectId: string; user: User; scope?: 'public' | 'team' }) {
  const { tr, locale } = useLocale();
  const action = useAction();
  const [body, setBody] = useState('');
  const load = useLoad(() => api<Comment[]>(`/projects/${projectId}/comments?scope=${scope}`), [projectId, scope]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    await action.run(async () => { await mutate(`/projects/${projectId}/comments`, { body, scope }); setBody(''); await load.reload(); }, tr(scope === 'public' ? 'Комментарий отправлен на модерацию' : 'Комментарий добавлен'));
  }
  return <section className="panel stack"><SectionHeading title={tr(scope === 'public' ? 'Обсуждение проекта' : 'Обсуждение команды')} description={tr(scope === 'public' ? 'Публичные комментарии и имя автора будут видны участникам платформы после модерации. Не публикуйте закрытые материалы.' : 'Обсуждение доступно только команде проекта и уполномоченному администратору с актуальными согласиями.')} />
    <ActionNotice action={action} /><LoadState {...load} retry={load.reload}>
      {!load.data?.length ? <EmptyState title={tr('Комментариев пока нет')} /> : <div className="stack">{load.data.map(comment => <article className="card" key={comment.id}><div className="row"><strong>{comment.author_name}</strong><Badge>{tr(statusText(comment.status))}</Badge></div><p style={{ whiteSpace: 'pre-wrap' }}>{comment.body}</p><p className="muted">{dateTime(comment.created_at, user.timezone, locale)}</p>{comment.author_id === user.id && <Button variant="ghost" disabled={action.busy} onClick={() => action.run(async () => { await mutate(`/comments/${comment.id}`, undefined, 'DELETE'); await load.reload(); }, tr('Комментарий скрыт'))}>{tr('Удалить комментарий')}</Button>}</article>)}</div>}
      <form onSubmit={submit} className="stack"><Field label={tr('Ваш комментарий')}><textarea required minLength={1} maxLength={5000} value={body} onChange={event => setBody(event.target.value)} /></Field><Button disabled={action.busy} type="submit">{tr(scope === 'public' ? 'Отправить на модерацию' : 'Добавить комментарий')}</Button></form>
    </LoadState></section>;
}

export function PrivateAttachments({ projectId, user, ownerId }: { projectId: string; user: User; ownerId: string }) {
  const { tr, locale } = useLocale();
  const action = useAction();
  const [file, setFile] = useState<File | null>(null);
  const [inputVersion, setInputVersion] = useState(0);
  const load = useLoad(async () => { const [items, policy] = await Promise.all([api<Attachment[]>(`/projects/${projectId}/attachments`), api<{ max_bytes: number; extensions: string[]; storage_configured: boolean }>('/attachment-policy')]); return { items, policy }; }, [projectId]);
  async function upload(event: FormEvent) {
    event.preventDefault();
    await action.run(async () => {
      if (!file) throw new Error(tr('Выберите файл'));
      if (load.data && file.size > load.data.policy.max_bytes) throw new Error(tr('Файл превышает допустимый размер'));
      const data = new FormData(); data.append('file', file);
      await api(`/projects/${projectId}/attachments`, { method: 'POST', body: data });
      setFile(null); setInputVersion(value => value + 1); await load.reload();
    }, tr('Закрытый файл загружен'));
  }
  return <section className="panel stack"><SectionHeading title={tr('Закрытые файлы проекта')} description={tr('Просмотр и скачивание требуют членства в команде и актуального NDA. Файлы не публикуются в открытом каталоге.')} /><ActionNotice action={action} /><LoadState {...load} retry={load.reload}>
    {load.data && !load.data.policy.storage_configured && <div className="notice">{tr('Закрытое хранилище пока не подключено. Загрузка недоступна.')}</div>}
    {!load.data?.items.length ? <EmptyState title={tr('Файлов пока нет')} /> : <div className="stack">{load.data.items.map(item => <article className="card" key={item.id}><strong>{item.filename}</strong><p className="muted">{(item.size_bytes / 1024 / 1024).toFixed(2)} MB · {dateTime(item.created_at, user.timezone, locale)}</p><div className="actions"><a className="text-link" href={item.download_path}>{tr('Скачать файл')}</a>{(item.uploader_id === user.id || ownerId === user.id || user.role === 'admin') && <Button variant="danger" disabled={action.busy} onClick={() => action.run(async () => { await mutate(`/attachments/${item.id}`, undefined, 'DELETE'); await load.reload(); }, tr('Файл удалён'))}>{tr('Удалить файл')}</Button>}</div></article>)}</div>}
    <form className="stack" onSubmit={upload}><Field label={tr('Добавить закрытый файл')} hint={load.data ? `${load.data.policy.extensions.join(', ')} · ${(load.data.policy.max_bytes / 1024 / 1024).toFixed(0)} MB` : ''}><input key={inputVersion} type="file" required accept=".pdf,.png,.jpg,.jpeg,.txt,.md,.docx" onChange={event => setFile(event.target.files?.[0] ?? null)} /></Field><Button disabled={action.busy || !load.data?.policy.storage_configured} type="submit">{tr('Загрузить файл')}</Button></form>
  </LoadState></section>;
}

export function ProjectTeam({ projectId, user, canInvite, onChanged }: { projectId: string; user: User; canInvite: boolean; onChanged?: () => void | Promise<void> }) {
  const { tr: appTr, locale } = useLocale();
  const tr = (text: string) => locale === 'ru' ? appTr(text) : collaborationTranslations[text]?.[locale === 'kk' ? 0 : 1] ?? appTr(text);
  const action = useAction();
  const removal = useAction();
  const [email, setEmail] = useState('');
  const [deliveryNotice, setDeliveryNotice] = useState('');
  const [selected, setSelected] = useState<Member | null>(null);
  const [reason, setReason] = useState('');
  const [departed, setDeparted] = useState(false);
  const load = useLoad(() => api<Member[]>(`/projects/${projectId}/team`), [projectId]);
  useEffect(() => { setSelected(null); setReason(''); setDeparted(false); }, [projectId, user.id]);
  async function invite(event: FormEvent) {
    event.preventDefault();
    await action.run(async () => { const result = await mutate<Invitation>(`/projects/${projectId}/invitations`, { email }); setEmail(''); setDeliveryNotice(tr(result.email_queued ? 'Email поставлен в очередь отправки.' : 'Приглашение сохранено в платформе. Email не отправлен: почтовый сервис не подключён.')); }, tr('Приглашение сохранено'));
  }
  async function remove(event: FormEvent) {
    event.preventDefault();
    if (!selected || reason.trim().length < 3) return;
    const target = selected;
    await removal.run(async () => {
      const result = await mutate<{ self_left: boolean }>(`/projects/${projectId}/team/${target.user_id}/remove`, { reason: reason.trim() });
      setSelected(null); setReason('');
      if (result.self_left) {
        setDeparted(true);
        load.setData([]);
      } else {
        await load.reload();
      }
      await onChanged?.();
    }, tr(target.is_self_leave ? 'Вы вышли из команды проекта' : 'Участник удалён из команды'));
  }
  const busy = action.busy || removal.busy;
  return <section className="panel stack">
    <SectionHeading title={tr('Команда проекта')} description={tr('Приглашение добавляет участника команды. Участие в менторстве согласуется отдельно через заявку.')} />
    <ActionNotice action={action} />
    {removal.error && <div className="error" role="alert">{tr(removal.error)}</div>}
    {removal.success && <div className="success" role="status">{tr(removal.success)}</div>}
    {departed ? <p className="notice">{tr('Членство завершено. Доступ через членство к закрытым материалам отозван. История проекта сохранена.')}</p> : <>
      {deliveryNotice && <div className="notice">{deliveryNotice}</div>}
      <LoadState {...load} retry={load.reload}>
        <div className="stack">{load.data?.map(member => <div className="row" key={member.user_id}>
          <strong>{member.full_name}</strong>
          <Badge>{tr(member.member_role === 'collaborator' ? 'Участник команды' : member.member_role === 'owner' ? 'Автор проекта' : statusText(member.member_role))}</Badge>
          {member.can_remove && <Button type="button" variant="danger" disabled={busy} onClick={() => { removal.clear(); setSelected(member); setReason(''); }}>{tr(member.is_self_leave ? 'Выйти из команды' : 'Удалить из команды')}</Button>}
        </div>)}</div>
        {selected && <form className="card stack" onSubmit={remove} aria-label={tr('Подтверждение изменения команды')}>
          <h3>{tr(selected.is_self_leave ? 'Подтвердите выход из команды' : 'Подтвердите удаление участника')}</h3>
          <strong>{selected.full_name}</strong>
          <p>{tr('Будет удалено только членство в команде. Доступ через членство к закрытым материалам прекратится. Комментарии, файлы, приглашения и история сохранятся.')}</p>
          <Field label={tr(selected.is_self_leave ? 'Причина выхода' : 'Причина удаления')} hint={tr('Причина будет сохранена в журнале действий. Не указывайте лишние личные данные.')}>
            <textarea required minLength={3} maxLength={2000} disabled={busy} value={reason} onChange={event => setReason(event.target.value)} />
          </Field>
          <div className="actions">
            <Button type="submit" variant="danger" disabled={busy || reason.trim().length < 3}>{tr(selected.is_self_leave ? 'Подтвердить выход' : 'Подтвердить удаление')}</Button>
            <Button type="button" variant="secondary" disabled={busy} onClick={() => { setSelected(null); setReason(''); removal.clear(); }}>{tr('Отмена')}</Button>
          </div>
        </form>}
        {canInvite && <form onSubmit={invite} className="form-grid"><Field label={tr('Email участника для приглашения')}><input required type="email" value={email} onChange={event => setEmail(event.target.value)} /></Field><Button disabled={busy} type="submit">{tr('Пригласить в команду')}</Button></form>}
        <p className="muted">{tr('Принять приглашение может только владелец указанного email после входа, одобрения анкеты и подтверждения документов.')}</p>
      </LoadState>
    </>}
  </section>;
}

export function InvitationList({ user }: { user: User }) {
  const { tr, locale } = useLocale();
  const action = useAction();
  const load = useLoad(() => api<Invitation[]>('/team-invitations'));
  const labels: Record<string, string> = { pending: 'Ожидает ответа', accepted: 'Принято', declined: 'Отклонено', revoked: 'Отозвано', expired: 'Истекло' };
  return <section className="stack"><ActionNotice action={action} /><LoadState {...load} retry={load.reload}>{!load.data?.length ? <EmptyState title={tr('Приглашений пока нет')} description={tr('Приглашения в проекты появятся здесь после приглашения на ваш email.')} /> : <div className="grid-2">{load.data.map(invitation => <article className="card" key={invitation.id}><div className="row"><h3>{invitation.project_title}</h3><Badge>{tr(labels[invitation.status] ?? invitation.status)}</Badge></div><p>{invitation.target_email}</p><p className="muted">{tr('Действует до')}: {dateTime(invitation.expires_at, user.timezone, locale)}</p><div className="actions"><Button href={`/projects/${invitation.project_id}`} variant="secondary">{tr('Открыть проект')}</Button>{invitation.status === 'pending' && (invitation.incoming ? <><Button disabled={action.busy} onClick={() => action.run(async () => { await mutate(`/team-invitations/${invitation.id}/decision`, { decision: 'accepted' }); await load.reload(); }, tr('Вы присоединились к команде'))}>{tr('Принять приглашение')}</Button><Button disabled={action.busy} variant="secondary" onClick={() => action.run(async () => { await mutate(`/team-invitations/${invitation.id}/decision`, { decision: 'declined' }); await load.reload(); }, tr('Приглашение отклонено'))}>{tr('Отклонить')}</Button></> : <Button disabled={action.busy} variant="danger" onClick={() => action.run(async () => { await mutate(`/team-invitations/${invitation.id}/revoke`); await load.reload(); }, tr('Приглашение отозвано'))}>{tr('Отозвать приглашение')}</Button>)}</div></article>)}</div>}</LoadState></section>;
}
