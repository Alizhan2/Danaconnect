"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Bell } from "lucide-react";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { Badge, Button, EmptyState, SectionHeading } from "@/components/ui";
import {
  ActionNotice,
  dateTime,
  LoadState,
  mutate,
  useAction,
  useLoad,
} from "@/components/workflows/common";

type Notice = {
  id: string;
  kind: string;
  title: string;
  body: string;
  read_at: string | null;
  created_at: string;
  href: string;
};
type Steps = {
  steps: Array<{
    id: string;
    title: string;
    description: string;
    href: string;
  }>;
  nearest_meeting: {
    id: string;
    starts_at: string;
    ends_at: string;
    timezone: string;
  } | null;
};
const refreshEvent = "danaconnect:notifications-read";

export function NotificationBell({
  userId,
  pathname,
}: {
  userId: string;
  pathname: string;
}) {
  const { tr } = useLocale();
  const load = useLoad(
    () => api<{ unread_count: number }>("/notification-center/summary"),
    [userId, pathname],
  );
  useEffect(() => {
    const refresh = () => void load.reload();
    window.addEventListener(refreshEvent, refresh);
    return () => window.removeEventListener(refreshEvent, refresh);
  }, [load.reload]);
  const count = load.data?.unread_count ?? 0;
  return (
    <Link
      href="/notifications"
      className="icon-button"
      style={{ position: "relative" }}
      aria-label={`${tr("Уведомления")}${count ? ` · ${tr("Непрочитанных")}: ${count}` : ""}`}
    >
      <Bell size={20} />
      {count > 0 && (
        <span
          style={{
            position: "absolute",
            top: -5,
            right: -8,
            borderRadius: 20,
            background: "var(--blue)",
            color: "white",
            fontSize: 10,
            padding: "2px 5px",
            lineHeight: 1.3,
          }}
          aria-hidden="true"
        >
          {count > 99 ? "99+" : count}
        </span>
      )}
    </Link>
  );
}

export function NextStepCards({ timezone }: { timezone: string }) {
  const { tr, locale } = useLocale();
  const load = useLoad(() => api<Steps>("/me/next-steps"));
  return (
    <section className="stack">
      <SectionHeading
        title={tr("Следующие шаги")}
        description={tr(
          "Подсказки основаны на текущем статусе вашего профиля, документах, заявках и встречах.",
        )}
        action={
          <Button onClick={load.reload} variant="secondary">
            {tr("Обновить")}
          </Button>
        }
      />
      <LoadState {...load} retry={load.reload}>
        {load.data?.nearest_meeting && (
          <div className="notice">
            <strong>{tr("Ближайшая встреча")}: </strong>
            {dateTime(load.data.nearest_meeting.starts_at, timezone, locale)}
            <br />
            <span className="muted">
              {tr("Ваш часовой пояс")}: {timezone}
            </span>
          </div>
        )}
        <div className="grid-2">
          {load.data?.steps.map((step) => (
            <article key={step.id} className="card stack">
              <h3>{tr(step.title)}</h3>
              <p className="muted">{tr(step.description)}</p>
              <Button href={step.href} variant="secondary">
                {tr("Перейти к действию")}
              </Button>
            </article>
          ))}
        </div>
      </LoadState>
    </section>
  );
}

export function NotificationFeed({ timezone }: { timezone: string }) {
  const { tr, locale } = useLocale();
  const [unreadOnly, setUnreadOnly] = useState(true);
  const [page, setPage] = useState(0);
  const action = useAction();
  const load = useLoad(async () => {
    const [items, summary] = await Promise.all([
      api<Notice[]>(
        `/notification-center?unread_only=${unreadOnly}&limit=25&offset=${page * 25}`,
      ),
      api<{ unread_count: number }>("/notification-center/summary"),
    ]);
    return { items, ...summary };
  }, [unreadOnly, page]);
  async function mark(id?: string) {
    await action.run(
      async () => {
        await mutate(
          id
            ? `/notification-center/${encodeURIComponent(id)}/read`
            : "/notification-center/read-all",
          undefined,
          id ? "PATCH" : "POST",
        );
        window.dispatchEvent(new Event(refreshEvent));
        if (unreadOnly && page > 0) setPage(0);
        else await load.reload();
      },
      tr(
        id
          ? "Уведомление отмечено прочитанным"
          : "Все текущие уведомления отмечены прочитанными",
      ),
    );
  }
  return (
    <section className="stack">
      <SectionHeading
        title={tr("Уведомления")}
        action={
          <Button onClick={load.reload} variant="secondary">
            {tr("Обновить")}
          </Button>
        }
      />
      <ActionNotice action={action} />
      <div className="filters">
        <Button
          variant={unreadOnly ? "primary" : "secondary"}
          aria-pressed={unreadOnly}
          disabled={action.busy}
          onClick={() => {
            setUnreadOnly(true);
            setPage(0);
            action.clear();
          }}
        >
          {tr("Непрочитанные")}
        </Button>
        <Button
          variant={!unreadOnly ? "primary" : "secondary"}
          aria-pressed={!unreadOnly}
          disabled={action.busy}
          onClick={() => {
            setUnreadOnly(false);
            setPage(0);
            action.clear();
          }}
        >
          {tr("Все уведомления")}
        </Button>
        <Button
          variant="ghost"
          disabled={action.busy || !load.data?.unread_count}
          onClick={() => mark()}
        >
          {tr("Отметить все прочитанными")}
        </Button>
      </div>
      <LoadState {...load} retry={load.reload}>
        <p className="muted">
          {tr("Непрочитанных")}: {load.data?.unread_count ?? 0}
        </p>
        {load.data?.items.length ? (
          <div className="stack">
            {load.data.items.map((item) => (
              <article key={item.id} className="card stack">
                <div className="row">
                  <h3>{tr(item.title)}</h3>
                  <Badge tone={item.read_at ? "neutral" : "blue"}>
                    {tr(item.read_at ? "Прочитано" : "Непрочитанные")}
                  </Badge>
                </div>
                <time dateTime={item.created_at} className="muted">
                  {dateTime(item.created_at, timezone, locale)}
                </time>
                {item.body && (
                  <p
                    style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}
                  >
                    {tr(item.body)}
                  </p>
                )}
                <div className="actions">
                  {item.href !== "/notifications" && (
                    <Button href={item.href} variant="secondary">
                      {tr("Перейти к действию")}
                    </Button>
                  )}
                  {!item.read_at && (
                    <Button
                      variant="ghost"
                      disabled={action.busy}
                      onClick={() => mark(item.id)}
                    >
                      {tr("Отметить прочитанным")}
                    </Button>
                  )}
                </div>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState
            title={tr(
              unreadOnly
                ? "Непрочитанных уведомлений нет"
                : "Уведомлений пока нет",
            )}
            description={tr(
              "Обновления о заявках, встречах и проверке анкеты появятся здесь.",
            )}
          />
        )}
        <nav className="actions" aria-label={tr("Страница")}>
          <Button
            variant="secondary"
            disabled={!page || action.busy}
            onClick={() => setPage(page - 1)}
          >
            {tr("Предыдущая страница")}
          </Button>
          <span>
            {tr("Страница")} {page + 1}
          </span>
          <Button
            variant="secondary"
            disabled={load.data?.items.length !== 25 || action.busy}
            onClick={() => setPage(page + 1)}
          >
            {tr("Следующая страница")}
          </Button>
        </nav>
      </LoadState>
    </section>
  );
}
