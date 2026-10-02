"use client";
import { useState } from "react";
import { api, ApiError, mutate, safeUrl } from "@/lib/api";
import { dateTime } from "@/lib/i18n";
import {
  ActionNotice,
  DataState,
  ErrorNotice,
  NoData,
  Pager,
  useAction,
  useLoad,
  usePaged,
  webUrl,
} from "@/components/common";
import { Badge, Button, Field, SectionHeading } from "@/components/ui";
import { useActivityLocale } from "./locale";

type Participation = {
  id: string;
  project_id: string | null;
  project_title: string | null;
  mentee_name: string;
  mentor_name: string | null;
  status: string;
  started_at: string;
  completed_at: string | null;
};
type Booking = {
  id: string;
  participation_id: string | null;
  mentor_name: string;
  mentee_name: string;
  status: string;
  starts_at: string;
  ends_at: string;
  timezone: string;
  meeting_url: string | null;
};
type ExitReason = { value: string; label: string };

function Notice({ action }: { action: ReturnType<typeof useAction> }) {
  const { tr, locale } = useActivityLocale();
  const error = action.error;
  const translated = error instanceof Error ? tr(error.message) : "";
  const generic = error instanceof ApiError && (error.status === 0 || error.status === 401) || locale !== "ru" && error instanceof Error && translated === error.message;
  return (
    <>
      {generic ? <ErrorNotice error={error}/> : error instanceof Error && (
        <div className="error" role="alert">
          {translated}
        </div>
      )}
      <ActionNotice action={{ ...action, error: undefined }} />
    </>
  );
}

function ParticipationCard({
  row,
  reasons,
  refresh,
}: {
  row: Participation;
  reasons: ExitReason[];
  refresh: () => Promise<void>;
}) {
  const { tr, locale, status } = useActivityLocale();
  const action = useAction();
  const [pauseReason, setPauseReason] = useState("");
  const [closing, setClosing] = useState(false);
  const [exitReason, setExitReason] = useState("lack_time");
  const [summary, setSummary] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const ongoing = row.status === "active" || row.status === "paused";
  async function change(path: string, body?: unknown) {
    const done = await action.run(async () => {
      await mutate(`/participations/${row.id}/${path}`, body);
      await refresh();
    });
    if (done) {
      setClosing(false);
      setConfirmed(false);
    }
  }
  return (
    <article className="card stack">
      <div className="row">
        <h3>{row.project_title || tr("Без проекта")}</h3>
        <Badge tone={ongoing ? "blue" : "neutral"}>{status(row.status)}</Badge>
      </div>
      <p>
        <strong>{tr("Менти")}:</strong> {row.mentee_name}
        <br />
        <strong>{tr("Ментор")}:</strong> {row.mentor_name || "—"}
      </p>
      <p className="muted">
        {tr("Начало участия")}: {dateTime(row.started_at, locale)}
        {row.completed_at && (
          <>
            <br />
            {tr("Завершение участия")}: {dateTime(row.completed_at, locale)}
          </>
        )}
      </p>
      <Notice action={action} />
      {row.status === "active" && (
        <>
          <Field label={tr("Причина паузы")}>
            <textarea
              maxLength={2000}
              value={pauseReason}
              onChange={(e) => setPauseReason(e.target.value)}
            />
          </Field>
          <Button
            variant="secondary"
            disabled={action.busy || !pauseReason.trim()}
            onClick={() => change("pause", { reason: pauseReason.trim() })}
          >
            {tr("Поставить на паузу")}
          </Button>
        </>
      )}
      {row.status === "paused" && (
        <Button disabled={action.busy} onClick={() => change("resume")}>
          {tr("Возобновить")}
        </Button>
      )}
      {ongoing && !closing && (
        <Button
          variant="danger"
          disabled={action.busy}
          onClick={() => {
            setClosing(true);
            action.clear();
          }}
        >
          {tr("Завершить досрочно")}
        </Button>
      )}
      {ongoing && closing && (
        <form
          className="stack"
          onSubmit={(e) => {
            e.preventDefault();
            if (
              confirmed &&
              summary.trim() &&
              reasons.some((reason) => reason.value === exitReason)
            )
              void change("complete", {
                status: "completed_early",
                exit_reason: exitReason,
                summary: summary.trim(),
              });
          }}
        >
          <h4>{tr("Досрочное завершение")}</h4>
          {reasons.length ? (
            <Field label={tr("Причина завершения")}>
              <select
                required
                value={exitReason}
                onChange={(e) => setExitReason(e.target.value)}
              >
                {reasons
                  .filter((reason) => reason.value !== "goal_achieved")
                  .map((reason) => (
                    <option key={reason.value} value={reason.value}>
                      {tr(reason.label)}
                    </option>
                  ))}
              </select>
            </Field>
          ) : (
            <p className="error">
              {tr("Причины завершения недоступны. Повторите загрузку.")}
            </p>
          )}
          <Field label={tr("Комментарий администратора")}>
            <textarea
              required
              maxLength={10000}
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
            />
          </Field>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            {tr("Подтвердить досрочное завершение")}
          </label>
          <div className="actions">
            <Button
              type="submit"
              variant="danger"
              disabled={
                action.busy ||
                !confirmed ||
                !summary.trim() ||
                !reasons.some((reason) => reason.value === exitReason)
              }
            >
              {tr("Завершить досрочно")}
            </Button>
            <Button
              variant="ghost"
              disabled={action.busy}
              onClick={() => {
                setClosing(false);
                setConfirmed(false);
              }}
            >
              {tr("Закрыть форму")}
            </Button>
          </div>
        </form>
      )}
      {row.project_id && (
        <a
          className="text-link"
          href={`${webUrl}/projects/${encodeURIComponent(row.project_id)}`}
          target="_blank"
          rel="noopener noreferrer"
        >
          {tr("Открыть проект")}
        </a>
      )}
    </article>
  );
}

