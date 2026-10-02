"use client";
import { NextStepCards } from "@/components/notification-center";
import { useState, type FormEvent } from "react";
import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import type {
  Application,
  Booking,
  Mentor,
  Participation,
  Project,
  Result,
  User,
} from "@/lib/types";
import { AppShell } from "@/components/shell";
import {
  Badge,
  Button,
  EmptyState,
  Field,
  SectionHeading,
} from "@/components/ui";
import { useLocale, translatePhrase as tr } from "@/lib/i18n";
import {
  ActionNotice,
  dateTime,
  LoadState,
  mutate,
  safeUrl,
  statusText,
  useAction,
  useLoad,
} from "@/components/workflows/common";
type Notification = {
  id: string;
  title: string;
  body: string;
  read_at?: string | null;
};
function ParticipationCard({
  item,
  refresh,
}: {
  item: Participation;
  refresh: () => Promise<void>;
}) {
  const { locale, tr } = useLocale();
  const action = useAction();
  const [mode, setMode] = useState("");
  const [reason, setReason] = useState("");
  const [summary, setSummary] = useState("");
  const [artifact, setArtifact] = useState("");
  const [outcome, setOutcome] = useState("completed_successfully");
  const [rating, setRating] = useState("");
  const [nps, setNps] = useState("");
  const reasons = useLoad(() =>
    api<{ value: string; label: string }[]>("/exit-reasons"),
  );
  const ongoing = ["active", "paused"].includes(item.status);
  async function submit(event: FormEvent) {
    event.preventDefault();
    await action.run(
      async () => {
        if (mode === "pause")
          await mutate(`/participations/${item.id}/pause`, { reason });
        if (mode === "complete")
          await mutate(`/participations/${item.id}/complete`, {
            status: outcome,
            exit_reason: reason,
            summary,
            artifact_url: artifact || null,
          });
        if (mode === "feedback")
          await mutate(`/participations/${item.id}/feedback`, {
            rating: Number(rating),
            nps: nps === "" ? null : Number(nps),
            comment: summary,
          });
        setMode("");
        await refresh();
      },
      mode === "feedback"
        ? tr("Отзыв сохранён")
        : tr("Статус участия обновлён"),
    );
  }
  return (
    <article className="card">
      <div className="row">
        <h3>{item.project_title || tr("Индивидуальное менторство")}</h3>
        <Badge tone={ongoing ? "blue" : "success"}>
          {tr(statusText(item.status))}
        </Badge>
      </div>
      <p>
        {item.mentor_name || tr("Ментор")} · {item.mentee_name || tr("Менти")}
      </p>
      <ActionNotice action={action} />
      <div className="actions">
        {item.status === "active" && (
          <Button
            variant="secondary"
            onClick={() => {
              setMode("pause");
              setReason("");
            }}
          >
            {tr("Пауза")}
          </Button>
        )}
        {item.status === "paused" && (
          <Button
            disabled={action.busy}
            onClick={() =>
              action.run(async () => {
                await mutate(`/participations/${item.id}/resume`);
                await refresh();
              })
            }
          >
            {tr("Возобновить")}
          </Button>
        )}
        {ongoing && (
          <Button
            variant="secondary"
            onClick={() => {
              setMode("complete");
              setOutcome("completed_successfully");
              setReason("goal_achieved");
              setSummary("");
            }}
          >
            {tr("Зафиксировать результат")}
          </Button>
        )}
        {!ongoing && (
          <Button
            variant="secondary"
            onClick={() => {
              setMode("feedback");
              setSummary("");
              setRating("");
              setNps("");
            }}
          >
            {tr("Оставить отзыв")}
          </Button>
        )}
        <Button href="/messages" variant="ghost">
          {tr("Сообщения")}
        </Button>
        {item.project_id && (
          <Button href={`/projects/${item.project_id}`} variant="ghost">
            {tr("Проект и публикация результата")}
          </Button>
        )}
      </div>
      {mode && (
        <form
          onSubmit={submit}
          className="form-stack"
          style={{ marginTop: 20 }}
        >
          {mode === "complete" && (
            <>
              <div className="notice">
                {tr(
                  "Завершение участия отменит будущие встречи, связанные с ним. Отзывы можно оставить после завершения.",
                )}
              </div>
              <Field label={tr("Итог")}>
                <select
                  value={outcome}
                  onChange={(e) => {
                    setOutcome(e.target.value);
                    setReason(
                      e.target.value === "completed_successfully"
                        ? "goal_achieved"
                        : "",
                    );
                  }}
                >
                  <option value="completed_successfully">
                    {tr("Успешное завершение")}
                  </option>
                  <option value="completed_early">
                    {tr("Досрочное завершение")}
                  </option>
                </select>
              </Field>
              <LoadState {...reasons} retry={reasons.reload}>
                <Field label={tr("Причина завершения")}>
                  <select
                    required
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                  >
                    <option value="">{tr("Выберите причину")}</option>
                    {reasons.data
                      ?.filter((r) =>
                        outcome === "completed_successfully"
                          ? r.value === "goal_achieved"
                          : r.value !== "goal_achieved",
                      )
                      .map((r) => (
                        <option value={r.value} key={r.value}>
                          {tr(r.label)}
                        </option>
                      ))}
                  </select>
                </Field>
              </LoadState>
              <Field
                label={
                  outcome === "completed_successfully"
                    ? tr("Ссылка на достигнутый результат")
                    : tr("Ссылка на результат (необязательно)")
                }
              >
                <input
                  type="url"
                  required={outcome === "completed_successfully"}
                  value={artifact}
                  onChange={(e) => setArtifact(e.target.value)}
                />
              </Field>
            </>
          )}
          {mode === "pause" ? (
            <>
              <div className="notice">
                {tr(
                  "При паузе будущие встречи этого участия будут отменены. После возобновления их нужно запланировать заново.",
                )}
              </div>
              <Field label={tr("Причина паузы")}>
                <textarea
                  required
                  minLength={3}
                  maxLength={2000}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
              </Field>
            </>
          ) : (
            <Field
              label={
                mode === "feedback"
                  ? tr("Комментарий (необязательно)")
                  : tr("Что было достигнуто")
              }
            >
              <textarea
                required={mode !== "feedback"}
                minLength={mode === "feedback" ? undefined : 10}
                maxLength={5000}
                value={summary}
                onChange={(e) => setSummary(e.target.value)}
              />
            </Field>
          )}
          {mode === "feedback" && (
            <div className="form-grid">
              <Field label={tr("Оценка, 1–5")}>
                <select
                  required
                  value={rating}
                  onChange={(e) => setRating(e.target.value)}
                >
                  <option value="">{tr("Выберите оценку")}</option>
                  {[1, 2, 3, 4, 5].map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </Field>
              <Field
                label={tr("Готовность рекомендовать, 0–10 (необязательно)")}
              >
                <select value={nps} onChange={(e) => setNps(e.target.value)}>
                  <option value="">{tr("Не отвечать")}</option>
                  {Array.from({ length: 11 }, (_, value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
          )}
          <div className="actions">
            <Button disabled={action.busy} type="submit">
              {tr("Сохранить")}
            </Button>
            <Button variant="ghost" onClick={() => setMode("")}>
              {tr("Отмена")}
            </Button>
          </div>
        </form>
      )}
    </article>
  );
}
function Dashboard() {
  const { t, locale, tr } = useLocale();
  const search = useSearchParams();
  const router = useRouter();
  const requestedMentor = search.get("mentor");
  const action = useAction();
  const [motivation, setMotivation] = useState("");
  const [project, setProject] = useState("");
  const [decisionReason, setDecisionReason] = useState<Record<string, string>>(
    {},
  );
  const [capacity, setCapacity] = useState<string>("");
  const load = useLoad(async () => {
    const user = await api<User>("/auth/me");
    if (user.account_status !== "active")
      return {
        user,
        applications: [] as Application[],
        participations: [] as Participation[],
        bookings: [] as Booking[],
        projects: [] as Project[],
        results: [] as Result[],
        notifications: [] as Notification[],
      };
    const [
      applications,
      participations,
      bookings,
      projects,
      results,
      notifications,
    ] = await Promise.all([
      api<Application[]>("/applications"),
      api<Participation[]>("/participations"),
      api<Booking[]>("/bookings"),
      api<Project[]>("/projects/mine"),
      api<Result[]>("/results"),
      api<Notification[]>("/notifications"),
    ]);
    return {
      user,
      applications,
      participations,
      bookings,
      projects,
      results,
      notifications,
    };
  });
  const mentor = useLoad(
    () =>
      requestedMentor
        ? api<Mentor>(`/mentors/${encodeURIComponent(requestedMentor)}`)
        : Promise.resolve(null),
    [requestedMentor],
  );
  async function request(event: FormEvent) {
    event.preventDefault();
    await action.run(async () => {
      await mutate("/applications", {
        mentor_id: requestedMentor,
        project_id: project || null,
        motivation,
      });
      setMotivation("");
      await load.reload();
    }, tr("Заявка отправлена. Ответ появится в кабинете."));
  }
  const user = load.data?.user;
  return (
    <AppShell
      title={t.dashboard}
      description={tr("Ваши заявки, встречи и движение к результату.")}
      dashboard
    >
      <LoadState {...load} retry={load.reload}>
        <ActionNotice action={action} />
        {user && (
          <div className="stack">
            <NextStepCards timezone={user.timezone}/>
            <div className="panel">
              <div className="row">
                <div>
                  <h2>{user.full_name || user.email}</h2>
                  <Badge
                    tone={
                      user.account_status === "active" ? "success" : "warning"
                    }
                  >
                    {tr(statusText(user.role))} ·{" "}
                    {tr(statusText(user.account_status))}
                  </Badge>
                </div>
                <div className="actions">
                  <Button href="/onboarding" variant="secondary">
                    {tr("Изменить профиль")}
                  </Button>
                  <Button
                    variant="ghost"
                    disabled={action.busy}
                    onClick={() =>
                      action.run(async () => {
                        await mutate("/auth/logout");
                        router.push("/login");
                        router.refresh();
                      }, tr("Вы вышли"))
                    }
                  >
                    {tr("Выйти")}
                  </Button>
                </div>
              </div>
              {user.account_status !== "active" ? (
                <div className="notice">
                  {tr(
                    "Следующий шаг: заполните анкету и документы, затем дождитесь модерации.",
                  )}{" "}
                  <Button
                    href={`/onboarding?returnTo=${encodeURIComponent(requestedMentor ? `/dashboard?mentor=${encodeURIComponent(requestedMentor)}` : "/dashboard")}`}
                  >
                    {tr("Открыть регистрацию")}
                  </Button>
                </div>
              ) : (
                <p>
                  {tr("Следующий шаг:")}{" "}
                  {load.data?.participations.some((p) =>
                    ["active", "paused"].includes(p.status),
                  )
                    ? tr(
                        "запланируйте встречу и согласуйте ближайший результат.",
                      )
                    : user.role === "mentor"
                      ? tr(
                          "откройте набор, создайте проект или рассмотрите входящие заявки.",
                        )
                      : tr(
                          "выберите ментора или проект и расскажите о своей цели.",
                        )}
                </p>
              )}
            </div>
            {user.account_status === "active" && (
              <>
                <div className="grid-3">
                  {[
                    [
                      tr("Текущих участий"),
                      load.data!.participations.filter((p) =>
                        ["active", "paused"].includes(p.status),
                      ).length,
                    ],
                    [
                      tr("Заявок на рассмотрении"),
                      load.data!.applications.filter(
                        (a) => a.status === "pending",
                      ).length,
                    ],
                    [
                      tr("Предстоящих встреч"),
                      load.data!.bookings.filter(
                        (b) =>
                          b.status === "scheduled" &&
                          new Date(b.starts_at) > new Date(),
                      ).length,
                    ],
                  ].map(([label, value]) => (
                    <div className="card" key={label}>
                      <div className="stat">{value}</div>
                      <p>{label}</p>
                    </div>
                  ))}
                </div>
                {user.role === "mentor" && (
                  <section className="panel">
                    <h2>{tr("Набор участников")}</h2>
                    <p>
                      {tr("Текущая вместимость:")} {user.capacity} ·{" "}
                      {user.intake_open ? t.openIntake : t.closedIntake}
                    </p>
                    <form
                      className="form-grid"
                      onSubmit={(e) => {
                        e.preventDefault();
                        action.run(async () => {
                          await mutate(
                            "/me/intake",
                            {
                              intake_open: !user.intake_open,
                              capacity:
                                capacity === ""
                                  ? user.capacity
                                  : Number(capacity),
                            },
                            "PATCH",
                          );
                          await load.reload();
                        }, tr("Настройки набора обновлены"));
                      }}
                    >
                      <Field label={tr("Вместимость")}>
                        <input
                          type="number"
                          min={0}
                          max={50}
                          value={capacity}
                          placeholder={String(user.capacity ?? 1)}
                          onChange={(e) => setCapacity(e.target.value)}
                        />
                      </Field>
                      <div className="actions">
                        <Button disabled={action.busy} type="submit">
                          {user.intake_open
                            ? tr("Закрыть набор")
                            : tr("Открыть набор")}
                        </Button>
                        <Button href="/calendar" variant="secondary">
                          {tr("Добавить время встречи")}
                        </Button>
                      </div>
                    </form>
                  </section>
                )}
                {requestedMentor && user.role === "mentee" && (
                  <section className="panel">
                    <LoadState {...mentor} retry={mentor.reload}>
                      <h2>
                        {tr("Заявка:")} {mentor.data?.full_name}
                      </h2>
                      <form onSubmit={request} className="form-stack">
                        <Field label={tr("Мой проект (необязательно)")}>
                          <select
                            value={project}
                            onChange={(e) => setProject(e.target.value)}
                          >
                            <option value="">
                              {tr("Индивидуальное менторство")}
                            </option>
                            {load.data?.projects
                              .filter((p) => p.owner_id === user.id)
                              .map((p) => (
                                <option key={p.id} value={p.id}>
                                  {p.title}
                                </option>
                              ))}
                          </select>
                        </Field>
                        <Field label={tr("Ваша цель и запрос")}>
                          <textarea
                            required
                            minLength={20}
                            maxLength={5000}
                            value={motivation}
                            onChange={(e) => setMotivation(e.target.value)}
                          />
                        </Field>
                        <Button
                          type="submit"
                          disabled={action.busy || !mentor.data?.intake_open}
                        >
                          {t.apply}
                        </Button>
                      </form>
                    </LoadState>
                  </section>
                )}
                <section>
                  <SectionHeading
                    title={tr("Мои проекты")}
                    action={
                      <Button href="/projects/new" variant="secondary">
                        {tr("Создать проект")}
                      </Button>
                    }
                  />
                  {!load.data?.projects.length ? (
                    <EmptyState
                      title={tr("Ваших проектов пока нет")}
                      description={tr(
                        "Можно предложить свою задачу или присоединиться к проекту ментора.",
                      )}
                    />
                  ) : (
                    <div className="grid-2">
                      {load.data.projects.map((item) => (
                        <article className="card" key={item.id}>
                          <Badge>
                            {tr(statusText(item.visibility_status))}
                          </Badge>
                          <h3>{item.title}</h3>
                          <p>{item.problem}</p>
                          <Button
                            variant="secondary"
                            href={`/projects/${item.id}`}
                          >
                            {tr("Открыть проект")}
                          </Button>
                        </article>
                      ))}
                    </div>
                  )}
                </section>
                <section>
                  <SectionHeading
                    title={tr("Заявки")}
                    action={
                      <Button href="/catalog" variant="secondary">
                        {t.findMentor}
                      </Button>
                    }
                  />
                  {!load.data?.applications.length ? (
                    <EmptyState
                      title={tr("Заявок пока нет")}
                      description={tr(
                        "Найдите подходящего ментора или предложите свой проект.",
                      )}
                    />
                  ) : (
                    <div className="grid-2">
                      {load.data.applications.map((application) => (
                        <article className="card" key={application.id}>
                          <div className="row">
                            <h3>
                              {application.project_title ||
                                tr("Индивидуальный запрос")}
                            </h3>
                            <Badge>{tr(statusText(application.status))}</Badge>
                          </div>
                          <p>
                            {application.mentee_name || tr("Менти")} →{" "}
                            {application.mentor_name || tr("Ментор")}
                          </p>
                          <p className="pre-line">{application.motivation}</p>
                          {application.rejection_reason && (
                            <p>
                              {tr("Причина:")}{" "}
                              {tr(statusText(application.rejection_reason))}
                            </p>
                          )}
                          {application.status === "pending" &&
                            (application.mentor_id === user.id ? (
                              <>
                                <Field label={tr("Причина отклонения")}>
                                  <select
                                    value={decisionReason[application.id] || ""}
                                    onChange={(e) =>
                                      setDecisionReason({
                                        ...decisionReason,
                                        [application.id]: e.target.value,
                                      })
                                    }
                                  >
                                    <option value="">
                                      {tr("Выберите причину для отказа")}
                                    </option>
                                    <option value="capacity_full">
                                      {tr("Нет свободных мест")}
                                    </option>
                                    <option value="direction_mismatch">
                                      {tr("Не совпадает направление")}
                                    </option>
                                    <option value="skills_mismatch">
                                      {tr("Не подходят навыки")}
                                    </option>
                                    <option value="insufficient_information">
                                      {tr("Недостаточно информации")}
                                    </option>
                                    <option value="not_a_fit">
                                      {tr("Запрос не подходит")}
                                    </option>
                                    <option value="project_closed">
                                      {tr("Проект закрыт")}
                                    </option>
                                  </select>
                                </Field>
                                <div className="actions">
                                  {["accepted", "rejected"].map((decision) => (
                                    <Button
                                      key={decision}
                                      variant={
                                        decision === "accepted"
                                          ? "primary"
                                          : "secondary"
                                      }
                                      disabled={
                                        action.busy ||
                                        (decision === "rejected" &&
                                          !decisionReason[application.id])
                                      }
                                      onClick={() =>
                                        action.run(
                                          async () => {
                                            await mutate(
                                              `/applications/${application.id}/decision`,
                                              {
                                                decision,
                                                reason:
                                                  decision === "rejected"
                                                    ? decisionReason[
                                                        application.id
                                                      ]
                                                    : null,
                                              },
                                            );
                                            await load.reload();
                                          },
                                          decision === "accepted"
                                            ? tr(
                                                "Заявка принята. Участие и диалог созданы.",
                                              )
                                            : tr("Заявка отклонена"),
                                        )
                                      }
                                    >
                                      {decision === "accepted"
                                        ? tr("Принять")
                                        : tr("Отклонить")}
                                    </Button>
                                  ))}
                                </div>
                              </>
                            ) : (
                              <Button
                                disabled={action.busy}
                                variant="secondary"
                                onClick={() =>
                                  action.run(async () => {
                                    await mutate(
                                      `/applications/${application.id}/withdraw`,
                                    );
                                    await load.reload();
                                  }, tr("Заявка отозвана"))
                                }
                              >
                                {tr("Отозвать заявку")}
                              </Button>
                            ))}
                        </article>
                      ))}
                    </div>
                  )}
                </section>
                <section>
                  <SectionHeading title={tr("Менторство")} />
                  {!load.data?.participations.length ? (
                    <EmptyState title={tr("Активных участий пока нет")} />
                  ) : (
                    <div className="grid-2">
                      {load.data.participations.map((item) => (
                        <ParticipationCard
                          item={item}
                          key={item.id}
                          refresh={load.reload}
                        />
                      ))}
                    </div>
                  )}
                </section>
                <section className="panel">
                  <SectionHeading
                    title={tr("Ближайшие встречи")}
                    action={
                      <Button href="/calendar" variant="secondary">
                        {t.calendar}
                      </Button>
                    }
                  />
                  {load.data?.bookings
                    .filter(
                      (b) =>
                        b.status === "scheduled" &&
                        new Date(b.starts_at) > new Date(),
                    )
                    .slice(0, 5)
                    .map((booking) => (
                      <div className="row" key={booking.id}>
                        <p>
                          {dateTime(booking.starts_at, user.timezone, locale)} ·{" "}
                          {booking.mentor_name} / {booking.mentee_name}
                        </p>
                        <Badge tone="blue">{user.timezone}</Badge>
                      </div>
                    ))}
                  {!load.data?.bookings.some(
                    (b) =>
                      b.status === "scheduled" &&
                      new Date(b.starts_at) > new Date(),
                  ) && <p>{tr("Предстоящих встреч нет.")}</p>}
                </section>
                <section>
                  <SectionHeading title={tr("Мои результаты")} />
                  {!load.data?.results.length ? (
                    <EmptyState
                      title={tr(
                        "Результаты появятся после завершения менторства",
                      )}
                    />
                  ) : (
                    <div className="grid-2">
                      {load.data.results.map((result) => (
                        <article className="card" key={result.id}>
                          <Badge
                            tone={
                              result.verification_status === "verified"
                                ? "success"
                                : "warning"
                            }
                          >
                            {tr(statusText(result.verification_status))}
                          </Badge>
                          <h3>{tr(statusText(result.status))}</h3>
                          <p>{result.summary}</p>
                          <p>
                            {tr("Встреч:")} {result.meeting_count}
                          </p>
                          {user.role === "mentor" &&
                            result.status === "completed_successfully" &&
                            result.verification_status !== "verified" && (
                              <Button
                                disabled={action.busy}
                                onClick={() =>
                                  action.run(async () => {
                                    await mutate(
                                      `/results/${result.id}/verify`,
                                    );
                                    await load.reload();
                                  }, tr("Результат подтверждён ментором"))
                                }
                              >
                                {tr("Подтвердить результат")}
                              </Button>
                            )}
                          {safeUrl(result.artifact_url) && (
                            <a
                              className="text-link"
                              href={safeUrl(result.artifact_url)}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              {tr("Открыть результат")}
                            </a>
                          )}
                        </article>
                      ))}
                    </div>
                  )}
                </section>
              </>
            )}
            <section className="panel">
              <h2>{tr("Уведомления")}</h2>
              {load.data?.notifications.length ? (
                load.data.notifications.map((notification) => (
                  <div className="row" key={notification.id}>
                    <div>
                      <strong>{tr(notification.title)}</strong>
                      <p>{notification.body}</p>
                    </div>
                    {!notification.read_at && (
                      <Button
                        disabled={action.busy}
                        variant="ghost"
                        onClick={() =>
                          action.run(async () => {
                            await mutate(
                              `/notifications/${notification.id}/read`,
                              undefined,
                              "PATCH",
                            );
                            await load.reload();
                          })
                        }
                      >
                        {tr("Прочитано")}
                      </Button>
                    )}
                  </div>
                ))
              ) : (
                <p>{tr("Новых уведомлений нет.")}</p>
              )}
            </section>
          </div>
        )}
      </LoadState>
    </AppShell>
  );
}
export default function DashboardPage() {
  const { locale, tr } = useLocale();
  return (
    <Suspense
      fallback={<div className="loading-state">{tr("Загружаем кабинет…")}</div>}
    >
      <Dashboard />
    </Suspense>
  );
}

