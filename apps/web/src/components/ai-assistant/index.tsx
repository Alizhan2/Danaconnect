'use client';
import { useState, type FormEvent } from 'react';
import { api } from '@/lib/api';
import { useLocale } from '@/lib/i18n';
import { Badge, Button, EmptyState, Field, SectionHeading } from '@/components/ui';
import { ActionNotice, LoadState, mutate, useAction, useLoad } from '@/components/workflows/common';

export type AIDraft = { title: string; problem: string; description: string; goal: string; steps: string[]; required_skills: string[]; questions: string[] };
type AIStatus = { available: boolean; reason: string | null; remaining_today: number; max_input_chars: number };
type Preview = { id: string; status: string; proposal: AIDraft };

export function AITextAssistant({ purpose = 'project', initialText = '', onApply }: { purpose?: 'project' | 'profile' | 'goal'; initialText?: string; onApply?: (draft: AIDraft) => void }) {
  const { tr, locale } = useLocale();
  const action = useAction();
  const load = useLoad(() => api<AIStatus>('/ai/status'));
  const [text, setText] = useState(initialText);
  const [consent, setConsent] = useState(false);
  const [preview, setPreview] = useState<AIDraft | null>(null);
  const [applied, setApplied] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault(); setApplied(false);
    await action.run(async () => { const result = await mutate<Preview>('/ai/structure', { text, purpose, locale, consent }); setPreview(result.proposal); await load.reload(); }, tr('Предложение готово для просмотра'));
  }
  return <section className="panel stack"><SectionHeading title={tr('ИИ-помощник для черновика')} description={tr('ИИ поможет упорядочить текст. Проверьте предложение и примените его вручную. Формы и регистрация работают без ИИ.')} /><ActionNotice action={action} /><LoadState {...load} retry={load.reload}>
    {load.data && !load.data.available && <div className="notice">{tr('ИИ-помощник не подключён. Заполните текст вручную.')}</div>}
    <form className="stack" onSubmit={submit}><Field label={tr('Ваш черновик')}><textarea required minLength={10} maxLength={load.data?.max_input_chars ?? 6000} value={text} onChange={event => { setText(event.target.value); setPreview(null); }} /></Field><label className="check-row"><input type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)} />{tr('Разрешаю отправить этот текст в OpenAI для подготовки предложения. Не добавляю имена, контакты или закрытые сведения третьих лиц.')}</label><div className="row"><Button disabled={action.busy || !consent || !load.data?.available || !load.data.remaining_today} type="submit">{tr('Подготовить предложение')}</Button><span className="muted">{tr('Запросов осталось сегодня')}: {load.data?.remaining_today ?? 0}</span></div></form>
    {preview && <article className="card stack"><Badge>{tr('Предложение ИИ — проверьте перед использованием')}</Badge><strong>{preview.title}</strong><p style={{ whiteSpace: 'pre-wrap' }}>{preview.problem}</p><p style={{ whiteSpace: 'pre-wrap' }}>{preview.description}</p><p><strong>{tr('Цель')}: </strong>{preview.goal}</p>{preview.steps.length > 0 && <ol>{preview.steps.map((step, index) => <li key={index}>{step}</li>)}</ol>}{preview.required_skills.length > 0 && <p>{tr('Навыки')}: {preview.required_skills.join(', ')}</p>}{preview.questions.length > 0 && <><strong>{tr('Что нужно уточнить')}</strong><ul>{preview.questions.map((question, index) => <li key={index}>{question}</li>)}</ul></>}{onApply && <Button variant="secondary" onClick={() => { onApply(preview); setApplied(true); }}>{tr('Применить к моему черновику')}</Button>}{applied && <div className="success">{tr('Черновик заполнен. Проверьте поля и сохраните форму самостоятельно.')}</div>}</article>}
  </LoadState></section>;
}

export function AIReviewPreference() {
  const { tr } = useLocale();
  const action = useAction();
  const load = useLoad(() => api<{ allow_admin_review: boolean }>('/me/ai-preference'));
  return <section className="panel stack"><SectionHeading title={tr('Помощь ИИ при проверке анкеты')} description={tr('Можно разрешить администратору анализ описания опыта и целей через OpenAI. Поля имени, email, телефона и даты рождения не отправляются. Не добавляйте их в описание. Решение принимает человек. Разрешение можно отозвать.')} /><ActionNotice action={action} /><LoadState {...load} retry={load.reload}><label className="check-row"><input type="checkbox" disabled={action.busy} checked={load.data?.allow_admin_review ?? false} onChange={event => { const allow = event.target.checked; void action.run(async () => { await mutate('/me/ai-preference', { allow_admin_review: allow }, 'PUT'); await load.reload(); }, tr('Настройка ИИ сохранена')); }} />{tr('Разрешаю проверку описания анкеты с помощью ИИ')}</label></LoadState></section>;
}

export function AIMentorRecommendations({ directionId }: { directionId: string }) {
  const { tr, locale } = useLocale();
  const action = useAction();
  const status = useLoad(() => api<AIStatus>('/ai/status'));
  const [goal, setGoal] = useState('');
  const [consent, setConsent] = useState(false);
  const [recommendations, setRecommendations] = useState<Array<{ candidate_id: string; full_name: string; reason: string; matching_skills: string[] }> | null>(null);
  async function submit(event: FormEvent) {
    event.preventDefault();
    await action.run(async () => { const result = await mutate<{ proposal: { recommendations: NonNullable<typeof recommendations> } }>('/ai/mentor-recommendations', { direction_id: directionId, goal, locale, consent, skills: [] }); setRecommendations(result.proposal.recommendations); await status.reload(); }, tr('Рекомендации готовы для просмотра'));
  }
  return <section className="panel stack"><SectionHeading title={tr('Подбор ментора с пояснениями')} description={tr('ИИ рассматривает только одобренных доступных менторов в выбранном направлении. Рекомендация не создаёт заявку и не резервирует место.')} /><ActionNotice action={action} /><LoadState {...status} retry={status.reload}>{status.data && !status.data.available && <div className="notice">{tr('ИИ-помощник не подключён. Каталог менторов доступен без ИИ.')}</div>}<form className="stack" onSubmit={submit}><Field label={tr('С чем нужна помощь')}><textarea required minLength={10} maxLength={2500} value={goal} onChange={event => setGoal(event.target.value)} /></Field><label className="check-row"><input type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)} />{tr('Разрешаю обработку моего запроса в OpenAI для подбора ментора.')}</label><Button disabled={action.busy || !consent || !status.data?.available || !status.data.remaining_today || !directionId} type="submit">{tr('Получить рекомендации')}</Button></form>{recommendations && (!recommendations.length ? <EmptyState title={tr('В этом направлении нет доступных менторов')} /> : <div className="stack">{recommendations.map(item => <article className="card" key={item.candidate_id}><h3>{item.full_name}</h3><p>{item.reason}</p>{item.matching_skills.length > 0 && <p>{item.matching_skills.join(', ')}</p>}<Button href={`/catalog/${item.candidate_id}`} variant="secondary">{tr('Открыть профиль ментора')}</Button></article>)}</div>)}</LoadState></section>;
}
