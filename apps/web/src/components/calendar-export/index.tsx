"use client";
import { useState } from "react";
import type { User } from "@/lib/types";
import { useLocale } from "@/lib/i18n";
import { ApiError } from "@/lib/api";
import { Button, Field } from "@/components/ui";
import { ActionNotice, useAction } from "@/components/workflows/common";

const copy = {
  ru: {title:"Перенести встречи в календарь", description:"Скачайте файл и импортируйте его в Google Calendar, Outlook или календарь телефона. В нём будут только ваши встречи за выбранный период.", period:"Период впереди", days:"дней", cancelled:"Включить отменённые встречи", download:"Скачать календарь", hint:"Это копия расписания. Изменения и отмены на платформе не обновляют импортированный календарь автоматически. Проверяйте актуальные встречи здесь.", done:"Файл календаря сохранён", failed:"Не удалось скачать календарь"},
  kk: {title:"Кездесулерді күнтізбеге көшіру", description:"Файлды жүктеп, Google Calendar, Outlook немесе телефон күнтізбесіне импорттаңыз. Онда таңдалған кезеңдегі тек өз кездесулеріңіз болады.", period:"Алдағы кезең", days:"күн", cancelled:"Болдырылмаған кездесулерді қосу", download:"Күнтізбені жүктеу", hint:"Бұл кестенің көшірмесі. Платформадағы өзгерістер мен болдырмаулар импортталған күнтізбені автоматты жаңартпайды. Өзекті кездесулерді осы жерден қараңыз.", done:"Күнтізбе файлы сақталды", failed:"Күнтізбені жүктеу мүмкін болмады"},
  en: {title:"Move meetings to your calendar", description:"Download a file and import it into Google Calendar, Outlook or your phone calendar. It contains only your meetings during the selected period.", period:"Period ahead", days:"days", cancelled:"Include cancelled meetings", download:"Download calendar", hint:"This is a copy of your schedule. Changes and cancellations on the platform do not automatically update the imported calendar. Check current meetings here.", done:"Calendar file saved", failed:"Could not download your calendar"},
};

export function CalendarExport({ user }: {user:User}) {
  const { locale } = useLocale();
  const t = copy[locale];
  const action = useAction();
  const [days, setDays] = useState(90);
  const [cancelled, setCancelled] = useState(false);
  async function download() {
    await action.run(async () => {
      const start = new Date();
      const end = new Date(start.getTime() + days * 86400000);
      const params = new URLSearchParams({starts_after:start.toISOString(), ends_before:end.toISOString(), include_cancelled:String(cancelled)});
      let response:Response;
      try { response = await fetch(`/api/v1/me/calendar.ics?${params}`, {credentials:"include",cache:"no-store", headers:{"Accept-Language":locale}, signal:AbortSignal.timeout(20000)}); }
      catch { throw new Error(t.failed); }
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new ApiError(response.status, typeof body?.detail === "string" ? body.detail : t.failed);
      }
      if (!response.headers.get("Content-Type")?.startsWith("text/calendar")) throw new Error(t.failed);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url; anchor.download = "danaconnect-calendar.ics";
      document.body.appendChild(anchor); anchor.click(); anchor.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }, t.done);
  }
  if (!["mentee","mentor"].includes(user.role)) return null;
  return <section className="panel stack"><h2>{t.title}</h2><p className="muted">{t.description}</p><ActionNotice action={action}/>
    <div className="form-grid"><Field label={t.period}><select value={days} onChange={event => setDays(Number(event.target.value))}>{[30,90,180,365].map(value => <option value={value} key={value}>{value} {t.days}</option>)}</select></Field>
    <label className="checkbox-row"><input type="checkbox" checked={cancelled} onChange={event => setCancelled(event.target.checked)}/>{t.cancelled}</label></div>
    <p className="muted">{t.hint}</p><Button disabled={action.busy} onClick={() => void download()}>{t.download}</Button></section>;
}
