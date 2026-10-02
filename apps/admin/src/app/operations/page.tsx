'use client';
import {useState,type ReactNode} from 'react';
import {CheckCircle2,AlertCircle,Download,RefreshCw} from 'lucide-react';
import {api} from '@/lib/api';
import type {Operations} from '@/lib/admin-types';
import {useLocale,dateTime} from '@/lib/i18n';
import {operationsText,operationsDiagnostics,signalAdvice,summaryKeys,safeTimestamp,safeMetric,safeFailureCode,readinessKeys,countKeys,type OperationsLabel} from '@/lib/operations';
import {AdminShell} from '@/components/shell';
import {Badge,Button} from '@/components/ui';
import {DataState,useLoad} from '@/components/common';

function Metric({label,value}:{label:string;value:ReactNode}){return <div className="operational-row"><span>{label}</span><strong>{value}</strong></div>;}

function OperationsPage(){
  const {t,label,locale}=useLocale();
  const text=(key:OperationsLabel)=>operationsText(locale,key);
  const load=useLoad(()=>api<Operations>('/admin/operations'));
  const [exportError,setExportError]=useState(false);
  const [exportPrepared,setExportPrepared]=useState(false);
  const data=load.data;
  const number=(value:unknown)=>{const metric=safeMetric(value);return metric===null?'—':new Intl.NumberFormat(locale==='kk'?'kk-KZ':locale==='ru'?'ru-RU':'en-GB',{maximumFractionDigits:0}).format(metric);};
  const elapsed=(value:unknown)=>{const metric=safeMetric(value);return metric===null?'—':new Intl.NumberFormat(locale==='kk'?'kk-KZ':locale==='ru'?'ru-RU':'en-GB',{style:'unit',unit:'second',unitDisplay:'short',maximumFractionDigits:0}).format(metric);};
  const timestamp=(value:unknown)=>{const safe=safeTimestamp(value);return safe?`${dateTime(safe,locale,'UTC')} UTC`:'—';};
  function download(){
    if(!data||load.loading||load.error)return;
    setExportError(false);
    setExportPrepared(false);
    let url:string|undefined;
    let anchor:HTMLAnchorElement|undefined;
    try{
      const body=JSON.stringify(operationsDiagnostics(data),null,2);
      url=URL.createObjectURL(new Blob([body],{type:'application/json;charset=utf-8'}));
      anchor=document.createElement('a');anchor.href=url;anchor.download='danaconnect-operations.json';
      document.body.appendChild(anchor);anchor.click();
      setExportPrepared(true);
    }catch{setExportError(true);}
    finally{anchor?.remove();if(url){const downloadUrl=url;setTimeout(()=>URL.revokeObjectURL(downloadUrl),1000);}}
  }
  const delivery=data?.delivery;
  const worker=data?.worker;
  const signals=(data?.signals??[]).filter(signal=>Object.hasOwn(signalAdvice,signal.code)&&['warning','critical'].includes(signal.severity));
  return <div className="stack">
    <div className="row">
      <p className="muted">{t('systemNote')}</p>
      <div className="row">
        <Button variant="secondary" onClick={()=>{setExportError(false);setExportPrepared(false);void load.reload();}} disabled={load.loading} aria-busy={load.loading}><RefreshCw size={15} aria-hidden="true"/>{t(load.loading?'loading':'refresh')}</Button>
        <Button variant="secondary" onClick={download} disabled={!data||load.loading||Boolean(load.error)}><Download size={15} aria-hidden="true"/>{text('export')}</Button>
      </div>
    </div>
    {exportError&&<div className="error" role="alert">{text('exportError')}</div>}
    {exportPrepared&&<div className="success" role="status">{text('exportPrepared')}</div>}
    <DataState {...load} retry={load.reload}>{data&&<>
      <div className="notice">
        <div className="row"><span>{t('environment')}: <strong>{data.environment==='test'?text('testEnvironment'):['development','production'].includes(data.environment)?label(data.environment):text('unknown')}</strong></span><span>{text('snapshot')}: <strong>{timestamp(data.observed_at)}</strong></span></div>
        <p>{text('snapshotNote')}</p>{data.demo_mode&&<p>{t('demoWarning')}</p>}
      </div>

      <section className="panel stack" aria-labelledby="operations-signals">
        <h2 id="operations-signals">{text('signals')}</h2>
        <p>{text('signalNote')}</p>
        {signals.length?signals.map(signal=><div className={signal.severity==='critical'?'error':'notice'} key={signal.code}>
          <div className="row"><strong className="row"><AlertCircle size={18} aria-hidden="true"/>{text(signal.code)}</strong><Badge tone={signal.severity==='critical'?'danger':'warning'}>{text(signal.severity)}</Badge></div>
          <p>{text(signalAdvice[signal.code])}</p>
        </div>):<div className="row"><CheckCircle2 size={18} aria-hidden="true"/><span>{text('noSignals')}</span></div>}
      </section>

      <div className="profile-grid">
        <section className="panel"><h2>{t('operations')}</h2>{readinessKeys.map(key=><div className="operational-row" key={key}><span className="row">{data.readiness[key]?<CheckCircle2 color="#24795d" size={18} aria-hidden="true"/>:<AlertCircle color="#9a7920" size={18} aria-hidden="true"/>} {label(key)}</span><Badge tone={data.readiness[key]?'success':'warning'}>{t(data.readiness[key]?'systemReady':'systemMissing')}</Badge></div>)}</section>
        <section className="panel"><h2>{t('queue')}</h2>{countKeys.map(key=><Metric key={key} label={label(key)} value={number(data.counts[key])}/>)}</section>
      </div>

      {delivery&&<section className="panel stack" aria-labelledby="operations-delivery">
        <h2 id="operations-delivery">{text('delivery')}</h2>
        <div className="grid-4">{(['pending','leased','sent','failed'] as const).map(key=><div className="card" key={key}><div className="stat">{number(delivery.status_counts[key])}</div><div className="stat-label">{text(key)}</div></div>)}</div>
        <p className="notice">{text('deliveryNote')}</p>
        <div className="grid-2">
          <div>{(['due_pending','expired_pending','expired_leases','failures_last_24h'] as const).map(key=><Metric key={key} label={text(key)} value={number(delivery[key])}/>)}</div>
          <div><Metric label={text('oldest_pending_at')} value={timestamp(delivery.oldest_pending_at)}/><Metric label={text('oldest_due_at')} value={timestamp(delivery.oldest_due_at)}/><Metric label={text('oldest_due_age_seconds')} value={elapsed(delivery.oldest_due_age_seconds)}/></div>
        </div>
        <h3>{text('failureGroups')}</h3><p>{text('failureNote')}</p><p>{text('cancellationNote')}</p>
        {delivery.failure_codes.length?<div className="table-wrap"><table><caption className="field-hint">{text('failureGroups')}</caption><thead><tr><th scope="col">{text('failureCode')}</th><th scope="col">{text('count')}</th></tr></thead><tbody>{delivery.failure_codes.map((row,index)=><tr key={`${safeFailureCode(row.code)}-${index}`}><th scope="row">{text(safeFailureCode(row.code))}</th><td>{number(row.count)}</td></tr>)}</tbody></table></div>:<p>{text('noFailures')}</p>}
      </section>}

      {worker&&<section className="panel stack" aria-labelledby="operations-worker">
        <div className="row"><h2 id="operations-worker">{t('worker')}</h2><Badge tone={worker.status==='running'?'blue':worker.recent_success?'success':'warning'}>{worker.status==='running'?label('running'):t(worker.recent_success?'workerFresh':'workerStale')}</Badge></div>
        <p>{t('status')}: <strong>{worker.status==='failed'?text('workerFailedStatus'):['idle','running','success'].includes(worker.status)?label(worker.status):text('unknown')}</strong></p>
        <div className="grid-2">
          <div><Metric label={text('last_started_at')} value={timestamp(worker.last_started_at)}/><Metric label={text('last_finished_at')} value={timestamp(worker.last_finished_at)}/></div>
          <div>{(['age_seconds','duration_seconds','running_age_seconds'] as const).map(key=><Metric key={key} label={text(key)} value={elapsed(worker[key])}/>)}</div>
        </div>
        <p>{text('workerNote')}</p><h3>{text('summary')}</h3><p>{text('summaryNote')}</p>
        <div className="grid-3">{(['rules','reminders','email'] as const).map(group=>{
          const counters=worker.summary?.[group];
          const entries=summaryKeys[group].map(key=>({key,value:safeMetric((counters as Record<string,unknown>|undefined)?.[key])})).filter(entry=>entry.value!==null);
          return <div className="card" key={group}><h3>{text(group)}</h3>{group==='email'&&worker.summary?.email?.status==='unconfigured'&&<Badge tone="warning">{text('unconfigured')}</Badge>}{entries.length?entries.map(entry=><Metric key={entry.key} label={text(entry.key)} value={number(entry.value)}/>):<p>{text('noSummary')}</p>}</div>;
        })}</div>
      </section>}
      <p className="muted">{text('exportNote')}</p>
    </>}</DataState>
  </div>;
}
export default function Page(){return <AdminShell title="operations"><OperationsPage/></AdminShell>;}
