"use client";

import { useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import type { Application, Project, User } from "@/lib/types";
import { useLocale } from "@/lib/i18n";
import { Badge, Button, EmptyState, Field } from "@/components/ui";
import { ActionNotice, LoadState, mutate, statusText, useAction, useLoad } from "./common";

/** Offers reuse the application inbox: the idea author decides, the mentor initiates. */
export function MentorOffers({ project, user, onChanged }: {
  project: Project;
  user: User;
  onChanged: () => Promise<void>;
}) {
  const { tr } = useLocale();
  const action = useAction();
  const [motivation, setMotivation] = useState("");
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const load = useLoad(() => api<Application[]>(`/applications?project_id=${encodeURIComponent(project.id)}`), [project.id, user.id]);
  const isOwner = user.id === project.owner_id;
  const applications = load.data?.filter((item) => item.project_id === project.id) || [];
  const offers = applications.filter((item) => item.initiator_role === "mentor");
  const existing = applications.find((item) => item.mentor_id === user.id && ["pending", "accepted"].includes(item.status));
  const canOffer = user.role === "mentor" && user.account_status === "active" && user.intake_open && !isOwner &&
    project.visibility_status === "published" && !project.mentor_id && !existing;

  async function refresh() {
    await load.reload();
    await onChanged();
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    await action.run(async () => {
      await mutate(`/projects/${project.id}/mentor-offers`, { motivation: motivation.trim() });
      setMotivation("");
      await refresh();
    }, tr("Предложение отправлено автору идеи"));
  }
  return (
    <section className="panel stack">
      <h2>{tr("Поддержка идеи ментором")}</h2>
      <p>{tr(isOwner
        ? "Рассмотрите предложения и выберите ментора. После принятия появятся участие и общий диалог."
        : "Расскажите, как вы можете помочь. Автор идеи самостоятельно принимает или отклоняет предложение.")}</p>
      <ActionNotice action={action} />
      <LoadState {...load} retry={load.reload}>
        {project.mentor_id && <p className="notice">{tr("Для этой идеи уже выбран ментор.")} {project.mentor_name || ""}</p>}
        {!offers.length && <EmptyState title={tr("Предложений менторов пока нет")} />}
        {offers.map((offer) => (
          <article className="card stack" key={offer.id}>
            <div className="row"><h3>{offer.mentor_name || tr("Ментор")}</h3><Badge>{tr(statusText(offer.status))}</Badge></div>
            <Button href={`/catalog/${offer.mentor_id}`} variant="ghost">{tr("Посмотреть профиль ментора")}</Button>
            <p className="pre-line">{offer.motivation}</p>
            {offer.rejection_reason && <p>{tr("Причина:")} {tr(statusText(offer.rejection_reason))}</p>}
            {offer.status === "pending" && user.account_status === "active" && (
              offer.decision_user_id === user.id ? <>
                <Field label={tr("Причина отклонения")}>
                  <select value={reasons[offer.id] || ""} onChange={(event) => setReasons({ ...reasons, [offer.id]: event.target.value })}>
                    <option value="">{tr("Выберите причину для отказа")}</option>
                    <option value="not_a_fit">{tr("Запрос не подходит")}</option>
                    <option value="direction_mismatch">{tr("Не совпадает направление")}</option>
                    <option value="insufficient_information">{tr("Недостаточно информации")}</option>
                    <option value="project_closed">{tr("Проект закрыт")}</option>
                  </select>
                </Field>
                <div className="actions">
                  <Button disabled={action.busy || !!project.mentor_id} onClick={() => action.run(async () => {
                    await mutate(`/applications/${offer.id}/decision`, { decision: "accepted" });
                    await refresh();
                  }, tr("Ментор выбран. Участие и диалог созданы."))}>{tr("Принять поддержку")}</Button>
                  <Button variant="secondary" disabled={action.busy || !reasons[offer.id]} onClick={() => action.run(async () => {
                    await mutate(`/applications/${offer.id}/decision`, { decision: "rejected", reason: reasons[offer.id] });
                    await refresh();
                  }, tr("Предложение отклонено"))}>{tr("Отклонить")}</Button>
                </div>
              </> : offer.initiator_id === user.id && <Button variant="secondary" disabled={action.busy} onClick={() => action.run(async () => {
                await mutate(`/applications/${offer.id}/withdraw`);
                await refresh();
              }, tr("Предложение отозвано"))}>{tr("Отозвать предложение")}</Button>
            )}
            {offer.status === "accepted" && <div className="actions"><Button href="/dashboard">{tr("Открыть участие")}</Button><Button href="/messages" variant="secondary">{tr("Открыть диалог")}</Button></div>}
          </article>
        ))}
        {canOffer && <form className="form-stack" onSubmit={submit}>
          <Field label={tr("Как вы поможете автору идеи")}>
            <textarea required minLength={10} maxLength={5000} value={motivation} onChange={(event) => setMotivation(event.target.value)} />
          </Field>
          <Button type="submit" disabled={action.busy || motivation.trim().length < 10}>{tr("Предложить поддержку")}</Button>
        </form>}
        {existing?.status === "pending" && (existing.initiator_role === "mentor"
          ? <p className="notice">{tr("Автор идеи рассматривает ваше предложение.")}</p>
          : <div className="notice">{tr("По этой идее у вас уже есть заявка менти. Рассмотрите её в кабинете.")} <Button href="/dashboard" variant="secondary">{tr("Открыть кабинет")}</Button></div>)}
        {user.role === "mentor" && user.account_status === "active" && !user.intake_open && !isOwner &&
          project.visibility_status === "published" && !project.mentor_id && !existing &&
          <div className="notice">{tr("Чтобы предлагать поддержку, откройте набор в кабинете.")} <Button href="/dashboard" variant="secondary">{tr("Открыть кабинет")}</Button></div>}
      </LoadState>
    </section>
  );
}
