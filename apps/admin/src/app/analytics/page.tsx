'use client';
import {api} from '@/lib/api';
import type {Analytics} from '@/lib/admin-types';
import {useLocale} from '@/lib/i18n';
import {AdminShell} from '@/components/shell';
import {AnalyticsCards} from '@/components/analytics';
import {Button} from '@/components/ui';
import {DataState,useLoad} from '@/components/common';
function AnalyticsPage(){const {t}=useLocale();const load=useLoad(()=>api<Analytics>('/admin/analytics'));return <div className="stack"><div className="row"><Button variant="secondary" onClick={load.reload}>{t('refresh')}</Button><a className="button button-secondary" href="/api/v1/admin/results/export">{t('exportCsv')}</a></div><DataState {...load} retry={load.reload}>{load.data&&<AnalyticsCards data={load.data}/>}</DataState></div>;}
export default function Page(){return <AdminShell title="analytics"><AnalyticsPage/></AdminShell>;}
