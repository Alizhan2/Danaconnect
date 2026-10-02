'use client';
import {useState,type FormEvent} from 'react';
import {api,mutate} from '@/lib/api';
import {useLocale,dateTime} from '@/lib/i18n';
import {Badge,Button,EmptyState,Field} from '@/components/ui';
import {ActionNotice,DataState,useAction,useLoad} from '@/components/common';
import {supportText,reportStatus,type Report,type ReportMessage,type SupportPhrase} from './copy';

export function ReportConversation({report,refresh}:{report:Report;refresh:()=>Promise<void>}) {
  const {locale}=useLocale();
  const text=(key:SupportPhrase)=>supportText(locale,key);
  const [page,setPage]=useState(0);
  const [body,setBody]=useState('');
  const action=useAction();
  const load=useLoad(()=>api<ReportMessage[]>(`/admin/reports/${encodeURIComponent(report.id)}/messages?limit=50&offset=${page*50}`),[report.id,page]);
  async function send(event:FormEvent){event.preventDefault();await action.run(async()=>{await mutate(`/admin/reports/${encodeURIComponent(report.id)}/messages`,{body:body.trim()});setBody('');if(page===0)await load.reload();else setPage(0);await refresh();});}
  return <section className="panel stack" aria-label={text('conversation')}>
    <div className="row"><h2>{text('conversation')}</h2><Badge tone={report.status==='resolved'?'success':'warning'}>{text(reportStatus(report.status))}</Badge><Button variant="secondary" onClick={load.reload}>{text('refresh')}</Button></div>
    <p className="muted">{text('private')}</p>
    <div className="panel"><strong>{text('original')}</strong><p style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{report.reason}</p><small>{dateTime(report.created_at,locale)}</small></div>
    <DataState {...load} retry={load.reload}>
      {load.data?.length ? <div className="stack">{load.data.map(message=><article className="panel" key={message.id}><div className="row"><strong>{text(message.is_mine?'you':message.sender_role==='support'?'staff':'participant')}</strong><small className="muted">{dateTime(message.created_at,locale)}</small></div><p style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{message.body}</p></article>)}</div>:<EmptyState title={text('noReplies')}/>}
    </DataState>
    <nav className="actions" aria-label={text('conversation')}><Button variant="secondary" disabled={load.loading||load.data?.length!==50} onClick={()=>setPage(page+1)}>{text('older')}</Button><span>{text(page===0?'latest':'page')} {page>0?page+1:''}</span><Button variant="secondary" disabled={load.loading||page===0} onClick={()=>setPage(page-1)}>{text('newer')}</Button></nav>
    <form className="stack" onSubmit={send}><ActionNotice action={action}/><Field label={text('reply')} hint={text('replyHint')}><textarea required minLength={5} maxLength={3000} rows={4} value={body} onChange={event=>setBody(event.target.value)}/></Field><div className="actions"><Button type="submit" disabled={action.busy||body.trim().length<5}>{text('send')}</Button></div></form>
  </section>;
}
