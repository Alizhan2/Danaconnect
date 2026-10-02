"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import type { User } from "@/lib/types";
import { useLocale } from "@/lib/i18n";
import { Button, EmptyState, Field } from "@/components/ui";
import { ActionNotice, LoadState, mutate, useAction, useLoad } from "@/components/workflows/common";

type Membership = {project_id:string;title:string;member_role:string;can_leave:boolean};
const copy = {
  ru:{title:"Мои команды", empty:"Участий в командах пока нет", leave:"Выйти из команды", reason:"Причина выхода", confirm:"Подтвердить выход", cancel:"Отмена", warning:"После выхода вы потеряете доступ к закрытым материалам этой команды. История работы сохранится.", done:"Вы вышли из команды", prev:"Назад", next:"Далее", protected:"Чтобы завершить менторство, оформите результат в рабочем пространстве. Автор и назначенный ментор выходят через отдельное согласование."},
  kk:{title:"Менің командаларым", empty:"Әзірге командаларға қатысу жоқ", leave:"Командадан шығу", reason:"Шығу себебі", confirm:"Шығуды растау", cancel:"Бас тарту", warning:"Шыққаннан кейін осы команданың жабық материалдарына қолжетімділікті жоғалтасыз. Жұмыс тарихы сақталады.", done:"Сіз командадан шықтыңыз", prev:"Артқа", next:"Әрі қарай", protected:"Менторлықты аяқтау үшін жұмыс кеңістігінде нәтижені рәсімдеңіз. Автор мен тағайындалған ментор бөлек келісім арқылы шығады."},
  en:{title:"My teams", empty:"No team memberships yet", leave:"Leave team", reason:"Reason for leaving", confirm:"Confirm departure", cancel:"Cancel", warning:"After leaving, you will lose access to this team's private materials. Your work history will remain.", done:"You left the team", prev:"Previous", next:"Next", protected:"To finish mentoring, record an outcome in your workspace. Authors and assigned mentors require separate coordination."},
};

export function TeamMemberships({user}:{user:User}) {
  const {locale}=useLocale(); const t=copy[locale]; const action=useAction();
  const [offset,setOffset]=useState(0),[selected,setSelected]=useState<string|null>(null),[reason,setReason]=useState("");
  const load=useLoad(()=>api<Membership[]>(`/me/team-memberships?limit=25&offset=${offset}`),[offset]);
  return <section className="panel stack"><h2>{t.title}</h2><ActionNotice action={action}/><LoadState {...load} retry={load.reload}>
    {!load.data?.length?<EmptyState title={t.empty}/>:load.data.map(row=><article className="card stack" key={row.project_id}><h3>{row.title}</h3>
      {row.can_leave?(selected===row.project_id?<form className="stack" onSubmit={event=>{event.preventDefault();void action.run(async()=>{await mutate(`/projects/${row.project_id}/team/${user.id}/remove`,{reason});setSelected(null);setReason("");await load.reload();},t.done);}}><p>{t.warning}</p><Field label={t.reason}><textarea required minLength={3} maxLength={2000} value={reason} onChange={event=>setReason(event.target.value)}/></Field><div className="actions"><Button type="submit" disabled={action.busy}>{t.confirm}</Button><Button type="button" variant="secondary" disabled={action.busy} onClick={()=>{setSelected(null);setReason("");}}>{t.cancel}</Button></div></form>:<Button variant="secondary" onClick={()=>{setSelected(row.project_id);setReason("");}}>{t.leave}</Button>):<p className="muted">{t.protected}</p>}
    </article>)}<div className="actions"><Button variant="secondary" disabled={offset===0||load.loading||action.busy} onClick={()=>{setOffset(Math.max(0,offset-25));setSelected(null);setReason("");}}>{t.prev}</Button><Button variant="secondary" disabled={load.data?.length!==25||load.loading||action.busy} onClick={()=>{setOffset(offset+25);setSelected(null);setReason("");}}>{t.next}</Button></div>
  </LoadState></section>;
}
