"use client";
import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import type { Message } from "@/lib/types";
import { Badge, Button } from "@/components/ui";

export type UnreadSummary = { total_unread: number; conversations: Array<{ id: string; unread_count: number }> };
const phrases: Record<string, [string, string, string]> = {
  unread: ["Непрочитано", "Оқылмаған", "Unread"],
  unavailable: ["Не удалось обновить счётчики сообщений.", "Хабарлама есептегіштерін жаңарту мүмкін болмады.", "Could not refresh message counts."],
  receiptFailed: ["Не удалось сохранить статус прочтения. Сообщения остаются непрочитанными до подтверждения сервера.", "Оқылған күйді сақтау мүмкін болмады. Сервер растағанға дейін хабарламалар оқылмаған болып қалады.", "Could not save read status. Messages remain unread until the server confirms."],
  retry: ["Повторить", "Қайталау", "Retry"],
  report: ["Сообщить о нарушении", "Бұзушылық туралы хабарлау", "Report a problem"],
  older: ["Более ранние сообщения", "Бұрынырақ хабарламалар", "Older messages"],
  newer: ["Более новые сообщения", "Кейінірек хабарламалар", "Newer messages"],
  noOlder: ["Более ранних сообщений нет.", "Бұрынырақ хабарламалар жоқ.", "No older messages."],
};
export function useMessageEngagementLabels() {
  const { locale } = useLocale();
  return (key: string) => phrases[key]?.[locale === "ru" ? 0 : locale === "kk" ? 1 : 2] ?? key;
}

export function UnreadBadge({ count }: { count: number }) {
  const t = useMessageEngagementLabels();
  return count > 0 ? <Badge tone="blue">{t("unread")}: {count}</Badge> : null;
}

export function MessageReportLink({ messageId }: { messageId: string }) {
  const t = useMessageEngagementLabels();
  return <a className="text-link" href={`/support?type=message&entity=${encodeURIComponent(messageId)}`}>{t("report")}</a>;
}

export function useUnreadSummary(userId: string | undefined) {
  const [summary, setSummary] = useState<UnreadSummary>();
  const [error, setError] = useState(false);
  const generation = useRef(0);
  const refresh = useCallback(async () => {
    if (!userId) return;
    const current = ++generation.current;
    try {
      const result = await api<UnreadSummary>("/messages/unread-summary");
      if (generation.current === current) { setSummary(result); setError(false); }
    } catch {
      if (generation.current === current) setError(true);
    }
  }, [userId]);
  useEffect(() => {
    setSummary(undefined); setError(false);
    if (userId) void refresh();
    return () => { generation.current++; };
  }, [userId, refresh]);
  return { summary, error, refresh };
}

export function UnreadSummaryNotice({ error, retry }: { error: boolean; retry: () => Promise<void> }) {
  const t = useMessageEngagementLabels();
  return error ? <div className="notice" role="status"><p>{t("unavailable")}</p><Button variant="secondary" onClick={() => void retry()}>{t("retry")}</Button></div> : null;
}

/** Observe only actually rendered incoming IDs from a successful, matching page. */
export function VisibleMessageReads({ conversationId, readerId, messages, container, ready, onRead }: {
  conversationId: string; readerId: string; messages: Message[] | undefined;
  container: RefObject<HTMLDivElement | null>; ready: boolean; onRead: () => Promise<void>;
}) {
  const t = useMessageEngagementLabels();
  const [failed, setFailed] = useState(false);
  const [retryVersion, setRetryVersion] = useState(0);
  const confirmed = useRef(new Set<string>());
  const sending = useRef(false);
  useEffect(() => {
    if (!ready || !container.current || !messages || typeof IntersectionObserver === "undefined") return;
    const known = new Set(messages.filter(message => message.conversation_id === conversationId && message.sender_id !== readerId).map(message => message.id));
    if (!known.size) return;
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const visible = new Set<string>();
    const pending = new Set<string>();
    let stopped = false;
    function schedule() {
      if (!live || stopped || timer || !pending.size || document.visibilityState !== "visible") return;
      timer = setTimeout(() => { timer = undefined; void flush(); }, 120);
    }
    async function flush() {
      if (!live || stopped || document.visibilityState !== "visible") return;
      if (sending.current) { schedule(); return; }
      const ids = [...pending].filter(id => known.has(id) && !confirmed.current.has(id)).slice(0, 100);
      if (!ids.length) return;
      sending.current = true;
      try {
        await api(`/conversations/${conversationId}/read`, { method: "POST", body: JSON.stringify({ message_ids: ids }) });
        ids.forEach(id => { confirmed.current.add(id); pending.delete(id); });
        if (live) { setFailed(false); await onRead(); }
      } catch {
        stopped = true;
        if (live) setFailed(true);
      } finally {
        sending.current = false;
        if (live) schedule();
      }
    }
    function enqueueVisible() {
      if (document.visibilityState !== "visible") return;
      visible.forEach(id => { if (!confirmed.current.has(id)) pending.add(id); });
      schedule();
    }
    const observer = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        const id = (entry.target as HTMLElement).dataset.messageId;
        if (!id || !known.has(id)) return;
        if (entry.isIntersecting && entry.intersectionRatio > 0) visible.add(id);
        else visible.delete(id);
      });
      enqueueVisible();
    }, { threshold: 0.01 });
    container.current.querySelectorAll<HTMLElement>("[data-message-id]").forEach(node => { if (node.dataset.messageId && known.has(node.dataset.messageId)) observer.observe(node); });
    document.addEventListener("visibilitychange", enqueueVisible);
    return () => { live = false; observer.disconnect(); document.removeEventListener("visibilitychange", enqueueVisible); if (timer) clearTimeout(timer); };
  }, [conversationId, readerId, messages, container, ready, onRead, retryVersion]);
  return failed ? <div className="notice" role="status"><p>{t("receiptFailed")}</p><Button variant="secondary" onClick={() => { setFailed(false); setRetryVersion(value => value + 1); }}>{t("retry")}</Button></div> : null;
}
