"use client";
import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import type { Direction, Project } from "@/lib/types";
import { Button, Field } from "@/components/ui";
import { api } from "@/lib/api";
import { useLocale, translatePhrase as tr } from "@/lib/i18n";
import { ActionNotice, LoadState, mutate, useAction, useLoad } from "./common";
export function ProjectForm({
  project,
  onSaved,
}: {
  project?: Project;
  onSaved?: () => void;
}) {
  const router = useRouter();
  const action = useAction();
  const { t, locale, tr } = useLocale();
  const directions = useLoad(() => api<Direction[]>("/directions"));
  const [draft, setDraft] = useState({
    title: project?.title || "",
    problem: project?.problem || "",
    description: project?.description || "",
    private_details: project?.private_details || "",
    direction_id: project?.direction_id || "",
    stage: project?.stage || "idea",
    required_skills: project?.required_skills.join(", ") || "",
    capacity: project?.capacity ?? 1,
  });
  const update = (key: keyof typeof draft, value: string | number) =>
    setDraft({ ...draft, [key]: value });
  async function submit(event: FormEvent) {
    event.preventDefault();
    await action.run(async () => {
      const saved = await mutate<Project>(
        project ? `/projects/${project.id}` : "/projects",
        {
          ...draft,
          ...(project && !draft.private_details
            ? { private_details: undefined }
            : {}),
          required_skills: draft.required_skills
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
        },
        project ? "PATCH" : "POST",
      );
      if (onSaved) onSaved();
      else router.push(`/projects/${saved.id}`);
    }, tr("Проект сохранён и ожидает модерации"));
  }
  return (
    <LoadState {...directions} retry={directions.reload}>
      <ActionNotice action={action} />
      <form className="form-stack" onSubmit={submit}>
        <Field label={tr("Название проекта")}>
          <input
            minLength={3}
            maxLength={200}
            required
            value={draft.title}
            onChange={(e) => update("title", e.target.value)}
          />
        </Field>
        <div className="form-grid">
          <Field label={tr("Направление")}>
            <select
              required
              value={draft.direction_id}
              onChange={(e) => update("direction_id", e.target.value)}
            >
              <option value="">{tr("Выберите направление")}</option>
              {directions.data?.map((d) => (
                <option key={d.id} value={d.id}>
                  {d[`name_${locale}`]}
                </option>
              ))}
            </select>
          </Field>
          <Field label={tr("Стадия")}>
            <select
              value={draft.stage}
              onChange={(e) => update("stage", e.target.value)}
            >
              <option value="idea">{tr("Идея")}</option>
              <option value="prototype">{tr("Прототип")}</option>
              <option value="mvp">MVP</option>
              <option value="growth">{tr("Развитие")}</option>
            </select>
          </Field>
        </div>
        <Field label={tr("Какую проблему решает проект")}>
          <textarea
            required
            minLength={10}
            maxLength={5000}
            value={draft.problem}
            onChange={(e) => update("problem", e.target.value)}
          />
        </Field>
        <Field
          label={tr("Публичное описание")}
          hint={tr("Видно посетителям после модерации")}
        >
          <textarea
            required
            minLength={20}
            maxLength={10000}
            value={draft.description}
            onChange={(e) => update("description", e.target.value)}
          />
        </Field>
        <Field
          label={tr("Закрытые детали (необязательно)")}
          hint={
            project
              ? tr(
                  "Оставьте пустым, чтобы сохранить текущую закрытую часть, или введите её полную новую редакцию.",
                )
              : tr(
                  "Доступ к этой части проверяется отдельно. Используйте только учебные данные.",
                )
          }
        >
          <textarea
            maxLength={20000}
            value={draft.private_details}
            onChange={(e) => update("private_details", e.target.value)}
          />
        </Field>
        <div className="form-grid">
          <Field label={tr("Нужные навыки")} hint={tr("Через запятую")}>
            <input
              value={draft.required_skills}
              onChange={(e) => update("required_skills", e.target.value)}
            />
          </Field>
          <Field label={tr("Мест в проекте")}>
            <input
              type="number"
              min={1}
              max={50}
              value={draft.capacity}
              onChange={(e) => update("capacity", Number(e.target.value))}
            />
          </Field>
        </div>
        <div className="notice">
          {tr("Новые и изменённые проекты проходят модерацию до публикации.")}
        </div>
        <Button type="submit" disabled={action.busy}>
          {action.busy ? t.loading : tr("Сохранить и отправить на проверку")}
        </Button>
      </form>
    </LoadState>
  );
}
