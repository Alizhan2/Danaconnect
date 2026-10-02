"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import type { Project, Direction } from "@/lib/types";
import { AppShell } from "@/components/shell";
import { Badge, Button, EmptyState, SectionHeading } from "@/components/ui";
import { useLocale, translatePhrase as tr } from "@/lib/i18n";
import { LoadState, statusText, useLoad } from "@/components/workflows/common";
export default function ProjectsPage() {
  const { t, locale, tr } = useLocale();
  const [q, setQ] = useState("");
  const [direction, setDirection] = useState("");
  const [stage, setStage] = useState("");
  const load = useLoad(async () => {
    const search = new URLSearchParams({
      q,
      ...(direction ? { direction_id: direction } : {}),
      ...(stage ? { stage } : {}),
    });
    const [projects, directions] = await Promise.all([
      api<Project[]>(`/projects?${search}`),
      api<Direction[]>("/directions"),
    ]);
    return { projects, directions };
  }, [q, direction, stage]);
  return (
    <AppShell
      title={t.projects}
      description={tr(
        "Найдите задачу, в которой ваш опыт поможет команде двигаться дальше.",
      )}
    >
      <div className="container page-content">
        <SectionHeading
          title={tr("Форум проектов")}
          action={<Button href="/projects/new">{tr("Создать проект")}</Button>}
        />
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
          {!load.data?.projects.length ? (
            <EmptyState
              title={tr("Проекты пока не найдены")}
              description={tr("Измените фильтры или предложите свой проект.")}
            />
          ) : (
            <div className="cards-grid">
              {load.data.projects.map((project) => (
                <article className="card stack" key={project.id}>
                  <div className="tags">
                    <Badge tone="blue">{tr(statusText(project.stage))}</Badge>
                    <Badge>
                      {load.data?.directions.find(
                        (d) => d.id === project.direction_id,
                      )?.[`name_${locale}`] || tr("Направление")}
                    </Badge>
                  </div>
                  <h3>{project.title}</h3>
                  <p>{project.problem}</p>
                  <div className="tags">
                    {project.required_skills.map((skill) => (
                      <Badge key={skill}>{skill}</Badge>
                    ))}
                  </div>
                  <p>
                    {tr("Мест:")} {project.capacity} ·{" "}
                    {tr(statusText(project.visibility_status))}
                  </p>
                  <Button href={`/projects/${project.id}`} variant="secondary">
                    {t.readMore}
                  </Button>
                </article>
              ))}
            </div>
          )}
        </LoadState>
      </div>
    </AppShell>
  );
}
