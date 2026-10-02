'use client';
import {useState,type FormEvent} from 'react';
import {api} from '@/lib/api';
import type {User} from '@/lib/types';
import {useLocale} from '@/lib/i18n';
import {AppShell} from '@/components/shell';
import {Badge,Button,EmptyState,Field} from '@/components/ui';
import {ActionNotice,dateTime,LoadState,mutate,useAction,useLoad} from '@/components/workflows/common';
import {supportText,reportStatus,type Report,type SupportPhrase} from './copy';
import {SupportThread} from './thread';

function Workspace({user,contextType,contextEntity}:{user:User;contextType:string;contextEntity:string}) {
  const {locale}=useLocale();
  const text=(key:SupportPhrase)=>supportText(locale,key);
  const contextValid=['project','mentor','message','booking'].includes(contextType)&&contextEntity.trim().length>0&&contextEntity.length<=36;
  const [kind,setKind]=useState(contextValid?contextType:'support');
  const [reason,setReason]=useState('');
  const [status,setStatus]=useState('');
  const [page,setPage]=useState(0);
  const [selected,setSelected]=useState('');
  const action=useAction();
  const load=useLoad(()=>api<Report[]>(`/me/reports?limit=25&offset=${page*25}${status?`&status=${status}`:''}`),[page,status]);
  const report=load.data?.find(row=>row.id===selected);
  const canReply=user.account_status!=='suspended';
  async function create(event:FormEvent){event.preventDefault();await action.run(async()=>{
    const response=await mutate<{id:string;status:string}>('/reports',{entity_type:kind,...(kind!=='support'?{entity_id:contextEntity.trim()}:{}),reason:reason.trim()});
    setReason('');setSelected(response.id);setPage(0);setStatus('');
    if(page===0&&!status)await load.reload();
  },text('created'));}
  return <div className="stack">
    <p className="muted">{text('private')}</p>
    {!canReply&&<p className="notice">{text('suspended')}</p>}
    {canReply&&<form className="panel stack" onSubmit={create}>
      <h2>{text('create')}</h2><ActionNotice action={action}/>
      {(contextType||contextEntity)&&!contextValid&&<p className="notice">{text('invalidContext')}</p>}
      <Field label={text('subject')}><select value={kind} onChange={event=>setKind(event.target.value)}><option value="support">{text('support')}</option>{contextValid&&<option value={contextType}>{text(contextType as SupportPhrase)}</option>}</select></Field>
      {kind!=='support'&&<p className="muted">{text('context')}</p>}
      <Field label={text('reason')} hint={text('reasonHint')}><textarea required minLength={10} maxLength={3000} rows={5} value={reason} onChange={event=>setReason(event.target.value)}/></Field>
      <div className="actions"><Button type="submit" disabled={action.busy||reason.trim().length<10}>{text('submit')}</Button></div>
    </form>}
    <section className="panel stack">
      <div className="row"><h2>{text('mine')}</h2><Button variant="secondary" onClick={load.reload}>{text('refresh')}</Button></div>
      <Field label={text('all')}><select value={status} onChange={event=>{setStatus(event.target.value);setPage(0);setSelected('');}}><option value="">{text('all')}</option>{['pending','reviewing','resolved','dismissed'].map(value=><option key={value} value={value}>{text(reportStatus(value))}</option>)}</select></Field>
      <LoadState {...load} retry={load.reload}>
        {load.data?.length ? <div className="stack">{load.data.map(row=><article className="panel" key={row.id}>
          <div className="row"><strong>{text(['project','mentor','message','booking'].includes(row.entity_type)?row.entity_type as SupportPhrase:'support')}</strong><Badge tone={row.status==='resolved'?'success':'warning'}>{text(reportStatus(row.status))}</Badge></div>
          <p style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{row.reason}</p><p className="muted">{dateTime(row.created_at,user.timezone||'Asia/Oral',locale)}</p>
          <Button variant={selected===row.id?'primary':'secondary'} onClick={()=>setSelected(selected===row.id?'':row.id)}>{text(selected===row.id?'close':'view')}</Button>
        </article>)}</div>:<EmptyState title={text(status?'filteredEmpty':'empty')}/>}
      </LoadState>
      <nav className="actions" aria-label={text('mine')}><Button variant="secondary" disabled={page===0||load.loading} onClick={()=>{setPage(page-1);setSelected('');}}>{text('previous')}</Button><span>{text('page')} {page+1}</span><Button variant="secondary" disabled={load.loading||load.data?.length!==25} onClick={()=>{setPage(page+1);setSelected('');}}>{text('next')}</Button></nav>
    </section>
    {report&&<SupportThread key={report.id} report={report} timezone={user.timezone||'Asia/Oral'} canReply={canReply} refresh={load.reload}/>}
  </div>;
}

export function SupportPage({contextType='',contextEntity=''}:{contextType?:string;contextEntity?:string}) {
  const {locale}=useLocale();
  const load=useLoad(()=>api<User>('/auth/me'));
  return <AppShell dashboard title={supportText(locale,'title')} description={supportText(locale,'description')}><LoadState {...load} retry={load.reload}>{load.data&&<Workspace user={load.data} contextType={contextType} contextEntity={contextEntity}/>}</LoadState></AppShell>;
}
