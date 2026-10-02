'use client';
import {api} from '@/lib/api';
import type {Analytics,SupportReport} from '@/lib/admin-types';
import type {User,Project} from '@/lib/types';
import {useLocale} from '@/lib/i18n';
import {AdminShell} from '@/components/shell';
import {AnalyticsCards} from '@/components/analytics';
import {Button,Badge} from '@/components/ui';
import {DataState,useLoad} from '@/components/common';
function Overview(){const {t}=useLocale();const load=useLoad(async()=>{const [analytics,registrations,projects,reports]=await Promise.all([api<Analytics>('/admin/analytics'),api<User[]>('/admin/registrations?limit=5'),api<Project[]>('/admin/projects?status=pending&limit=5'),api<SupportReport[]>('/admin/reports?limit=5')]);return {analytics,registrations,projects,reports};});return <DataState {...load} retry={load.reload}>{load.data&&<div className="stack"><AnalyticsCards data={load.data.analytics} compact/><div className="grid-3">{[[t('registrations'),load.data.registrations,'/registrations'],[t('projects'),load.data.projects,'/projects'],[t('reports'),load.data.reports.filter(r=>r.status==='open'||r.status==='reviewing'),'/reports']].map(([label,records,href])=><section className="panel" key={String(href)}><div className="panel-header"><h2>{label as string}</h2><Badge tone="blue">{(records as unknown[]).length}{(records as unknown[]).length===5?'+':''}</Badge></div><p>{t('queueNote')}</p><Button href={href as string} variant="secondary">{t('details')}</Button></section>)}</div><div className="panel"><div className="row"><div><h2>{t('operations')}</h2><p>{t('systemNote')}</p></div><Button href="/operations">{t('details')}</Button></div></div></div>}</DataState>;}
export default function Page(){return <AdminShell title="overview" description="platformAtAGlance"><Overview/></AdminShell>;}
