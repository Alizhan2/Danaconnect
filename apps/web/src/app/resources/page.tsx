"use client";
import { useState } from "react";
import { ArrowUpRight, BookOpen } from "lucide-react";
import { AppShell } from "@/components/shell";
import { Badge, EmptyState } from "@/components/ui";
import { LoadState, safeUrl, useLoad } from "@/components/workflows/common";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import type { Direction } from "@/lib/types";
import type { Material } from "@/components/growth/types";
export default function ResourcesPage() {
  const { locale, tr, t } = useLocale();
  const [direction, setDirection] = useState("");
  const [kind, setKind] = useState("");
  const load = useLoad(async () => {
    const query = new URLSearchParams();
    if (direction) query.set("direction_id", direction);
    if (kind) query.set("kind", kind);
    const [materials, directions] = await Promise.all([
      api<Material[]>(`/materials?${query}`),
      api<Direction[]>("/directions"),
    ]);
    return { materials, directions };
  }, [direction, kind, locale]);
  const kinds: Record<string, string> = {
    article: "Статья",
    video: "Видео",
    course: "Курс",
    guide: "Руководство",
  };
  return (
    <AppShell
      title={tr("Библиотека развития")}
      description={tr(
        "Материалы по направлениям, отобранные командой платформы.",
      )}
    >
      <div className="container page-content">
        <div className="filters">
          <select
            aria-label={tr("Направление")}
            value={direction}
            onChange={(event) => setDirection(event.target.value)}
          >
            <option value="">{t.allDirections}</option>
            {load.data?.directions.map((row) => (
              <option value={row.id} key={row.id}>
                {row[`name_${locale}`]}
              </option>
            ))}
          </select>
          <select
            aria-label={tr("Формат материала")}
            value={kind}
            onChange={(event) => setKind(event.target.value)}
          >
            <option value="">{tr("Все форматы")}</option>
            {Object.entries(kinds).map(([value, label]) => (
              <option value={value} key={value}>
                {tr(label)}
              </option>
            ))}
          </select>
        </div>
        <LoadState {...load} retry={load.reload}>
          {!load.data?.materials.length ? (
            <EmptyState
              title={tr("Материалов пока нет")}
              description={tr(
                "Команда добавит материалы по направлениям. Попробуйте другой фильтр.",
              )}
            />
          ) : (
            <div className="cards-grid">
              {load.data.materials.map((material) => (
                <article className="card stack" key={material.id}>
                  <div className="row">
                    <BookOpen size={25} color="var(--blue)" />
                    <Badge tone="blue">
                      {tr(kinds[material.kind] || material.kind)}
                    </Badge>
                  </div>
                  <h2 lang={material.text_locale}>{material.title}</h2>
                  <p lang={material.text_locale}>{material.description}</p>
                  <div className="tags">
                    <Badge>
                      {tr("Язык источника")}:{" "}
                      {material.content_language
                        .toUpperCase()
                        .replace("KK", "KZ")}
                    </Badge>
                    {material.text_locale !== locale && (
                      <Badge tone="warning">
                        {tr("Описание доступно на русском")}
                      </Badge>
                    )}
                  </div>
                  {safeUrl(material.url) && (
                    <a
                      className="button button-secondary"
                      href={safeUrl(material.url)}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {tr("Открыть материал")}
                      <ArrowUpRight size={16} />
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
