"use client";
import { useLocale } from "@/lib/i18n";

import { api } from "@/lib/api";
import type { User } from "@/lib/types";
import { AppShell } from "@/components/shell";
import { Button } from "@/components/ui";
import { ProjectForm } from "@/components/workflows/project-form";
import { LoadState, useLoad } from "@/components/workflows/common";
export default function NewProjectPage() {
  const { tr } = useLocale();
  const load = useLoad(() => api<User>("/auth/me"));
  return (
    <AppShell title={tr(load.data?.role === "mentee" ? "Предложить идею" : "Новый проект")} dashboard>
      <div className="narrow">
        <LoadState {...load} retry={load.reload}>
          {load.data?.account_status === "active" && ["mentor", "mentee"].includes(load.data.role) ? (
            <div className="panel">
              <p>{tr(load.data.role === "mentee" ? "Опишите идею и желаемую помощь. После публикации менторы смогут предложить поддержку." : "Опишите проект и количество мест. После публикации менти смогут отправить заявки.")}</p>
              <ProjectForm />
            </div>
          ) : load.data?.role === "admin" ? (
            <div className="notice">{tr("Проекты и идеи публикуют менторы и менти.")} <Button href="/forum">{tr("Вернуться на форум")}</Button></div>
          ) : (
            <div className="notice">
              {tr(
                "Создание проекта доступно после проверки анкеты и документов.",
              )}{" "}
              <Button href="/onboarding">{tr("Заполнить профиль")}</Button>
            </div>
          )}
        </LoadState>
      </div>
    </AppShell>
  );
}
