"use client";
import { useEffect, useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import type { User, Direction, DocumentVersion } from "@/lib/types";
import { AppShell } from "@/components/shell";
import { Badge, Button, Field } from "@/components/ui";
import { useLocale, translatePhrase as tr } from "@/lib/i18n";
import { usePlatformStatus } from "@/components/platform-status";
import { AITextAssistant, AIReviewPreference } from "@/components/ai-assistant";
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

function evidenceProblem(values: string[]) {
  const links = values.map((value) => value.trim()).filter(Boolean);
  if (!links.length) return "Добавьте хотя бы одну ссылку на ваш опыт.";
  if (links.length > 10) return "Можно добавить не более 10 ссылок.";
  for (const link of links) {
    try {
      const url = new URL(link);
      if (!["http:", "https:"].includes(url.protocol) || link.length > 2083)
        return "Укажите полный адрес сайта, например https://github.com/username. Каждая ссылка — с новой строки.";
    } catch {
      return "Укажите полный адрес сайта, например https://github.com/username. Каждая ссылка — с новой строки.";
    }
  }
  return "";
}

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
        current && current.id === user.id
          ? {
              ...current,
              account_status: user.account_status,
              profile_completed: user.profile_completed,
            }
          : user,
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
      if (!availableDirections.length)
        throw new Error("Направления пока не открыты. Команда платформы готовит список. Вы сможете завершить анкету, когда он появится.");
      if (!draft.direction_ids.length || draft.direction_ids.length > 10 ||
          draft.direction_ids.some((id) => !availableDirections.some((direction) => direction.id === id)))
        throw new Error("Выберите от 1 до 10 доступных направлений.");
      if (draft.role === "mentor") {
        const problem = evidenceProblem(draft.evidence_urls || []);
        if (problem) throw new Error(problem);
      }
      await mutate(
        "/me/profile",
        {
          preferred_locale: locale,
          full_name: draft.full_name,
          ...(draft.role === "admin" ? {} : { role: draft.role }),
          timezone: draft.timezone,
          city: draft.city,
          phone: draft.phone || "",
          birth_date: draft.birth_date || null,
          bio: draft.bio || "",
          expertise: draft.expertise || "",
          evidence_urls: (draft.evidence_urls || [])
            .map((value) => value.trim())
            .filter(Boolean),
          direction_ids: draft.direction_ids,
          capacity: draft.capacity ?? 1,
        },
        "PUT",
      );
      await load.reload();
    }, tr("Профиль сохранён. Проверьте актуальные документы ниже."));
  }
  async function submitDocuments() {
    await action.run(async () => {
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
  const evidenceError = draft?.role === "mentor" ? evidenceProblem(draft.evidence_urls || []) : "";
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
                    "Изменение имени, описания, экспертизы, подтверждений, направлений или вместимости потребует повторной модерации и временно закроет набор.",
                  )}
                </div>
              )}
              <form onSubmit={save} className="form-grid">
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
                <Field label={tr("Имя и фамилия")}>
                  <input
                    required
                    minLength={2}
                    maxLength={160}
                    value={draft.full_name}
                    onChange={(e) => update("full_name", e.target.value)}
                  />
                </Field>
                <Field label={t.city}>
                  <input
                    required
                    maxLength={120}
                    value={draft.city}
                    onChange={(e) => update("city", e.target.value)}
                  />
                </Field>
                <Field
                  label={t.timezone}
                  hint={tr("Название IANA, например Asia/Oral или Asia/Almaty")}
                >
                  <input
                    required
                    value={draft.timezone}
                    onChange={(e) => update("timezone", e.target.value)}
                  />
                </Field>
                {draft.role === "mentee" && (
                  <Field label={tr("Дата рождения")}>
                    <input
                      type="date"
                      required
                      value={draft.birth_date?.slice(0, 10) || ""}
                      onChange={(e) => update("birth_date", e.target.value)}
                    />
                  </Field>
                )}
                <Field label={tr("Телефон (необязательно)")}>
                  <input
                    type="tel"
                    maxLength={40}
                    value={draft.phone || ""}
                    onChange={(e) => update("phone", e.target.value)}
                  />
                </Field>
                <div className="full-width">
                  <Field label={tr("О себе и целях")}>
                    <textarea
                      required
                      minLength={10}
                      maxLength={5000}
                      value={draft.bio || ""}
                      onChange={(e) => update("bio", e.target.value)}
                    />
                  </Field>
                </div>
                {draft.role === "mentor" && (
                  <>
                    <div className="full-width">
                      <Field label={t.expertise}>
                        <textarea
                          required
                          minLength={10}
                          maxLength={3000}
                          value={draft.expertise || ""}
                          onChange={(e) => update("expertise", e.target.value)}
                        />
                      </Field>
                    </div>
                    <Field
                      label={tr("Ссылки на опыт")}
                      hint={tr(
                        "Ссылки на LinkedIn, GitHub, портфолио или публикации — по одной в строке, до 10. Видны только команде проверки.",
                      )}
                    >
                      <textarea
                        required
                        placeholder={"https://www.linkedin.com/in/username\nhttps://github.com/username"}
                        aria-invalid={Boolean(evidenceError && draft.evidence_urls?.some((value) => value.trim()))}
                        aria-describedby={evidenceError ? "evidence-error" : undefined}
                        value={(draft.evidence_urls || []).join("\n")}
                        onChange={(e) => {
                          const links = e.target.value.split("\n");
                          e.currentTarget.setCustomValidity(tr(evidenceProblem(links)));
                          update("evidence_urls", links);
                        }}
                      />
                      {evidenceError && draft.evidence_urls?.some((value) => value.trim()) &&
                        <span id="evidence-error" className="field-hint">{tr(evidenceError)}</span>}
                    </Field>
                    <Field
                      label={tr("Сколько менти готовы вести одновременно")}
                      hint={tr("Например, 3 — до трёх менти одновременно. 0 — свободных мест нет.")}
                    >
                      <input
                        type="number"
                        min={0}
                        max={50}
                        required
                        value={draft.capacity ?? 1}
                        onChange={(e) =>
                          update("capacity", Number(e.target.value))
                        }
                      />
                    </Field>
                  </>
                )}
                <fieldset className="full-width panel">
                  <legend>{tr("Направления")}</legend>
                  {directionsUnavailable ? (
                    <div className="notice" role="status">
                      <p>{tr("Направления пока не открыты. Команда платформы готовит список. Вы сможете завершить анкету, когда он появится.")}</p>
                      <Button onClick={load.reload} disabled={load.loading || action.busy} variant="secondary">{tr("Обновить список направлений")}</Button>
                    </div>
                  ) : <p className="field-hint">{tr("Выберите от 1 до 10 доступных направлений.")}</p>}
                  <div className="tags">
                    {load.data?.directions.map((direction) => (
                      <label className="check-row" key={direction.id}>
                        <input
                          type="checkbox"
                          checked={draft.direction_ids.includes(direction.id)}
                          onChange={(e) =>
                            update(
                              "direction_ids",
                              e.target.checked
                                ? [...draft.direction_ids, direction.id]
                                : draft.direction_ids.filter(
                                    (id) => id !== direction.id,
                                  ),
                            )
                          }
                        />
                        {direction[`name_${locale}`]}
                      </label>
                    ))}
                  </div>
                </fieldset>
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
              </form>
            </div>
            {draft.role !== "admin" && (
              <>
                <AITextAssistant
                  purpose="profile"
                  initialText={draft.bio || ""}
                  onApply={(proposal) =>
                    update("bio", proposal.description.slice(0, 5000))
                  }
                />
                <AIReviewPreference />
              </>
            )}
            <div className="panel">
              <h2>{tr("Документы и согласия")}</h2>
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
