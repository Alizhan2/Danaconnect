"use client";
import { useLocale, translatePhrase as tr } from "@/lib/i18n";

import { AppShell } from "@/components/shell";
import { Button, EmptyState } from "@/components/ui";
export default function ErrorPage({
  reset,
}: {
  error: Error;
  reset: () => void;
}) {
  const { locale, tr } = useLocale();
  return (
    <AppShell>
      <div className="container section">
        <EmptyState
          title={tr("Не удалось открыть страницу")}
          description={tr(
            "Повторите попытку. Если ошибка сохранится, вернитесь на главную.",
          )}
          action={
            <>
              <Button onClick={reset}>{tr("Повторить")}</Button>
              <Button href="/" variant="ghost">
                {tr("На главную")}
              </Button>
            </>
          }
        />
      </div>
    </AppShell>
  );
}