function ParticipationList() {
  const { tr, status } = useActivityLocale();
  const [filter, setFilter] = useState("active");
  const load = usePaged<Participation>(
    `/admin/participations${filter ? `?status=${filter}` : ""}`,
  );
  const reasons = useLoad(() => api<ExitReason[]>("/exit-reasons"));
  return (
    <section className="stack">
      <SectionHeading
        title={tr("Участия")}
        description={tr(
          "Пауза и досрочное завершение отменят будущие встречи этого участия. Возобновление проверяет доступ участников заново.",
        )}
      />
      <div className="filters">
        <select
          aria-label={tr("Все статусы")}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        >
          <option value="">{tr("Все статусы")}</option>
          {[
            "active",
            "paused",
            "completed_successfully",
            "completed_early",
          ].map((value) => (
            <option key={value} value={value}>
              {status(value)}
            </option>
          ))}
        </select>
        <Button
          variant="secondary"
          onClick={() => {
            void load.reload();
            void reasons.reload();
          }}
        >
          {tr("Обновить")}
        </Button>
      </div>
      <DataState {...load} retry={load.reload}>
        {load.data?.length ? (
          <div className="grid-2">
            {load.data.map((row) => (
              <ParticipationCard
                key={row.id}
                row={row}
                reasons={reasons.data ?? []}
                refresh={load.reload}
              />
            ))}
          </div>
        ) : (
          <NoData />
        )}
        <Pager {...load} hasNext={load.data?.length === 25} />
      </DataState>
    </section>
  );
}

function BookingCard({
  row,
  refresh,
}: {
  row: Booking;
  refresh: () => Promise<void>;
}) {
  const { tr, locale, status } = useActivityLocale();
  const action = useAction();
  const [confirm, setConfirm] = useState(false);
  const future =
    row.status === "scheduled" &&
    new Date(row.starts_at).getTime() > Date.now();
  const url = safeUrl(row.meeting_url);
  return (
    <article className="card stack">
      <div className="row">
        <h3>
          {row.mentee_name} · {row.mentor_name}
        </h3>
        <Badge tone={row.status === "scheduled" ? "blue" : "neutral"}>
          {status(row.status)}
        </Badge>
      </div>
      <p>
        {tr("Начало")}: {dateTime(row.starts_at, locale, row.timezone)}
        <br />
        {tr("Окончание")}: {dateTime(row.ends_at, locale, row.timezone)}
        <br />
        <span className="muted">
          {tr("Часовой пояс встречи")}: {row.timezone}
        </span>
      </p>
      <p className="muted">
        {row.participation_id
          ? `${tr("Идентификатор участия")}: ${row.participation_id}`
          : tr("Участие не привязано")}
      </p>
      {url && (
        <a
          className="text-link"
          href={url}
          target="_blank"
          rel="noopener noreferrer"
        >
          {tr("Открыть ссылку встречи")}
        </a>
      )}
      <Notice action={action} />
      {future && (
        <>
          <p className="muted">
            {tr(
              "Встречу можно отменить только до её начала. Участники получат уведомление.",
            )}
          </p>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={confirm}
              onChange={(e) => setConfirm(e.target.checked)}
            />
            {tr("Подтвердить отмену встречи")}
          </label>
          <Button
            variant="danger"
            disabled={action.busy || !confirm}
            onClick={() =>
              action.run(async () => {
                await mutate(`/bookings/${row.id}/cancel`);
                setConfirm(false);
                await refresh();
              })
            }
          >
            {tr("Отменить будущую встречу")}
          </Button>
        </>
      )}
    </article>
  );
}

function BookingList() {
  const { tr } = useActivityLocale();
  const load = usePaged<Booking>("/bookings");
  return (
    <section className="stack">
      <SectionHeading
        title={tr("Встречи")}
        action={
          <Button variant="secondary" onClick={load.reload}>
            {tr("Обновить")}
          </Button>
        }
      />
      <DataState {...load} retry={load.reload}>
        {load.data?.length ? (
          <div className="grid-2">
            {load.data.map((row) => (
              <BookingCard key={row.id} row={row} refresh={load.reload} />
            ))}
          </div>
        ) : (
          <NoData />
        )}
        <Pager {...load} hasNext={load.data?.length === 25} />
      </DataState>
    </section>
  );
}

export function ActivityAdministration() {
  const { tr } = useActivityLocale();
  return (
    <div className="stack">
      <div className="notice">
        {tr(
          "Успешные результаты проверяются в разделе результатов. Проведение встречи подтверждает её ментор.",
        )}
      </div>
      <ParticipationList />
      <BookingList />
    </div>
  );
}
