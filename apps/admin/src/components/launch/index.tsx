'use client';
import { AlertCircle, CheckCircle2, ClipboardCheck } from 'lucide-react';
import { api } from '@/lib/api';
import type { Operations } from '@/lib/admin-types';
import type { User } from '@/lib/types';
import { useLocale, dateTime } from '@/lib/i18n';
import { Badge, Button } from '@/components/ui';
import { DataState, useLoad } from '@/components/common';
import { launchText, type LaunchPhrase } from './translations';

type Snapshot = { operations: Operations; administrator: User };
type Signal = { title: LaunchPhrase; present: boolean; development?: boolean };
type Group = { title: LaunchPhrase; signals: Signal[]; action: LaunchPhrase; note: LaunchPhrase; href?: string; link?: LaunchPhrase };

async function loadSnapshot(): Promise<Snapshot> {
  const [operations, administrator] = await Promise.all([
    api<Operations>('/admin/operations'), api<User>('/admin/me'),
  ]);
  return { operations, administrator };
}

function Checklist({ snapshot, refresh }: { snapshot: Snapshot; refresh: () => Promise<void> }) {
  const { locale } = useLocale();
  const text = (key: LaunchPhrase) => launchText(locale, key);
  const { operations, administrator } = snapshot;
  const ready = operations.readiness;
  const production = operations.environment === 'production';
  const number = (value: number | undefined) => value === undefined ? '—' : new Intl.NumberFormat(locale === 'kk' ? 'kk-KZ' : locale === 'ru' ? 'ru-RU' : 'en-GB').format(value);
  const groups: Group[] = [
    { title: 'hosting', signals: [{ title: 'production', present: production }], action: 'hostingMissing', note: 'hostingNote' },
    { title: 'database', signals: [{ title: 'pg', present: ready.postgresql === true }, { title: 'https', present: ready.https_origins === true }], action: 'databaseMissing', note: 'databaseNote', href: '/operations', link: 'system' },
    { title: 'mail', signals: [{ title: 'mailCheck', present: production && ready.email_configured === true, development: !production && ready.email_configured === true }], action: 'mailMissing', note: 'mailNote', href: '/operations', link: 'system' },
    { title: 'files', signals: [{ title: 'filesCheck', present: production && ready.private_storage_configured === true, development: !production && ready.private_storage_configured === true }], action: 'filesMissing', note: 'filesNote', href: '/operations', link: 'system' },
    { title: 'mfa', signals: [{ title: 'mfaCheck', present: ready.admin_mfa === true }], action: 'mfaMissing', note: 'mfaNote', href: '/users', link: 'users' },
    { title: 'legal', signals: [{ title: 'legalCheck', present: ready.legal_documents_configured === true }], action: 'legalMissing', note: 'legalNote', href: '/documents', link: 'documents' },
    { title: 'worker', signals: [{ title: 'workerCheck', present: ready.worker_recent_success === true && operations.worker?.recent_success === true }], action: 'workerMissing', note: 'workerNote', href: '/operations', link: 'system' },
    { title: 'clean', signals: [{ title: 'demo', present: ready.demo_disabled === true && operations.demo_mode === false }, { title: 'debug', present: ready.debug_codes_disabled === true }], action: 'cleanMissing', note: 'cleanNote' },
  ];
  const signals = groups.flatMap(group => group.signals);
  const configured = signals.filter(signal => signal.present).length;
  const manualItems: LaunchPhrase[] = ['manualMail', 'manualFiles', 'manualLegal', 'manualRestore', 'manualPilot'];
  const guideItems: LaunchPhrase[] = ['guide1', 'guide2', 'guide3', 'guide4', 'guide5', 'guide6'];

  return <div className="stack">
    <div className="row"><div><p className="muted">{text('intro')}</p><p>{text('account')}: <strong>{administrator.full_name || administrator.email}</strong></p></div><Button variant="secondary" onClick={refresh}>{text('refresh')}</Button></div>
    <section className="panel stack" aria-label={text('signals')}>
      <div className="row"><ClipboardCheck size={28}/><h2>{text('signals')}</h2><Badge tone="blue">{configured} {text('count')} {signals.length}</Badge></div>
      <p className="muted">{text('summary')}</p>
      <a href="#operator-guide" className="text-link">{text('instructions')}</a>
    </section>
    <div className="profile-grid">
      {groups.map(group => <section className="panel stack" key={group.title}>
        <h2>{text(group.title)}</h2>
        {group.signals.map(signal => <div className="operational-row" key={signal.title}>
          <span className="row">{signal.present ? <CheckCircle2 size={18} color="#030ba6"/> : <AlertCircle size={18} color="#9a7920"/>}{text(signal.title)}</span>
          <Badge tone={signal.present ? 'blue' : signal.development ? 'neutral' : 'warning'}>{text(signal.present ? 'detected' : signal.development ? 'local' : 'configure')}</Badge>
        </div>)}
        {!group.signals.every(signal => signal.present) && <p>{text(group.action)}</p>}
        <p className="muted">{text(group.note)}</p>
        {group.title === 'mail' && <p>{text('queued')}: {number(operations.counts.email_pending)} · {text('failed')}: {number(operations.counts.email_failed)}</p>}
        {group.title === 'worker' && <p>{text('lastRun')}: {operations.worker?.last_finished_at ? dateTime(operations.worker.last_finished_at, locale, administrator.timezone || 'Asia/Oral') : '—'}</p>}
        {group.href && group.link ? <Button variant="secondary" href={group.href}>{text(group.link)}</Button> : <a className="text-link" href="#operator-guide">{text('instructions')}</a>}
      </section>)}
    </div>
    <section className="panel stack">
      <div className="row"><h2>{text('manualTitle')}</h2><Badge>{text('manual')}</Badge></div>
      <p className="muted">{text('manualNote')}</p>
      {manualItems.map(item => <div className="operational-row" key={item}><p>{text(item)}</p><Badge>{text('unknown')}</Badge></div>)}
    </section>
    <section className="panel stack">
      <h2>{text('optional')}</h2><p className="muted">{text('optionalNote')}</p>
      <div className="profile-grid">
        <div className="stack"><div className="row"><h3>{text('google')}</h3><Badge tone={ready.google_configured === true ? 'blue' : 'neutral'}>{text(ready.google_configured === true ? 'detected' : 'unknown')}</Badge></div><p className="muted">{text('googleNote')}</p><Button variant="secondary" href="/operations">{text('system')}</Button></div>
        <div className="stack"><div className="row"><h3>{text('ai')}</h3><Badge>{text('unknown')}</Badge></div><p className="muted">{text('aiNote')}</p><Button variant="secondary" href="/ai-review">{text('aiLink')}</Button></div>
      </div>
    </section>
    <section id="operator-guide" className="panel stack">
      <h2>{text('guideTitle')}</h2><p className="muted">{text('guideNote')}</p>
      <ol>{guideItems.map(item => <li key={item}><p>{text(item)}</p></li>)}</ol>
      <div className="actions"><Button variant="secondary" href="/documents">{text('documents')}</Button><Button variant="secondary" href="/users">{text('users')}</Button><Button variant="secondary" href="/operations">{text('system')}</Button></div>
    </section>
  </div>;
}

export function PilotLaunch() {
  const load = useLoad(loadSnapshot);
  return <DataState {...load} retry={load.reload}>{load.data && <Checklist snapshot={load.data} refresh={load.reload}/>}</DataState>;
}
