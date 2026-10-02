"use client";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import type { User, Conversation, Message } from "@/lib/types";
import { AppShell } from "@/components/shell";
import { Button, EmptyState, Field } from "@/components/ui";
import { useLocale } from "@/lib/i18n";
import { MessageReportLink, UnreadBadge, UnreadSummaryNotice, VisibleMessageReads, useMessageEngagementLabels, useUnreadSummary } from "@/components/messages-engagement";
import {
  ActionNotice,
  dateTime,
  LoadState,
  mutate,
  useAction,
  useLoad,
} from "@/components/workflows/common";
function Thread({
  conversation,
  user,
  refreshUnread,
}: {
  conversation: Conversation;
  user: User;
  refreshUnread: () => Promise<void>;
}) {
  const { locale, tr } = useLocale();
  const engagementLabel = useMessageEngagementLabels();
  const action = useAction();
  const [body, setBody] = useState("");
  const [offset, setOffset] = useState(0);
  const bottom = useRef<HTMLDivElement>(null);
  const messageList = useRef<HTMLDivElement>(null);
  const load = useLoad(
    () => api<Message[]>(`/conversations/${conversation.id}/messages?limit=50&offset=${offset}`),
    [conversation.id, offset],
  );
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "nearest" });
  }, [load.data]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    await action.run(async () => {
      await mutate(`/conversations/${conversation.id}/messages`, {
        body: body.trim(),
      });
      setBody("");
      if (offset) setOffset(0);
      else await load.reload();
      await refreshUnread();
    }, tr("Сообщение отправлено"));
  }
  return (
    <section className="panel">
      <div className="row">
        <h2>
          {conversation.title || conversation.other_name || tr("Менторство")}
        </h2>
        <Button variant="ghost" onClick={async () => { if (offset) setOffset(0); else await load.reload(); await refreshUnread(); }}>
          {tr("Обновить")}
        </Button>
      </div>
      <LoadState {...load} retry={load.reload}>
        <div
          className="message-list"
          ref={messageList}
          role="log"
          aria-label={tr("Сообщения диалога")}
        >
          {load.data?.length ? (
            load.data.map((message) => (
              <div
                className={`message ${message.sender_id === user.id ? "mine" : ""}`}
                key={message.id}
                data-message-id={message.id}
              >
                <strong>
                  {message.sender_name ||
                    (message.sender_id === user.id ? tr("Вы") : tr("Участник"))}
                </strong>
                <div className="pre-line">{message.body}</div>
                <small>
                  {dateTime(message.created_at, user.timezone, locale)}
                </small>
                {message.sender_id !== user.id && <small><MessageReportLink messageId={message.id}/></small>}
              </div>
            ))
          ) : (
            <p className="muted">
              {offset ? engagementLabel("noOlder") : tr(
                "Начните диалог: расскажите о цели и удобном времени встречи.",
              )}
            </p>
          )}
          <div ref={bottom} />
        </div>
      </LoadState>
      <div className="actions">
        <Button variant="secondary" disabled={load.loading || Boolean(load.error) || load.data?.length !== 50} onClick={() => setOffset(value => value + 50)}>{engagementLabel("older")}</Button>
        <Button variant="secondary" disabled={load.loading || !offset} onClick={() => setOffset(value => Math.max(0, value - 50))}>{engagementLabel("newer")}</Button>
      </div>
      <VisibleMessageReads conversationId={conversation.id} readerId={user.id} messages={load.data} container={messageList}
        ready={!load.loading && !load.error && user.account_status === 'active' && (user.role === 'admin' || user.profile_completed)} onRead={refreshUnread}/>
      <hr className="divider" />
      <ActionNotice action={action} />
      <form className="form-stack" onSubmit={submit}>
        <Field label={tr("Сообщение")}>
          <textarea
            required
            maxLength={5000}
            value={body}
            onChange={(e) => setBody(e.target.value)}
          />
        </Field>
        <Button type="submit" disabled={action.busy || !body.trim()}>
          {tr("Отправить")}
        </Button>
      </form>
    </section>
  );
}
export default function MessagesPage() {
  const { t, locale, tr } = useLocale();
  const [selected, setSelected] = useState("");
  const load = useLoad(async () => {
    const [user, conversations] = await Promise.all([
      api<User>("/auth/me"),
      api<Conversation[]>("/conversations"),
    ]);
    return { user, conversations };
  });
  const conversation =
    load.data?.conversations.find((c) => c.id === selected) ||
    load.data?.conversations[0];
  const currentUser = load.data?.user;
  const eligible = currentUser?.account_status === 'active' && (currentUser.role === 'admin' || currentUser.profile_completed);
  const unread = useUnreadSummary(eligible ? currentUser?.id : undefined);
  const unreadCounts = new Map(unread.summary?.conversations.map(item => [item.id, item.unread_count]));
  return (
    <AppShell
      title={t.messages}
      description={tr("Диалоги создаются при заявке или принятии участия.")}
      dashboard
    >
      <LoadState {...load} retry={load.reload}>
        <UnreadSummaryNotice error={unread.error} retry={unread.refresh}/>
        {unread.summary && <p><UnreadBadge count={unread.summary.total_unread}/></p>}
        {!load.data?.conversations.length ? (
          <EmptyState
            title={tr("Диалогов пока нет")}
            description={tr(
              "Отправьте заявку ментору; после обработки заявки здесь появится разговор.",
            )}
            action={<Button href="/catalog">{t.findMentor}</Button>}
          />
        ) : (
          <div className="profile-grid">
            <section className="panel">
              <h2>{tr("Диалоги")}</h2>
              <div className="stack">
                {load.data.conversations.map((item) => (
                  <Button
                    key={item.id}
                    variant={
                      conversation?.id === item.id ? "primary" : "secondary"
                    }
                    onClick={() => setSelected(item.id)}
                  >
                    {item.title || item.other_name || tr("Менторство")}
                    <UnreadBadge count={unreadCounts.get(item.id) ?? 0}/>
                  </Button>
                ))}
              </div>
            </section>
            {conversation && (
              <Thread
                key={conversation.id}
                conversation={conversation}
                user={load.data.user}
                refreshUnread={unread.refresh}
              />
            )}
          </div>
        )}
      </LoadState>
    </AppShell>
  );
}
