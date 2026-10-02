'use client';
import type {AuditEvent} from '@/lib/admin-types';
import {useLocale,dateTime} from '@/lib/i18n';
import {AdminShell} from '@/components/shell';
import {Badge} from '@/components/ui';
import {DataState,NoData,Pager,usePaged} from '@/components/common';
function Audit(){const {t,label,locale}=useLocale();const load=usePaged<AuditEvent>('/admin/audit');return <DataState {...load} retry={load.reload}>{load.data?.length?<div className="table-wrap"><table><thead><tr><th>{t('created')}</th><th>{t('action')}</th><th>{t('actor')}</th><th>{t('entity')}</th><th>{t('details')}</th></tr></thead><tbody>{load.data.map(event=><tr key={event.id}><td>{dateTime(event.created_at,locale)}</td><td><Badge tone="blue">{event.action}</Badge></td><td className="word-break">{event.actor_id||'—'}</td><td>{label(event.entity_type)}<small className="word-break">{event.entity_id}</small></td><td><details><summary>{t('details')}</summary><pre className="code-block">{JSON.stringify(event.detail,null,2)}</pre></details></td></tr>)}</tbody></table></div>:<NoData/>}<Pager {...load} hasNext={load.data?.length===25}/></DataState>;}
export default function Page(){return <AdminShell title="audit"><Audit/></AdminShell>;}
