"use client";
import { useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import type { User, Slot, Booking, Participation, Mentor } from "@/lib/types";
import { AppShell } from "@/components/shell";
import { RecurringAvailability, MeetingControls } from "@/components/calendar-rules";
import { CalendarExport } from "@/components/calendar-export";
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
// Convert a wall-clock datetime in the profile's IANA zone into an instant, including DST validation.
function zonedToUtc(wall: string, timezone: string) {
  const [year, month, day, hour, minute] = wall.split(/[-T:]/).map(Number);
  const target = Date.UTC(year, month - 1, day, hour, minute);
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  });
  let guess = target;
  for (let pass = 0; pass < 4; pass++) {
    const parts = Object.fromEntries(
      formatter.formatToParts(new Date(guess)).map((p) => [p.type, p.value]),
    );
    const represented = Date.UTC(
      Number(parts.year),
      Number(parts.month) - 1,
      Number(parts.day),
      Number(parts.hour),
      Number(parts.minute),
      Number(parts.second),
    );
    const delta = target - represented;
    guess += delta;
    if (!delta) break;
  }
  const parts = Object.fromEntries(
    formatter.formatToParts(new Date(guess)).map((p) => [p.type, p.value]),
  );
  if (
    Number(parts.year) !== year ||
    Number(parts.month) !== month ||
    Number(parts.day) !== day ||
    Number(parts.hour) !== hour ||
    Number(parts.minute) !== minute
  )
    throw new Error(
      tr(
        "Это локальное время не существует из-за перехода часового пояса. Выберите другое время.",
      ),
    );
  return new Date(guess).toISOString();
}
export default function CalendarPage() {
  const { t, locale, tr } = useLocale();
  const action = useAction();
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [mentorFilter, setMentorFilter] = useState("");
  const [participation, setParticipation] = useState("");
  const load = useLoad(async () => {
    const user = await api<User>("/auth/me");
    const [slots, bookings, participations, mentors] = await Promise.all([
      api<Slot[]>(
        `/slots${mentorFilter ? `?mentor_id=${encodeURIComponent(mentorFilter)}` : ""}`,
      ),
      api<Booking[]>("/bookings"),
      api<Participation[]>("/participations"),
      api<Mentor[]>("/mentors"),
    ]);
    return { user, slots, bookings, participations, mentors };
  }, [mentorFilter]);
  const user = load.data?.user;
  async function create(event: FormEvent) {
    event.preventDefault();
    if (!user) return;
    await action.run(async () => {
      const starts_at = zonedToUtc(start, user.timezone),
        ends_at = zonedToUtc(end, user.timezone);
      if (new Date(starts_at) >= new Date(ends_at))
        throw new Error(tr("Время окончания должно быть позже начала."));
      await mutate("/slots", { starts_at, ends_at, timezone: user.timezone });
      setStart("");
      setEnd("");
      await load.reload();
    }, tr("Разовая встреча добавлена"));
  }
  return (
    <AppShell
      title={t.calendar}
      description={tr(
        "Свободные часы менторов и ваши запланированные встречи.",
      )}
      dashboard
    >
      <LoadState {...load} loading={load.loading && !load.data} retry={load.reload}>
        <ActionNotice action={action} />
        {user && (
          <div className="stack">
            <div className="notice">
              {tr("Все даты показаны в вашем часовом поясе:")}{" "}
              <strong>{user.timezone}</strong>
            </div>
            {user.role === "mentor" && (
              <>
              <RecurringAvailability timezone={user.timezone} onChanged={load.reload}/>
              <section className="panel">
                <h2>{tr("Предложить время")}</h2>
                <form onSubmit={create} className="form-grid">
                  <Field label={`${tr("Начало")} · ${user.timezone}`}>
                    <input
                      type="datetime-local"
                      required
                      value={start}
                      onChange={(e) => setStart(e.target.value)}
                    />
                  </Field>
                  <Field label={`${tr("Окончание")} · ${user.timezone}`}>
                    <input
                      type="datetime-local"
                      required
                      value={end}
                      onChange={(e) => setEnd(e.target.value)}
                    />
                  </Field>
                  <Button disabled={action.busy} type="submit">
                    {tr("Добавить встречу")}
                  </Button>
                </form>
              </section>
              </>
            )}
            <section>
              <SectionHeading title={tr("Свободное время")} />
              <div className="filters">
                <select
                  aria-label={tr("Ментор")}
                  value={mentorFilter}
                  onChange={(e) => setMentorFilter(e.target.value)}
                >
                  <option value="">{tr("Все менторы")}</option>
                  {load.data?.mentors.map((mentor) => (
                    <option key={mentor.id} value={mentor.id}>
                      {mentor.full_name}
                    </option>
                  ))}
                </select>
                {user.role === "mentee" && (
                  <select
                    aria-label={tr("Участие для встречи")}
                    value={participation}
                    onChange={(e) => setParticipation(e.target.value)}
                  >
                    <option value="">
                      {tr("Автоматически подобрать активное участие")}
                    </option>
                    {load.data?.participations
                      .filter((p) => p.status === "active")
                      .map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.project_title || p.mentor_name || tr("Менторство")}
                        </option>
                      ))}
                  </select>
                )}
              </div>
              {!load.data?.slots.filter(
                (slot) =>
                  slot.status === "available" &&
                  new Date(slot.starts_at) > new Date(),
              ).length ? (
                <EmptyState
                  title={tr("Свободных часов пока нет")}
                  description={tr(
                    "Менторы смогут предложить время после согласования участия.",
                  )}
                />
              ) : (
                <div className="grid-2">
                  {load.data.slots
                    .filter(
                      (slot) =>
                        slot.status === "available" &&
                        new Date(slot.starts_at) > new Date(),
                    )
                    .map((slot) => (
                      <article className="card" key={slot.id}>
                        <h3>{slot.mentor_name || tr("Ментор")}</h3>
                        <p>
                          {dateTime(slot.starts_at, user.timezone, locale)} —{" "}
                          {dateTime(slot.ends_at, user.timezone, locale)}
                        </p>
                        <Badge tone="success">{tr("Свободно")}</Badge>
                        <div className="actions">
                          {user.role === "mentee" && (
                            <Button
                              disabled={action.busy}
                              onClick={() =>
                                action.run(async () => {
                                  const matching =
                                    load.data?.participations.find(
                                      (p) =>
                                        p.mentor_id === slot.mentor_id &&
                                        p.status === "active",
                                    );
                                  const selected =
                                    participation || matching?.id;
                                  if (!selected)
                                    throw new Error(
                                      tr(
                                        "Для бронирования нужно активное участие у этого ментора. Сначала дождитесь принятия заявки.",
                                      ),
                                    );
                                  const record = load.data?.participations.find(
                                    (p) => p.id === selected,
                                  );
                                  if (record?.mentor_id !== slot.mentor_id)
                                    throw new Error(
                                      tr(
                                        "Выбранное участие относится к другому ментору.",
                                      ),
                                    );
                                  await mutate("/bookings", {
                                    slot_id: slot.id,
                                    participation_id: selected,
                                  });
                                  await load.reload();
                                }, tr("Встреча забронирована"))
                              }
                            >
                              {tr("Забронировать")}
                            </Button>
                          )}
                          {slot.mentor_id === user.id && (
                            <Button
                              variant="secondary"
                              disabled={action.busy}
                              onClick={() =>
                                action.run(async () => {
                                  await mutate(
                                    `/slots/${slot.id}`,
                                    undefined,
                                    "DELETE",
                                  );
                                  await load.reload();
                                }, tr("Свободное время удалено"))
                              }
                            >
                              {tr("Удалить время")}
                            </Button>
                          )}
                        </div>
                      </article>
                    ))}
                </div>
              )}
            </section>
            <section>
              <SectionHeading title={tr("Мои встречи")} />
              <CalendarExport user={user}/>
              {!load.data?.bookings.length ? (
                <EmptyState title={tr("Встреч пока нет")} />
              ) : (
                <div className="grid-2">
                  {load.data.bookings.map((booking) => (
                    <article className="card" key={booking.id}>
                      <div className="row">
                        <h3>
                          {user.role === "mentor"
                            ? booking.mentee_name
                            : booking.mentor_name}
                        </h3>
                        <Badge>{tr(statusText(booking.status))}</Badge>
                      </div>
                      <p>
                        {dateTime(booking.starts_at, user.timezone, locale)} —{" "}
                        {dateTime(booking.ends_at, user.timezone, locale)}
                      </p>
                      {booking.status === "scheduled" && safeUrl(booking.meeting_url) && (
                        <a
                          className="text-link"
                          href={safeUrl(booking.meeting_url)}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          {tr("Подключиться к встрече")}
                        </a>
                      )}
                      {booking.status === "scheduled" && (
                        <div className="actions">
                          <Button
                            variant="secondary"
                            disabled={action.busy || new Date(booking.starts_at) <= new Date()}
                            onClick={() =>
                              action.run(async () => {
                                await mutate(`/bookings/${booking.id}/cancel`);
                                await load.reload();
                              }, tr("Встреча отменена"))
                            }
                          >
                            {tr("Отменить встречу")}
                          </Button>
                          {booking.mentor_id === user.id && (
                            <Button
                              disabled={
                                action.busy ||
                                new Date(booking.ends_at) > new Date()
                              }
                              onClick={() =>
                                action.run(async () => {
                                  await mutate(
                                    `/bookings/${booking.id}/complete`,
                                  );
                                  await load.reload();
                                }, tr("Проведение встречи подтверждено"))
                              }
                            >
                              {tr("Отметить проведённой")}
                            </Button>
                          )}
                        </div>
                      )}
                      <MeetingControls booking={booking} user={user} onChanged={load.reload}/>
                    </article>
                  ))}
                </div>
              )}
            </section>
          </div>
        )}
      </LoadState>
    </AppShell>
  );
}
