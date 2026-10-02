"use client";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError, errorMessage } from "@/lib/api";
import { useLocale, translatePhrase as tr, type Locale } from "@/lib/i18n";
import { Button } from "@/components/ui";

export function useLoad<T>(loader: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<unknown>();
  const [loading, setLoading] = useState(true);
  const requestVersion = useRef(0);
  const mounted = useRef(true);
  // Each caller owns its loader dependencies; cancellation prevents stale responses replacing newer data.
  const reload = useCallback(async () => {
    const version = ++requestVersion.current;
    setLoading(true);
    setError(undefined);
    try {
      const next = await loader();
      if (mounted.current && version === requestVersion.current) setData(next);
    } catch (value) {
      if (mounted.current && version === requestVersion.current) setError(value);
    } finally {
      if (mounted.current && version === requestVersion.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => {
    mounted.current = true;
    const version = ++requestVersion.current;
    setLoading(true);
    setError(undefined);
    loader()
      .then((value) => {
        if (mounted.current && version === requestVersion.current) setData(value);
      })
      .catch((value) => {
        if (mounted.current && version === requestVersion.current) setError(value);
      })
      .finally(() => {
        if (mounted.current && version === requestVersion.current) setLoading(false);
      });
    return () => {
      mounted.current = false;
      ++requestVersion.current;
    };
  }, deps);
  return { data, error, loading, reload, setData };
}
export function LoadState({
  loading,
  error,
  retry,
  children,
}: {
  loading: boolean;
  error: unknown;
  retry: () => void;
  children: ReactNode;
}) {
  const { t, locale, tr } = useLocale();
  const returnTo =
    typeof window === "undefined"
      ? "/dashboard"
      : safeReturnTo(window.location.pathname + window.location.search);
  if (loading)
    return (
      <div className="loading-state" role="status">
        <div className="spinner" />
        {t.loading}
      </div>
    );
  if (error)
    return (
      <div className="error" role="alert">
        <p>{errorMessage(error)}</p>
        <div className="actions">
          <Button onClick={retry} variant="secondary">
            {t.retry}
          </Button>
          {error instanceof ApiError && error.status === 401 && (
            <Button href={`/login?returnTo=${encodeURIComponent(returnTo)}`}>
              {t.login}
            </Button>
          )}
          {error instanceof ApiError && error.status === 403 && (
            <Button
              href={`/onboarding?returnTo=${encodeURIComponent(returnTo)}`}
            >
              {tr("Проверить профиль и документы")}
            </Button>
          )}
        </div>
      </div>
    );
  return <>{children}</>;
}
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  async function run(work: () => Promise<unknown>, message = tr("Сохранено")) {
    if (busy) return false;
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      await work();
      setSuccess(message);
      return true;
    } catch (value) {
      setError(errorMessage(value));
      return false;
    } finally {
      setBusy(false);
    }
  }
  return {
    busy,
    error,
    success,
    run,
    clear: () => {
      setError("");
      setSuccess("");
    },
  };
}
export function ActionNotice({
  action,
}: {
  action: ReturnType<typeof useAction>;
}) {
  const { tr } = useLocale();
  return (
    <>
      {action.error && (
        <div className="error" role="alert">
          {tr(action.error)}
        </div>
      )}
      {action.success && (
        <div className="success" role="status">
          {tr(action.success)}
        </div>
      )}
    </>
  );
}
export const mutate = <T,>(path: string, body?: unknown, method = "POST") =>
  api<T>(path, {
    method,
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });
const statuses: Record<string, string> = {
  idea: "Идея",
  prototype: "Прототип",
  mvp: "MVP",
  growth: "Развитие",
  suspended: "Заблокирован",
  capacity_full: "Нет свободных мест",
  direction_mismatch: "Не совпадает направление",
  skills_mismatch: "Не подходят навыки",
  insufficient_information: "Недостаточно информации",
  not_a_fit: "Запрос не подходит",
  project_closed: "Проект закрыт",
  goal_achieved: "Цель достигнута",
  lack_time: "Недостаточно времени",
  changed_interests: "Изменились интересы",
  mentorship_mismatch: "Не подошёл формат менторства",
  technical_issue: "Технические трудности",
  personal_circumstances: "Личные обстоятельства",
  other: "Другая причина",
  unchosen: "Роль не выбрана",
  draft: "Черновик",
  pending: "На рассмотрении",
  active: "Активно",
  changes_requested: "Нужны исправления",
  paused: "Приостановлено",
  accepted: "Принята",
  rejected: "Отклонена",
  withdrawn: "Отозвана",
  published: "Опубликован",
  hidden: "Скрыт",
  available: "Свободно",
  booked: "Забронировано",
  scheduled: "Запланировано",
  cancelled: "Отменено",
  completed: "Завершено",
  completed_successfully: "Успешно завершено",
  completed_early: "Досрочно завершено",
  verified: "Подтверждено",
  no_show: "Не состоялось",
  mentor: "Ментор",
  mentee: "Менти",
  admin: "Администратор",
};
export const statusText = (value: string) => statuses[value] ?? value;
export function dateTime(
  value: string,
  timezone = "Asia/Oral",
  locale: Locale = "ru",
) {
  try {
    return new Intl.DateTimeFormat(
      locale === "kk" ? "kk-KZ" : locale === "en" ? "en-GB" : "ru-RU",
      { timeZone: timezone, dateStyle: "medium", timeStyle: "short" },
    ).format(new Date(value));
  } catch {
    return value;
  }
}
export function safeUrl(value?: string | null) {
  if (!value) return undefined;
  try {
    const parsed = new URL(value);
    return ["http:", "https:"].includes(parsed.protocol)
      ? parsed.href
      : undefined;
  } catch {
    return undefined;
  }
}
export function safeReturnTo(value?: string | null) {
  if (
    !value ||
    !value.startsWith("/") ||
    value.startsWith("//") ||
    /[\\\u0000-\u001f]/.test(value)
  )
    return "/dashboard";
  try {
    const base = "https://local.invalid";
    const parsed = new URL(value, base);
    if (
      parsed.origin !== base ||
      parsed.pathname === "/login" ||
      parsed.pathname.startsWith("/api/")
    )
      return "/dashboard";
    return parsed.pathname + parsed.search + parsed.hash;
  } catch {
    return "/dashboard";
  }
}
