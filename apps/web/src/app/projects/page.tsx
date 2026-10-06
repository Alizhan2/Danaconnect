"use client";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { Project, Direction, User } from "@/lib/types";
import { AppShell } from "@/components/shell";
import { Badge, Button, EmptyState } from "@/components/ui";
import { useLocale } from "@/lib/i18n";
import { LoadState, statusText, useLoad } from "@/components/workflows/common";
export default function ProjectsPage() {
  const { t, locale, tr } = useLocale();
  const [q, setQ] = useState("");
  const [direction, setDirection] = useState("");
  const [stage, setStage] = useState("");
  const [kind, setKind] = useState("");
  const load = useLoad(async () => {
    const search = new URLSearchParams({
      q,
      ...(direction ? { direction_id: direction } : {}),
      ...(stage ? { stage } : {}),
      ...(kind ? { kind } : {}),
    });
    const [projects, directions, user] = await Promise.all([
      api<Project[]>(`/projects?${search}`),
      api<Direction[]>("/directions"),
      api<User>("/auth/me").catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 401) return null;
        throw error;
      }),
    ]);
    return { projects, directions, user };
  }, [q, direction, stage, kind]);
  const projects = load.data?.projects || [];
  const user = load.data?.user;
  const canCreate = user?.account_status === "active" && ["mentor", "mentee"].includes(user.role);
  return (
    <AppShell
    >
      <div className="container page-content projects-directory">
        <div className="projects-heading">
          <div><p className="eyebrow">{tr("Сообщество")}</p><h1>{tr("Проекты и идеи сообщества")}</h1><p>{tr("Обсуждайте проекты, предлагайте идеи и находите команду для совместной работы.")}</p></div>
          {(!user || ["mentor", "mentee", "unchosen"].includes(user.role)) && <Button href={canCreate ? "/projects/new" : user ? "/onboarding" : "/register"}>{tr(user?.role === "mentee" ? "Предложить идею" : "Создать проект")}</Button>}
        </div>
        <div className="project-kind-filter" role="group" aria-label={tr("Тип публикации")}>
          {[["", "Все проекты и идеи"], ["ideas", "Идеи ищут ментора"], ["projects", "Проекты с ментором"]].map(([value, label]) => <button key={value} type="button" aria-pressed={kind === value} onClick={() => setKind(value)}>{tr(label)}</button>)}
        </div>
        {kind && <p className="project-kind-help">{tr(kind === "ideas" ? "Предложите свою идею. Ментор может предложить поддержку, а автор идеи выбирает наставника." : "Выберите проект, обсудите задачу и отправьте заявку на свободное место.")}</p>}
        <div className="filters">
          <input
            aria-label={tr("Поиск проектов")}
            placeholder={tr("Название или проблема")}
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <select
            aria-label={tr("Направление")}
            value={direction}
            onChange={(e) => setDirection(e.target.value)}
          >
            <option value="">{t.allDirections}</option>
            {load.data?.directions.map((d) => (
              <option key={d.id} value={d.id}>
                {d[`name_${locale}`]}
              </option>
            ))}
          </select>
          <select
            aria-label={tr("Стадия")}
            value={stage}
            onChange={(e) => setStage(e.target.value)}
          >
            <option value="">{tr("Все стадии")}</option>
            <option value="idea">{tr("Идея")}</option>
            <option value="prototype">{tr("Прототип")}</option>
            <option value="mvp">MVP</option>
            <option value="growth">{tr("Развитие")}</option>
          </select>
        </div>
        <LoadState {...load} retry={load.reload}>
          {!projects.length ? (
            <EmptyState
              title={tr("Проекты пока не найдены")}
              description={tr("Измените фильтры или предложите свой проект.")}
            />
          ) : (
            <div className="project-list">
              {projects.map((project) => (
                <article className="project-entry" key={project.id}>
                  <div className="project-entry-main">
                  <div className="tags">
                    <Badge tone="blue">{tr(statusText(project.stage))}</Badge>
                    <Badge>{tr(project.owner_role === "mentee" && !project.mentor_id ? "Идея ищет ментора" : "Проект с ментором")}</Badge>
                    <Badge>
                      {load.data?.directions.find(
                        (d) => d.id === project.direction_id,
                      )?.[`name_${locale}`] || tr("Направление")}
                    </Badge>
                  </div>
                  <h2>{project.title}</h2>
                  <p>{project.problem}</p>
                  {project.owner_name && <p>{tr("Автор:")} {project.owner_name}{project.owner_role && <> · {tr(statusText(project.owner_role))}</>}</p>}
                  {project.mentor_name && <p>{tr("Ментор:")} {project.mentor_name}</p>}
                  <div className="tags">
                    {project.required_skills.map((skill) => (
                      <Badge key={skill}>{skill}</Badge>
                    ))}
                  </div>
                  </div>
                  <div className="project-entry-action"><p>
                    {project.available_places !== undefined ? `${tr("Свободных мест:")} ${project.available_places} / ${project.capacity}` : `${tr("Мест:")} ${project.capacity}`} ·{" "}
                    {tr(statusText(project.visibility_status))}
                  </p>
                  <Button href={`/projects/${project.id}`} variant="secondary">
                    {t.readMore}
                  </Button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </LoadState>
      </div>
    </AppShell>
  );
}
