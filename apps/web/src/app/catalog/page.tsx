"use client";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ArrowUpRight, MapPin, Search } from "lucide-react";
import { AppShell } from "@/components/shell";
import { Badge, Button, EmptyState, TextLink } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { Direction, Mentor } from "@/lib/types";
import { useLocale, translatePhrase as tr } from "@/lib/i18n";
function CatalogContent() {
  const { t, locale, tr } = useLocale();
  const query = useSearchParams();
  const [direction, setDirection] = useState(query.get("direction") || "");
  const [q, setQ] = useState("");
  const [mentors, setMentors] = useState<Mentor[]>([]);
  const [directions, setDirections] = useState<Direction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let live = true;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setLoading(true);
      setError("");
      const params = new URLSearchParams();
      if (direction) params.set("direction_id", direction);
      if (q) params.set("q", q);
      Promise.all([
        api<Mentor[]>(`/mentors?${params}`, { signal: controller.signal }),
        api<Direction[]>("/directions", { signal: controller.signal }),
      ])
        .then(([m, d]) => {
          if (live) {
            setMentors(m);
            setDirections(d);
          }
        })
        .catch((e) => {
          if (live) setError(errorMessage(e));
        })
        .finally(() => {
          if (live) setLoading(false);
        });
    }, 200);
    return () => {
      live = false;
      controller.abort();
      clearTimeout(timer);
    };
  }, [direction, q, revision]);
  const name = (d: Direction) =>
    locale === "kk" ? d.name_kk : locale === "en" ? d.name_en : d.name_ru;
  return (
    <AppShell title={t.catalogTitle} description={t.catalogText}>
      <div className="container page-content">
        <div className="filters">
          <div className="search-box">
            <Search size={18} />
            <input
              aria-label={t.search}
              placeholder={t.search}
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
          <select
            aria-label={t.directions}
            value={direction}
            onChange={(e) => setDirection(e.target.value)}
          >
            <option value="">{t.allDirections}</option>
            {directions.map((d) => (
              <option key={d.id} value={d.id}>
                {name(d)}
              </option>
            ))}
          </select>
        </div>
        {loading ? (
          <div className="loading-state" aria-live="polite">
            <div className="spinner" />
            {t.loading}
          </div>
        ) : error ? (
          <EmptyState
            title={
              locale === "ru"
                ? tr("Не удалось загрузить менторов")
                : locale === "kk"
                  ? "Менторларды жүктеу мүмкін болмады"
                  : "Unable to load mentors"
            }
            description={error}
            action={
              <Button
                variant="secondary"
                onClick={() => setRevision((r) => r + 1)}
              >
                {t.retry}
              </Button>
            }
          />
        ) : mentors.length ? (
          <div className="mentor-grid">
            {mentors.map((m) => (
              <article className="mentor-card" key={m.id}>
                <div className="mentor-card-top">
                  <div className="avatar" aria-hidden="true">
                    {m.full_name
                      .split(" ")
                      .map((n) => n[0])
                      .slice(0, 2)
                      .join("")}
                  </div>
                  <div>
                    <h3>{m.full_name}</h3>
                    <span className="mentor-meta">
                      <MapPin size={12} />
                      {m.city || "—"}
                    </span>
                  </div>
                </div>
                <div className="tags">
                  {directions
                    .filter((d) => m.direction_ids.includes(d.id))
                    .map((d) => (
                      <Badge tone="blue" key={d.id}>
                        {name(d)}
                      </Badge>
                    ))}
                </div>
                <p>{m.expertise || m.bio}</p>
                <div className="mentor-card-bottom">
                  <Badge tone={m.intake_open ? "success" : "neutral"}>
                    {m.intake_open ? t.openIntake : t.closedIntake}
                  </Badge>
                  <TextLink href={`/catalog/${m.id}`}>{t.profile}</TextLink>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState title={t.noMentors} description={t.noMentorsText} />
        )}
      </div>
    </AppShell>
  );
}
export default function CatalogPage() {
  const { locale, tr } = useLocale();
  return (
    <Suspense
      fallback={<div className="loading-state">{tr("Загружаем каталог…")}</div>}
    >
      <CatalogContent />
    </Suspense>
  );
}
