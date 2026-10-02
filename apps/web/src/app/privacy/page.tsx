'use client';
import { useState, type FormEvent } from 'react';
import { api } from '@/lib/api';
import { useLocale } from '@/lib/i18n';
import { AppShell } from '@/components/shell';
import { Badge, Button, EmptyState, Field } from '@/components/ui';
import { ActionNotice, dateTime, LoadState, mutate, useAction, useLoad } from '@/components/workflows/common';

type PrivacyRequest = {id:string;kind:'export'|'deactivate'|'erase';status:string;reason:string;review_reason:string;created_at:string};
const copy = {
  ru: {title:'Ваши данные',description:'Скачайте сведения своего аккаунта или отправьте запрос команде платформы.',export:'Скачать мои данные',exportHint:'Файл содержит ваши личные сведения. Храните его в безопасном месте.',request:'Отправить запрос',kind:'Что нужно сделать',reason:'Пояснение, если нужно',exportKind:'Получить копию данных',deactivateKind:'Деактивировать аккаунт',eraseKind:'Удалить личные данные',eraseHint:'Запрос рассмотрит команда. Удаление учитывает обязательные сроки хранения и не выполняется сразу после отправки формы.',sent:'Запрос отправлен',downloaded:'Копия данных сохранена',history:'Мои запросы',empty:'Запросов пока нет',pending:'На рассмотрении',reviewing:'В работе',fulfilled:'Выполнен',rejected:'Отклонён'},
  kk: {title:'Сіздің деректеріңіз',description:'Тіркелгі мәліметтерін жүктеп алыңыз немесе платформа тобына сұрау жіберіңіз.',export:'Деректерімді жүктеп алу',exportHint:'Файлда жеке мәліметтеріңіз бар. Оны қауіпсіз жерде сақтаңыз.',request:'Сұрау жіберу',kind:'Не істеу керек',reason:'Қажет болса, түсіндірме',exportKind:'Деректер көшірмесін алу',deactivateKind:'Тіркелгіні өшіру',eraseKind:'Жеке деректерді жою',eraseHint:'Сұрауды топ қарайды. Жою міндетті сақтау мерзімдерін ескереді және нысанды жібергеннен кейін бірден орындалмайды.',sent:'Сұрау жіберілді',downloaded:'Деректер көшірмесі сақталды',history:'Менің сұрауларым',empty:'Әзірге сұраулар жоқ',pending:'Қаралуда',reviewing:'Орындалуда',fulfilled:'Орындалды',rejected:'Қабылданбады'},
  en: {title:'Your data',description:'Download your account information or send a request to the platform team.',export:'Download my data',exportHint:'The file contains your personal information. Store it securely.',request:'Send a request',kind:'What would you like to do?',reason:'Explanation, if needed',exportKind:'Request a copy of my data',deactivateKind:'Deactivate my account',eraseKind:'Erase my personal data',eraseHint:'The team will review your request. Erasure takes required retention periods into account and does not happen immediately after submitting this form.',sent:'Request sent',downloaded:'Data copy saved',history:'My requests',empty:'No requests yet',pending:'Pending review',reviewing:'In progress',fulfilled:'Fulfilled',rejected:'Rejected'}
};
export default function PrivacyPage(){
  const {locale}=useLocale(); const t=copy[locale]; const action=useAction();
  const requests=useLoad(()=>api<PrivacyRequest[]>('/me/privacy-requests'),[]);
  const [kind,setKind]=useState<PrivacyRequest['kind']>('export'); const [reason,setReason]=useState('');
  const kindLabel=(value:string)=>value==='export'?t.exportKind:value==='deactivate'?t.deactivateKind:t.eraseKind;
  const stateLabel=(value:string)=>({pending:t.pending,reviewing:t.reviewing,fulfilled:t.fulfilled,rejected:t.rejected}[value]||value);
  function submit(event:FormEvent){event.preventDefault();void action.run(async()=>{await mutate('/me/privacy-requests',{kind,reason});setReason('');await requests.reload();},t.sent);}
  async function download(){await action.run(async()=>{
    const payload=await api<Record<string,unknown>>('/me/data-export');
    const url=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}));
    const anchor=document.createElement('a');anchor.href=url;anchor.download='danaconnect-my-data.json';document.body.appendChild(anchor);anchor.click();anchor.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  },t.downloaded);}
  return <AppShell dashboard title={t.title} description={t.description}><LoadState loading={requests.loading} error={requests.error} retry={requests.reload}>
    <ActionNotice action={action}/><div className="grid-2"><section className="card"><h2>{t.export}</h2><p className="muted">{t.exportHint}</p><Button disabled={action.busy} onClick={()=>void download()}>{t.export}</Button></section>
    <form className="card" onSubmit={submit}><h2>{t.request}</h2><Field label={t.kind}><select value={kind} onChange={e=>setKind(e.target.value as PrivacyRequest['kind'])}><option value="export">{t.exportKind}</option><option value="deactivate">{t.deactivateKind}</option><option value="erase">{t.eraseKind}</option></select></Field><Field label={t.reason}><textarea value={reason} onChange={e=>setReason(e.target.value)} maxLength={2000}/></Field>{kind==='erase'&&<p className="muted">{t.eraseHint}</p>}<Button type="submit" disabled={action.busy}>{t.request}</Button></form></div>
    <section className="section"><h2>{t.history}</h2>{!requests.data?.length?<EmptyState title={t.empty}/>:<div className="card-stack">{requests.data.map(row=><article className="card" key={row.id}><div className="row"><h3>{kindLabel(row.kind)}</h3><Badge>{stateLabel(row.status)}</Badge></div><p className="muted">{dateTime(row.created_at,'Asia/Oral',locale)}</p>{row.reason&&<p>{row.reason}</p>}{row.review_reason&&<p>{row.review_reason}</p>}</article>)}</div>}</section>
  </LoadState></AppShell>;
}
