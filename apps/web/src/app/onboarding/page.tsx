"use client";
import { useEffect, useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import type { User, Direction, DocumentVersion } from "@/lib/types";
import { AppShell } from "@/components/shell";
import { Badge, Button, Field } from "@/components/ui";
import { useLocale, translatePhrase as tr } from "@/lib/i18n";
import { usePlatformStatus } from "@/components/platform-status";
import { RegistrationFields } from "@/components/registration-fields";
import { profilePendingChanges, registrationProblem, registrationValues, requestedRole } from "@/lib/registration";
import {
  ActionNotice,
  LoadState,
  mutate,
  statusText,
  safeReturnTo,
  useAction,
  useLoad,
} from "@/components/workflows/common";

type RegistrationRequirements = {
  documents_configured: boolean;
  required_version_ids: string[];
  unaccepted_version_ids: string[];
};

export default function OnboardingPage() {
  const { t, locale, tr } = useLocale();
  const { health } = usePlatformStatus();
  const action = useAction();
  const load = useLoad(async () => {
    const [user, directions, documents, notifications, requirements] = await Promise.all([
      api<User>("/auth/me"),
      api<Direction[]>("/directions"),
      api<DocumentVersion[]>("/documents"),
      api<{ id: string; title: string; body: string }[]>("/notifications"),
      api<RegistrationRequirements>("/me/registration-requirements"),
    ]);
    return { user, directions, documents, notifications, requirements };
  }, [locale]);
  const [draft, setDraft] = useState<User>();
  const [checked, setChecked] = useState<string[]>([]);
  useEffect(() => {
    if (load.data) {
      const user = load.data.user;
      setDraft((current) =>
        current && current.id === user.id && (user.role === "unchosen" || current.role === user.role)
          ? {
              ...current,
              account_status: user.account_status,
              profile_completed: user.profile_completed,
              mentor_commitment_accepted_at: user.mentor_commitment_accepted_at,
            }
          : { ...user, role: requestedRole(user.role, typeof window === "undefined" ? null : new URLSearchParams(window.location.search).get("role")) },
      );
      setChecked([]);
    }
  }, [load.data]);
  function update(name: keyof User, value: unknown) {
    setDraft((current) => (current ? { ...current, [name]: value } : current));
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!draft) return;
    await action.run(async () => {
      const availableDirections = load.data?.directions ?? [];
      if (draft.role !== "admin") {
        const problem = registrationProblem(draft, availableDirections);
        if (problem) throw new Error(problem);
      }
      const values = registrationValues(draft);
      const saved = await mutate<User>(
        "/me/profile",
        {
          preferred_locale: locale,
          ...values,
          ...(draft.role === "admin" ? { role: undefined } : {}),
        },
        "PUT",
      );
      setDraft(saved);
      window.dispatchEvent(new Event("danaconnect:profile-updated"));
      await load.reload();
    }, tr("Профиль сохранён. Проверьте актуальные документы ниже."));
  }
  async function submitDocuments() {
    await action.run(async () => {
      if (draft && load.data?.user && profilePendingChanges(draft, load.data.user))
        throw new Error("Сначала сохраните изменения анкеты.");
      if (!load.data?.requirements.documents_configured)
        throw new Error("Обязательные документы ещё не опубликованы командой платформы. Отправка анкеты станет доступна после публикации.");
      if (load.data.requirements.unaccepted_version_ids.some((id) => !checked.includes(id)))
        throw new Error("Прочитайте обязательные документы ниже и отметьте подтверждение ознакомления с каждым из них.");
      for (const document of load.data?.documents ?? []) {
        if (!document.accepted && checked.includes(document.id))
          await mutate(`/documents/${document.id}/consent`, {
            content_hash: document.content_hash,
            content_locale: document.content_locale,
          });
      }
      await mutate("/me/submit-registration");
      await load.reload();
    }, tr("Анкета отправлена на модерацию"));
  }
  const returnTo = safeReturnTo(
    typeof window === "undefined"
      ? null
      : new URLSearchParams(window.location.search).get("returnTo"),
  );
  const documentsConfigured = load.data?.requirements.documents_configured === true;
  const directionsUnavailable = !load.data?.directions.length;
  const profileDirty = Boolean(draft && load.data?.user && profilePendingChanges(draft, load.data.user));
  return (
    <AppShell
      title={tr("Профиль и регистрация")}
      description={tr(
        "Заполните анкету, прочитайте документы и отправьте профиль на проверку.",
      )}
      dashboard
    >
      <LoadState {...load} retry={load.reload}>
        <ActionNotice action={action} />
        {draft && (
          <div className="stack">
            <div className="panel">
              <div className="row">
                <h2>{draft.full_name || tr("Новый профиль")}</h2>
                <Badge
                  tone={
                    draft.account_status === "active" ? "success" : "warning"
                  }
                >
                  {tr(statusText(draft.account_status))}
                </Badge>
              </div>
              {draft.account_status === "pending" && (
                <div className="notice">
                  {tr(
                    "Анкета ожидает проверки. После решения команды здесь появится новый статус. Можно обновить страницу для проверки.",
                  )}
                </div>
              )}
              {draft.account_status === "changes_requested" && (
                <div className="error">
                  {tr("Команда попросила исправления.")}{" "}
                  {
                    load.data?.notifications.find((n) =>
                      n.title.includes("исправлений"),
                    )?.body
                  }
                </div>
              )}
              {draft.account_status === "active" && (
                <div className="notice">
                  {tr(
                    "Изменение данных анкеты потребует повторной модерации и временно закроет набор.",
                  )}
                </div>
              )}
              <form onSubmit={save} className="form-grid" aria-busy={action.busy}>
                <fieldset disabled={action.busy} className="form-grid full-width" style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
                <Field label={tr("Роль")}>
                  <select
                    value={draft.role}
                    disabled={load.data?.user.role !== "unchosen"}
                    onChange={(e) => update("role", e.target.value)}
                    required
                  >
                    <option value="unchosen" disabled>
                      {tr("Выберите роль")}
                    </option>
                    <option value="mentee">
                      {tr("Менти — ищу поддержку")}
                    </option>
                    <option value="mentor">
                      {tr("Ментор — делюсь опытом")}
                    </option>
                    {draft.role === "admin" && (
                      <option value="admin">{tr("Администратор")}</option>
                    )}
                  </select>
                </Field>
                {draft.role !== "unchosen" && <RegistrationFields draft={draft} directions={load.data?.directions || []} update={update} reloadDirections={load.reload} loading={load.loading || action.busy} />}
                <div className="full-width actions">
                  <Button
                    type="submit"
                    disabled={
                      action.busy ||
                      directionsUnavailable ||
                      draft.role === "unchosen" ||
                      !draft.direction_ids.length
                    }
                  >
                    {action.busy ? t.loading : tr("Сохранить профиль")}
                  </Button>
                  <Button onClick={load.reload} variant="secondary">
                    {tr("Обновить статус")}
                  </Button>
                </div>
                </fieldset>
              </form>
            </div>
            <div className="panel">
              <h2>{tr("Документы и согласия")}</h2>
              {profileDirty && <p className="notice" role="status">{tr("Сначала сохраните изменения анкеты.")}</p>}
              {load.data?.user.profile_completed && !documentsConfigured && (
                <div className="notice" role="status">
                  <p>{tr("Обязательные документы ещё не опубликованы командой платформы. Отправка анкеты станет доступна после публикации.")}</p>
                  <Button onClick={load.reload} disabled={action.busy || load.loading} variant="secondary">{tr("Обновить документы")}</Button>
                </div>
              )}
              {documentsConfigured && load.data?.requirements.unaccepted_version_ids.length !== 0 && (
                <p className="field-hint">{tr("Прочитайте обязательные документы ниже и отметьте подтверждение ознакомления с каждым из них.")}</p>
              )}
              {health?.demo_mode && (
                <div className="notice">
                  {tr(
                    "В локальной версии показаны проекты документов. Подтверждение ознакомления сохраняется для демонстрации; юридическую подпись этот интерфейс не оформляет.",
                  )}
                </div>
              )}
              {load.data?.documents.map((document) => (
                <div key={document.id} className="stack">
                  <details>
                    <summary>
                      {document.title} {tr("· версия")} {document.version}{" "}
                      {document.required ? tr("· обязательно") : ""}
                    </summary>
                    <div
                      className="document-content"
                      lang={document.content_locale || "ru"}
                    >
                      {document.content}
                    </div>
                    {locale !== "ru" && document.content_locale !== locale && (
                      <p className="field-hint">
                        {tr(
                          "Перевод документа пока недоступен. Показана исходная русская версия.",
                        )}
                      </p>
                    )}
                  </details>
                  <label className="check-row">
                    <input
                      type="checkbox"
                      disabled={document.accepted}
                      checked={
                        document.accepted || checked.includes(document.id)
                      }
                      onChange={(e) =>
                        setChecked(
                          e.target.checked
                            ? [...checked, document.id]
                            : checked.filter((id) => id !== document.id),
                        )
                      }
                    />
                    {document.accepted
                      ? tr("Ознакомление уже сохранено")
                      : tr(
                          health?.demo_mode
                            ? "Я прочитал(а) эту версию и подтверждаю ознакомление в демонстрационной среде"
                            : "Я прочитал(а) эту версию и подтверждаю ознакомление",
                        )}
                  </label>
                  <hr className="divider" />
                </div>
              ))}
              {!load.data?.documents.length && !load.data?.user.profile_completed && (
                <p>
                  {tr(
                    directionsUnavailable
                      ? "Сначала дождитесь открытия направлений. После сохранения профиля здесь появятся документы для вашей роли."
                      : "Сохраните роль и направления, чтобы получить применимые документы.",
                  )}
                </p>
              )}
              <Button
                disabled={
                  action.busy ||
                  profileDirty ||
                  directionsUnavailable ||
                  !documentsConfigured ||
                  !draft.profile_completed ||
                  !["draft", "changes_requested"].includes(
                    draft.account_status,
                  ) ||
                  load.data?.requirements.unaccepted_version_ids.some((id) => !checked.includes(id))
                }
                onClick={submitDocuments}
              >
                {tr("Сохранить согласия и отправить анкету")}
              </Button>
              {draft.account_status === "active" && (
                <div className="actions">
                  <Button
                    disabled={action.busy || !checked.length}
                    variant="secondary"
                    onClick={() =>
                      action.run(async () => {
                        for (const id of checked) {
                          const document = load.data?.documents.find(
                            (d) => d.id === id,
                          );
                          await mutate(`/documents/${id}/consent`, {
                            content_hash: document?.content_hash,
                            content_locale: document?.content_locale,
                          });
                        }
                        await load.reload();
                      }, tr("Ознакомление с обновлёнными документами сохранено"))
                    }
                  >
                    {tr("Подтвердить новые версии документов")}
                  </Button>
                  <Button href={returnTo}>
                    {returnTo === "/dashboard"
                      ? t.dashboard
                      : tr("Продолжить выбранный путь")}
                  </Button>
                </div>
              )}
            </div>
          </div>
        )}
      </LoadState>
    </AppShell>
  );
}
