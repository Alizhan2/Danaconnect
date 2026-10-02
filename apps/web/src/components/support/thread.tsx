'use client';
import {useState,type FormEvent} from 'react';
import {api} from '@/lib/api';
import {useLocale} from '@/lib/i18n';
import {Badge,Button,EmptyState,Field} from '@/components/ui';
import {ActionNotice,dateTime,LoadState,mutate,useAction,useLoad} from '@/components/workflows/common';
import {supportText,reportStatus,type Report,type ReportMessage} from './copy';

export function SupportThread({report,timezone,canReply,refresh}:{report:Report;timezone:string;canReply:boolean;refresh:()=>Promise<void>}) {
  const {locale}=useLocale();
  const text=(key:Parameters<typeof supportText>[1])=>supportText(locale,key);
  const [page,setPage]=useState(0);
  const [body,setBody]=useState('');
  const action=useAction();
  const load=useLoad(()=>api<ReportMessage[]>(`/me/reports/${encodeURIComponent(report.id)}/messages?limit=50&offset=${page*50}`),[report.id,page]);
  async function send(event:FormEvent){event.preventDefault();await action.run(async()=>{await mutate(`/me/reports/${encodeURIComponent(report.id)}/messages`,{body:body.trim()});setBody('');if(page===0)await load.reload();else setPage(0);await refresh();},text('sent'));}
  return <section className="panel stack" aria-label={text('conversation')}>
    <div className="row"><h2>{text('conversation')}</h2><Badge tone={report.status==='resolved'?'success':'warning'}>{text(reportStatus(report.status))}</Badge><Button variant="secondary" onClick={load.reload}>{text('refresh')}</Button></div>
    <p className="muted">{text('private')}</p>
    <div className="panel"><strong>{text('original')}</strong><p className="pre-line" style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{report.reason}</p><small className="muted">{dateTime(report.created_at,timezone,locale)}</small></div>
    <LoadState {...load} retry={load.reload}>
      {load.data?.length ? <div className="stack">{load.data.map(message=><article className="panel" key={message.id}><div className="row"><strong>{text(message.is_mine?'you':message.sender_role==='support'?'staff':'participant')}</strong><small className="muted">{dateTime(message.created_at,timezone,locale)}</small></div><p style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{message.body}</p></article>)}</div>:<EmptyState title={text('noReplies')}/>}
    </LoadState>
    <nav className="actions" aria-label={text('conversation')}><Button variant="secondary" disabled={load.loading||load.data?.length!==50} onClick={()=>setPage(page+1)}>{text('older')}</Button><span>{text(page===0?'latest':'page')} {page>0?page+1:''}</span><Button variant="secondary" disabled={load.loading||page===0} onClick={()=>setPage(page-1)}>{text('newer')}</Button></nav>
    {canReply && <form className="stack" onSubmit={send}>
      {['resolved','dismissed'].includes(report.status)&&<p className="notice">{text('reopen')}</p>}
      <ActionNotice action={action}/>
      <Field label={text('reply')} hint={text('replyHint')}><textarea required minLength={5} maxLength={3000} value={body} onChange={event=>setBody(event.target.value)} rows={4}/></Field>
      <div className="actions"><Button type="submit" disabled={action.busy||body.trim().length<5}>{text('send')}</Button></div>
    </form>}
  </section>;
}
