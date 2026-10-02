"use client";
import { useLocale, translatePhrase as tr } from "@/lib/i18n";

import { api } from "@/lib/api";
import type { User } from "@/lib/types";
import { AppShell } from "@/components/shell";
import { Button } from "@/components/ui";
import { ProjectForm } from "@/components/workflows/project-form";
import { LoadState, useLoad } from "@/components/workflows/common";
export default function NewProjectPage() {
  const { locale, tr } = useLocale();
  const load = useLoad(() => api<User>("/auth/me"));
  return (
    <AppShell title={tr("Новый проект")} dashboard>
      <div className="narrow">
        <LoadState {...load} retry={load.reload}>
          {load.data?.account_status === "active" ? (
            <div className="panel">
              <ProjectForm />
            </div>
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
