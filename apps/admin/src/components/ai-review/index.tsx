'use client';
import { useState, type FormEvent } from 'react';
import { api, mutate } from '@/lib/api';
import { useLocale } from '@/lib/i18n';
import { Button, Field, Badge, EmptyState } from '@/components/ui';
import { ActionNotice, DataState, useAction, useLoad } from '@/components/common';

type Proposal = { id: string; subject_user_id: string; status: string; proposal: { completeness_score: number; summary: string; strengths: string[]; missing_information: string[]; questions: string[] } | null; review_reason?: string; override_summary?: string };
const phrases: Record<string, [string, string, string]> = {
  title: ['Предложения ИИ по анкетам', 'Сауалнамалар бойынша ЖИ ұсыныстары', 'AI profile review proposals'],
  unavailable: ['ИИ не подключён. Проверяйте анкеты вручную.', 'ЖИ қосылмаған. Сауалнамаларды қолмен тексеріңіз.', 'AI is not connected. Review applications manually.'],
  note: ['Баллы показывают полноту описания, а не пригодность участника. Подтверждение предложения не активирует аккаунт. Регистрацию проверяйте отдельно.', 'Ұпай сипаттаманың толықтығын көрсетеді, қатысушының жарамдылығын емес. Ұсынысты растау аккаунтты белсендірмейді. Тіркелуді бөлек тексеріңіз.', 'Scores describe information completeness. Confirming AI advice never activates an account. Review registration separately.'],
  request: ['Подготовить предложение по анкете', 'Сауалнама бойынша ұсыныс дайындау', 'Generate profile advice'],
  consent: ['Участник должен разрешить такую проверку в своей анкете. Подтверждаю обработку описания через OpenAI.', 'Қатысушы сауалнамасында осы тексеруге рұқсат беруі керек. Сипаттаманы OpenAI арқылы өңдеуді растаймын.', 'The participant must opt in through their own profile. I confirm processing of the description through OpenAI.'],
  user: ['ID анкеты участника', 'Қатысушы сауалнамасының ID', 'Participant profile ID'],
  score: ['Полнота описания', 'Сипаттаманың толықтығы', 'Description completeness'],
  missing: ['Что требует уточнения', 'Нақтылауды қажет ететін мәліметтер', 'Information to clarify'],
  decision: ['Решение по предложению', 'Ұсыныс бойынша шешім', 'Decision on AI advice'],
  approved: ['Подтвердить предложение', 'Ұсынысты растау', 'Confirm advice'],
  dismissed: ['Отклонить предложение', 'Ұсынысты қабылдамау', 'Dismiss advice'],
  overridden: ['Заменить своим выводом', 'Өз қорытындысымен ауыстыру', 'Override with human conclusion'],
  reason: ['Пояснение решения', 'Шешімнің түсіндірмесі', 'Decision reason'],
  override: ['Вывод администратора', 'Әкімшінің қорытындысы', 'Administrator conclusion'],
  save: ['Сохранить решение по предложению', 'Ұсыныс бойынша шешімді сақтау', 'Save decision on advice'],
  empty: ['Предложений ИИ пока нет', 'Әзірге ЖИ ұсыныстары жоқ', 'No AI advice yet'],
  pending: ['Подготавливается', 'Дайындалуда', 'Preparing'],
  ready: ['Ожидает решения человека', 'Адамның шешімін күтуде', 'Awaiting human decision'],
  failed: ['Не удалось подготовить', 'Дайындау мүмкін болмады', 'Generation failed'],
  status_approved: ['Предложение подтверждено', 'Ұсыныс расталды', 'Advice confirmed'],
  status_dismissed: ['Предложение отклонено', 'Ұсыныс қабылданбады', 'Advice dismissed'],
  status_overridden: ['Вывод заменён человеком', 'Қорытынды адаммен ауыстырылды', 'Advice overridden by a human'],
};

export function AIReviewPanel() {
  const { locale } = useLocale();
  const t = (key: string) => phrases[key]?.[locale === 'ru' ? 0 : locale === 'kk' ? 1 : 2] ?? key;
  const action = useAction();
  const [userId, setUserId] = useState('');
  const [consent, setConsent] = useState(false);
  const load = useLoad(async () => { const [status, items] = await Promise.all([api<{ available: boolean; remaining_today: number }>('/ai/status'), api<Proposal[]>('/admin/ai/proposals')]); return { status, items }; });
  async function request(event: FormEvent) { event.preventDefault(); await action.run(async () => { await mutate(`/admin/ai/profile-review/${encodeURIComponent(userId)}`, { consent, locale }); await load.reload(); }); }
  return <section className="panel stack"><h2>{t('title')}</h2><p className="notice">{t('note')}</p><ActionNotice action={action} /><DataState {...load} retry={load.reload}>{load.data && !load.data.status.available && <div className="notice">{t('unavailable')}</div>}<form className="stack" onSubmit={request}><Field label={t('user')}><input required value={userId} onChange={event => setUserId(event.target.value)} /></Field><label className="check-row"><input type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)} />{t('consent')}</label><Button type="submit" disabled={action.busy || !consent || !load.data?.status.available || !load.data.status.remaining_today}>{t('request')}</Button></form>{!load.data?.items.length ? <EmptyState title={t('empty')} /> : load.data.items.map(item => <ReviewCard key={item.id} item={item} t={t} refresh={load.reload} />)}</DataState></section>;
}

function ReviewCard({ item, t, refresh }: { item: Proposal; t: (key: string) => string; refresh: () => Promise<void> }) {
  const action = useAction();
  const [decision, setDecision] = useState('approved');
  const [reason, setReason] = useState('');
  const [override, setOverride] = useState('');
  return <article className="card stack"><div className="row"><strong>{item.subject_user_id}</strong><Badge>{t(['approved', 'dismissed', 'overridden'].includes(item.status) ? 'status_' + item.status : item.status)}</Badge></div>{item.proposal && <><p>{t('score')}: {item.proposal.completeness_score}/100</p><p>{item.proposal.summary}</p><h3>{t('missing')}</h3><ul>{item.proposal.missing_information.map((fact, index) => <li key={index}>{fact}</li>)}</ul><ul>{item.proposal.questions.map((question, index) => <li key={index}>{question}</li>)}</ul></>}<ActionNotice action={action} />{item.status === 'ready' && <form className="stack" onSubmit={event => { event.preventDefault(); void action.run(async () => { await mutate(`/admin/ai/proposals/${item.id}/decision`, { decision, reason, override_summary: decision === 'overridden' ? override : null }); await refresh(); }); }}><Field label={t('decision')}><select value={decision} onChange={event => setDecision(event.target.value)}>{['approved', 'dismissed', 'overridden'].map(value => <option key={value} value={value}>{t(value)}</option>)}</select></Field><Field label={t('reason')}><textarea required minLength={5} maxLength={2000} value={reason} onChange={event => setReason(event.target.value)} /></Field>{decision === 'overridden' && <Field label={t('override')}><textarea required maxLength={3000} value={override} onChange={event => setOverride(event.target.value)} /></Field>}<Button disabled={action.busy} type="submit">{t('save')}</Button></form>}{item.review_reason && <p>{item.review_reason}</p>}{item.override_summary && <p>{item.override_summary}</p>}</article>;
}

