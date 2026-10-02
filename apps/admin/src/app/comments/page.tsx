'use client';
import {useState} from 'react';
import {mutate} from '@/lib/api';
import {useLocale,dateTime} from '@/lib/i18n';
import {AdminShell} from '@/components/shell';
import {Badge,Button,Field} from '@/components/ui';
import {ActionNotice,DataState,NoData,Pager,useAction,usePaged} from '@/components/common';
type Comment={id:string;project_id:string;author_name:string;body:string;scope:string;status:string;created_at:string};
function Review({comment,refresh}:{comment:Comment;refresh:()=>Promise<void>}){const {t}=useLocale();const [decision,setDecision]=useState('');const [reason,setReason]=useState('');const action=useAction();return <form className="form-grid" onSubmit={event=>{event.preventDefault();action.run(async()=>{await mutate(`/admin/comments/${comment.id}/review`,{decision,reason});await refresh();});}}><div className="full-width"><ActionNotice action={action}/></div><Field label={t('decision')}><select required value={decision} onChange={event=>setDecision(event.target.value)}><option value="">{t('choose')}</option><option value="visible">{t('visible')}</option><option value="hidden">{t('hidden')}</option></select></Field><Field label={t('reason')}><textarea required minLength={3} maxLength={2000} value={reason} onChange={event=>setReason(event.target.value)}/></Field><Button type="submit" disabled={action.busy}>{t('save')}</Button></form>;}
function Comments(){const {t,label,locale}=useLocale();const load=usePaged<Comment>('/admin/comments');return <DataState {...load} retry={load.reload}>{load.data?.length?<div className="stack">{load.data.map(comment=><article className="panel" key={comment.id}><div className="row"><strong>{comment.author_name}</strong><Badge>{label(comment.status)}</Badge><small>{dateTime(comment.created_at,locale)}</small></div><p className="muted word-break">{t('project')}: {comment.project_id}</p><p className="pre-line">{comment.body}</p><Review comment={comment} refresh={load.reload}/></article>)}</div>:<NoData/>}<Pager {...load} hasNext={load.data?.length===25}/></DataState>;}
export default function Page(){return <AdminShell title="comments" description="publicCommentsNote"><Comments/></AdminShell>;}
