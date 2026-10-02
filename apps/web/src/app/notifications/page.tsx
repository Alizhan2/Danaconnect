"use client";
import { api } from "@/lib/api";
import type { User } from "@/lib/types";
import { useLocale } from "@/lib/i18n";
import { AppShell } from "@/components/shell";
import { LoadState, useLoad } from "@/components/workflows/common";
import {
  NextStepCards,
  NotificationFeed,
} from "@/components/notification-center";

export default function NotificationsPage() {
  const { tr } = useLocale();
  const load = useLoad(() => api<User>("/auth/me"));
  return (
    <AppShell
      dashboard
      title={tr("Уведомления")}
      description={tr("Важные обновления и действия в одном месте.")}
    >
      <LoadState {...load} retry={load.reload}>
        {load.data && (
          <div className="stack">
            <NextStepCards timezone={load.data.timezone} />
            <NotificationFeed timezone={load.data.timezone} />
          </div>
        )}
      </LoadState>
    </AppShell>
  );
}
