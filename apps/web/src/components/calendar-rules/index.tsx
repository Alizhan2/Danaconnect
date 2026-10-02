'use client';

import { useState, type FormEvent } from 'react';
import { api } from '@/lib/api';
import { useLocale } from '@/lib/i18n';
import type { Booking, User } from '@/lib/types';
import { Badge, Button, EmptyState, Field, SectionHeading } from '@/components/ui';
import { ActionNotice, LoadState, mutate, useAction, useLoad } from '@/components/workflows/common';

type Rule = {
  id: string; weekday: number; start_time: string; end_time: string; timezone: string;
  slot_minutes: number; starts_on: string; ends_on: string | null; horizon_weeks: number;
  dst_fold: 'first' | 'second'; active: boolean; generated_until: string | null;
};
type RuleInput = Omit<Rule, 'id' | 'active' | 'generated_until'>;
type Generation = { created: number; existing: number; conflicts: number; dst_skipped: number; generated_until: string };
type RuleResponse = { rule: Rule; generation: Generation };

function localToday(timezone: string) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date()).map(part => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day}`;
}

export function RecurringAvailability({ timezone, onChanged }: { timezone: string; onChanged?: () => void | Promise<void> }) {
  const { tr } = useLocale();
  const action = useAction();
  const load = useLoad(() => api<Rule[]>('/availability-rules'));
  const [editing, setEditing] = useState<string | null>(null);
  const [report, setReport] = useState<Generation | null>(null);
  const [form, setForm] = useState<RuleInput>({ weekday: 0, start_time: '09:00', end_time: '12:00', timezone, slot_minutes: 30, starts_on: localToday(timezone), ends_on: null, horizon_weeks: 8, dst_fold: 'first' });
  const weekdays = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье'];

  async function refresh() { await load.reload(); await onChanged?.(); }
  async function save(event: FormEvent) {
    event.preventDefault();
    await action.run(async () => {
      const result = await mutate<RuleResponse>(editing ? `/availability-rules/${editing}` : '/availability-rules', form, editing ? 'PATCH' : 'POST');
      setReport(result.generation); setEditing(null); await refresh();
    }, tr('Еженедельное расписание сохранено'));
  }
  function edit(rule: Rule) {
    setEditing(rule.id);
    setForm({ weekday: rule.weekday, start_time: rule.start_time, end_time: rule.end_time, timezone: rule.timezone, slot_minutes: rule.slot_minutes, starts_on: rule.starts_on, ends_on: rule.ends_on, horizon_weeks: rule.horizon_weeks, dst_fold: rule.dst_fold });
    setReport(null); action.clear();
  }

  return <section className="panel stack">
    <SectionHeading title={tr('Еженедельное расписание')} description={tr('Сохраните правило повторения. Свободные часы создаются на ограниченный период и продлеваются фоновым сервисом. Забронированные встречи сохраняются при изменении правила.')} />
    <ActionNotice action={action} />
    <form className="form-grid" onSubmit={save}>
      <Field label={tr('День недели')}><select value={form.weekday} onChange={event => setForm({ ...form, weekday: Number(event.target.value) })}>{weekdays.map((day, index) => <option key={day} value={index}>{tr(day)}</option>)}</select></Field>
      <Field label={tr('Часовой пояс')}><input required value={form.timezone} onChange={event => setForm({ ...form, timezone: event.target.value })} placeholder="Asia/Oral" /></Field>
      <Field label={tr('Начало доступности')}><input required type="time" value={form.start_time} onChange={event => setForm({ ...form, start_time: event.target.value })} /></Field>
      <Field label={tr('Окончание доступности')}><input required type="time" value={form.end_time} onChange={event => setForm({ ...form, end_time: event.target.value })} /></Field>
      <Field label={tr('Длительность встречи, минут')}><select value={form.slot_minutes} onChange={event => setForm({ ...form, slot_minutes: Number(event.target.value) })}>{[15, 30, 45, 60, 90, 120].map(value => <option key={value} value={value}>{value}</option>)}</select></Field>
      <Field label={tr('Период создания слотов, недель')}><input required type="number" min={1} max={12} value={form.horizon_weeks} onChange={event => setForm({ ...form, horizon_weeks: Number(event.target.value) })} /></Field>
      <Field label={tr('Действует с')}><input required type="date" value={form.starts_on} onChange={event => setForm({ ...form, starts_on: event.target.value })} /></Field>
      <Field label={tr('Действует до')} hint={tr('Необязательно. Без даты правило действует до отключения.')}><input type="date" value={form.ends_on ?? ''} onChange={event => setForm({ ...form, ends_on: event.target.value || null })} /></Field>
      <Field label={tr('Если локальное время повторяется при переводе часов')}><select value={form.dst_fold} onChange={event => setForm({ ...form, dst_fold: event.target.value as 'first' | 'second' })}><option value="first">{tr('Первое наступление времени')}</option><option value="second">{tr('Второе наступление времени')}</option></select></Field>
      <div className="actions"><Button disabled={action.busy} type="submit">{tr(editing ? 'Сохранить изменения' : 'Добавить правило')}</Button>{editing && <Button variant="secondary" onClick={() => setEditing(null)}>{tr('Отменить редактирование')}</Button>}</div>
    </form>
    <p className="muted">{tr('Несуществующее время при переводе часов пропускается. Интервалы с изменившейся длительностью также пропускаются. Пересечения с другими часами не создаются.')}</p>
    {report && <div className="notice" role="status">{tr('Создано интервалов')}: {report.created}. {tr('Уже существует')}: {report.existing}. {tr('Пересечения')}: {report.conflicts}. {tr('Пропущено из-за перевода часов')}: {report.dst_skipped}. {tr('Слоты созданы до')}: {report.generated_until} {tr('(дата не включена)')}.</div>}
    <LoadState {...load} retry={load.reload}>
      {!load.data?.length ? <EmptyState title={tr('Правил повторения пока нет')} /> : <div className="stack">{load.data.map(rule => <article className="card" key={rule.id}>
        <div className="row"><strong>{tr(weekdays[rule.weekday])} · {rule.start_time}–{rule.end_time}</strong><Badge tone={rule.active ? 'success' : 'neutral'}>{tr(rule.active ? 'Активно' : 'Отключено')}</Badge></div>
        <p>{rule.timezone} · {rule.slot_minutes} {tr('минут')} · {rule.horizon_weeks} {tr('недель вперёд')}</p>
        <p className="muted">{tr('Слоты созданы до')}: {rule.generated_until ?? '—'} {tr('(дата не включена)')}</p>
        {rule.active && <div className="actions">
          <Button disabled={action.busy} variant="secondary" onClick={() => edit(rule)}>{tr('Изменить')}</Button>
          <Button disabled={action.busy} variant="secondary" onClick={() => action.run(async () => { const result = await mutate<RuleResponse>(`/availability-rules/${rule.id}/regenerate`); setReport(result.generation); await refresh(); }, tr('Период расписания обновлён'))}>{tr('Обновить период')}</Button>
          <Button disabled={action.busy} variant="danger" onClick={() => action.run(async () => { await mutate(`/availability-rules/${rule.id}`, undefined, 'DELETE'); await refresh(); }, tr('Правило отключено. Забронированные встречи сохранены.'))}>{tr('Отключить')}</Button>
        </div>}
      </article>)}</div>}
    </LoadState>
  </section>;
}

export function MeetingControls({ booking, user, onChanged }: { booking: Booking; user: User; onChanged: () => void | Promise<void> }) {
  const { tr } = useLocale();
  const action = useAction();
  const [url, setUrl] = useState(booking.meeting_url ?? '');
  const [reason, setReason] = useState('');
  if (user.role !== 'mentor' || booking.mentor_id !== user.id || booking.status !== 'scheduled') return null;
  const started = new Date(booking.starts_at).getTime() <= Date.now();
  return <div className="stack">
    <ActionNotice action={action} />
    <form className="stack" onSubmit={event => { event.preventDefault(); void action.run(async () => { await mutate(`/bookings/${booking.id}/meeting-url`, { meeting_url: url || null }, 'PATCH'); await onChanged(); }, tr('Ссылка на встречу сохранена')); }}>
      <Field label={tr('Закрытая ссылка на видеовстречу')} hint={tr('Публичный HTTPS-адрес. Ссылка доступна только сторонам встречи и администратору.')}><input type="url" value={url} onChange={event => setUrl(event.target.value)} placeholder="https://meet.google.com/..." maxLength={2048} /></Field>
      <Button disabled={action.busy} type="submit" variant="secondary">{tr('Сохранить ссылку')}</Button>
    </form>
    {started && <details><summary>{tr('Отметить неявку')}</summary><form className="stack" onSubmit={event => { event.preventDefault(); void action.run(async () => { await mutate(`/bookings/${booking.id}/no-show`, { reason }); await onChanged(); }, tr('Неявка отмечена')); }}>
      <Field label={tr('Причина неявки')}><textarea required minLength={5} maxLength={1000} value={reason} onChange={event => setReason(event.target.value)} /></Field>
      <Button disabled={action.busy} variant="danger" type="submit">{tr('Подтвердить неявку')}</Button>
    </form></details>}
  </div>;
}
