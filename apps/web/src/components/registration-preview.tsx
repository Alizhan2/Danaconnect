"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { emptyRegistration, type ParticipantRole, type RegistrationDraft } from "@/lib/registration";
import type { Direction } from "@/lib/types";
import { AppShell } from "./shell";
import { Button } from "./ui";
import { RegistrationFields } from "./registration-fields";
import { LoadState, useLoad } from "./workflows/common";

/** Read-only review path: editable examples stay in memory and are never submitted. */
export function RegistrationPreview({ role }: { role: ParticipantRole }) {
  const { locale, tr } = useLocale();
  const load = useLoad(() => api<Direction[]>("/directions"), [locale]);
  const [draft, setDraft] = useState<RegistrationDraft>(() => emptyRegistration(role));
  const title = tr(role === "mentor" ? "Анкета ментора" : "Анкета менти");
  return <AppShell title={title} description={tr("Посмотрите поля анкеты перед регистрацией.")}>
    <div className="container section stack narrow registration-page" style={{ paddingTop: 0 }}>
      <div className="notice" role="status"><strong>{tr("Предпросмотр анкеты")}</strong><p>{tr("Это просмотр полей. Введённые здесь данные не отправляются и не сохраняются. После подтверждения email анкету нужно заполнить заново.")}</p></div>
      <div className="actions"><Button href={`/login?role=${role}`}>{tr("Начать регистрацию по email")}</Button><Button href="/register" variant="secondary">{tr("Выбрать другую роль")}</Button></div>
      <section className="panel stack">
        <h2>{tr("Поля вашей анкеты")}</h2>
        <p className="field-hint">{tr("Обязательные поля отмечены в форме. Документы подтверждаются отдельным шагом после входа.")}</p>
        {(load.error || load.loading) && <LoadState {...load} loading={load.loading && !load.data} retry={load.reload}>{null}</LoadState>}
        <form className="form-grid" onSubmit={event => event.preventDefault()}>
          <RegistrationFields draft={draft} directions={load.data || []} preview loading={load.loading} reloadDirections={load.reload} update={(name, value) => setDraft(current => ({ ...current, [name]: value }))} />
        </form>
      </section>
      <section className="panel stack"><h2>{tr("Документы и согласия")}</h2><p>{tr("После подтверждения email и сохранения роли платформа покажет актуальные документы для ваших направлений. Каждый документ нужно прочитать и подтвердить самостоятельно.")}</p><p className="notice">{tr("Если обязательные документы ещё не опубликованы, анкету можно сохранить, но отправить на проверку пока нельзя.")}</p></section>
      <section className="panel"><h2>{tr("Как проходит регистрация")}</h2><ol><li>{tr("Подтвердите email одноразовым кодом.")}</li><li>{tr("Заполните анкету своей роли.")}</li><li>{tr("Прочитайте опубликованные документы и подтвердите согласия.")}</li><li>{tr("Отправьте анкету на проверку команды.")}</li></ol><div className="actions"><Button href={`/login?role=${role}`}>{tr("Начать регистрацию по email")}</Button><Button href="/login" variant="secondary">{tr("Уже есть аккаунт — войти")}</Button></div></section>
    </div>
  </AppShell>;
}
