"use client";
import { useState } from "react";
import { useGrowthLocale } from "./locale";
import { formatDateTime } from "@/lib/date-format";
export { useLoad, DataState as LoadState } from "@/components/common";
export { mutate } from "@/lib/api";
export function dateTime(
  value: string,
  timezone = "Asia/Oral",
  locale: "ru" | "kk" | "en" = "ru",
) {
  return formatDateTime(value, timezone, locale);
}
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  async function run(work: () => Promise<unknown>, message = "Сохранено") {
    if (busy) return false;
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      await work();
      setSuccess(message);
      return true;
    } catch (value) {
      setError(
        value instanceof Error
          ? value.message
          : "Произошла ошибка. Повторите попытку.",
      );
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
  const { tr } = useGrowthLocale();
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
