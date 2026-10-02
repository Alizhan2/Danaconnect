"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import type { User, Direction } from "@/lib/types";
import { AppShell } from "@/components/shell";
import { AIMentorRecommendations } from "@/components/ai-assistant";
import { Button, EmptyState, Field } from "@/components/ui";
import { LoadState, useLoad } from "@/components/workflows/common";

export default function RecommendationsPage() {
  const { tr, t, locale } = useLocale();
  const [selected, setSelected] = useState("");
  const load = useLoad(async () => {
    const [user, directions] = await Promise.all([
      api<User>("/auth/me"),
      api<Direction[]>("/directions"),
    ]);
    return {
      user,
      directions: directions.filter((direction) =>
        user.direction_ids.includes(direction.id),
      ),
    };
  });
  const directionId = load.data?.directions.some(
    (direction) => direction.id === selected,
  )
    ? selected
    : (load.data?.directions[0]?.id ?? "");
  const eligible =
    load.data?.user.role === "mentee" &&
    load.data.user.account_status === "active" &&
    load.data.user.profile_completed;
  return (
    <AppShell
      dashboard
      title={tr("Подбор ментора")}
      description={tr(
        "Выберите направление из своей анкеты и опишите цель. Вы сами выбираете ментора и отправляете заявку.",
      )}
    >
      <LoadState {...load} retry={load.reload}>
        <div className="stack">
          {!eligible ? (
            <EmptyState
              title={tr("Подбор доступен менти после одобрения анкеты.")}
              action={
                <Button href="/onboarding">
                  {tr("Проверить профиль и документы")}
                </Button>
              }
            />
          ) : !load.data?.directions.length ? (
            <EmptyState
              title={tr(
                "В вашей анкете пока нет действующих направлений. Обновите профиль.",
              )}
              action={
                <Button href="/onboarding">
                  {tr("Проверить профиль и документы")}
                </Button>
              }
            />
          ) : (
            <>
              <div className="panel">
                <Field label={tr("Направление")}>
                  <select
                    value={directionId}
                    onChange={(event) => setSelected(event.target.value)}
                  >
                    {load.data.directions.map((direction) => (
                      <option key={direction.id} value={direction.id}>
                        {direction[`name_${locale}`] || direction.name_ru}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>
              <AIMentorRecommendations
                key={directionId}
                directionId={directionId}
              />
            </>
          )}
          <div className="actions">
            <Button href="/catalog" variant="secondary">
              {t.mentors}
            </Button>
          </div>
        </div>
      </LoadState>
    </AppShell>
  );
}
