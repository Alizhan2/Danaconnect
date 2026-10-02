"use client";
import { useLocale, translatePhrase as tr } from "@/lib/i18n";
import { api } from "@/lib/api";
import { AppShell } from "@/components/shell";
import { Badge, EmptyState } from "@/components/ui";
import {
  dateTime,
  LoadState,
  safeUrl,
  useLoad,
} from "@/components/workflows/common";
type ShowcaseItem = {
  id: string;
  title: string;
  problem: string;
  description: string;
  stage: string;
  summary: string;
  artifact_url?: string | null;
  meeting_count: number;
  completed_at: string;
  participants: { name: string; role: string }[];
  demo_mode: boolean;
};
export default function ShowcasePage() {
  const { t, locale, tr } = useLocale();
  const load = useLoad(() => api<ShowcaseItem[]>("/showcase"));
  return (
    <AppShell
      title={t.showcase}
      description={tr(
        "Подтверждённые результаты, опубликованные с согласия участников.",
      )}
    >
      <div className="container page-content">
        <LoadState {...load} retry={load.reload}>
          {!load.data?.length ? (
            <EmptyState
              title={tr("Публичных результатов пока нет")}
              description={tr(
                "Проект появится здесь после проверки результата и согласий всех необходимых участников.",
              )}
            />
          ) : (
            <div className="cards-grid">
              {load.data.map((item) => (
                <article className="card stack" key={item.id}>
                  <div className="tags">
                    <Badge tone="success">{tr("Результат подтверждён")}</Badge>
                    {item.demo_mode && (
                      <Badge tone="warning">{tr("Учебный пример")}</Badge>
                    )}
                  </div>
                  <h2>{item.title}</h2>
                  <p>{item.problem}</p>
                  <p className="pre-line">{item.summary}</p>
                  <div className="tags">
                    {item.participants.map((participant, index) => (
                      <Badge key={`${participant.name}-${index}`}>
                        {participant.name}
                      </Badge>
                    ))}
                  </div>
                  <p>
                    {tr("Проведено встреч:")} {item.meeting_count} ·{" "}
                    {dateTime(item.completed_at, undefined, locale)}
                  </p>
                  {safeUrl(item.artifact_url) && (
                    <a
                      className="button button-secondary"
                      target="_blank"
                      rel="noopener noreferrer"
                      href={safeUrl(item.artifact_url)}
                    >
                      {tr("Посмотреть результат")}
                    </a>
                  )}
                </article>
              ))}
            </div>
          )}
        </LoadState>
      </div>
    </AppShell>
  );
}
