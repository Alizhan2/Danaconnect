"use client";
import { useLocale, translatePhrase as tr } from "@/lib/i18n";
import { AppShell } from "@/components/shell";
import { Button, EmptyState } from "@/components/ui";
export default function NotFound() {
  const { locale, tr } = useLocale();
  return (
    <AppShell>
      <div className="container section">
        <EmptyState
          title={tr("Страница не найдена")}
          description={tr("Проверьте адрес или продолжите с главной страницы.")}
          action={<Button href="/">{tr("На главную")}</Button>}
        />
      </div>
    </AppShell>
  );
}
