"use client";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Search } from "lucide-react";
import { AppShell } from "@/components/shell";
import { Button, EmptyState } from "@/components/ui";
import { discoveryText, MentorCatalogIntro, MentorPreviewCard } from "@/components/mentor-discovery";
import { api, errorMessage } from "@/lib/api";
import type { Direction, Mentor } from "@/lib/types";
import { useLocale } from "@/lib/i18n";
const demoInvite = {
  ru: { title: "Посмотреть, как выглядит менторство", body: "Демо-каталог: 6 вымышленных менторов, профили и пробная заявка без отправки.", action: "Открыть демо менторов" },
  kk: { title: "Менторлық қалай көрінетінін қараңыз", body: "Демо-каталог: 6 ойдан шығарылған ментор, профильдер және жіберілмейтін сынақ өтінімі.", action: "Менторлар демосын ашу" },
  en: { title: "Explore how mentoring works", body: "Demo catalog: 6 fictional mentors, profiles, and a practice application that is not sent.", action: "Explore demo mentors" },
};
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
  const [openOnly, setOpenOnly] = useState(false);
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
  const c = discoveryText[locale];
  const visibleMentors = openOnly ? mentors.filter(mentor => mentor.intake_open) : mentors;
  const resetFilters = () => { setDirection(""); setQ(""); setOpenOnly(false); };
  return (
    <AppShell>
      <MentorCatalogIntro />
      <div className="container discovery-content">
        <div className="discovery-layout">
        <aside className="discovery-filters" aria-label={c.filters}>
          <h2>{c.filters}</h2>
          <label className="discovery-filter-field"><span>{t.search}</span><span className="search-box">
            <Search size={17} strokeWidth={1.6} aria-hidden="true" />
            <input
              aria-label={t.search}
              placeholder={c.search}
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </span></label>
          <label className="discovery-filter-field"><span>{c.direction}</span>
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
          </label>
          <label className="discovery-checkbox"><input type="checkbox" checked={openOnly} onChange={e => setOpenOnly(e.target.checked)} /><span>{c.openOnly}</span></label>
          {(q || direction || openOnly) && <button type="button" className="discovery-reset" onClick={resetFilters}>{c.reset}</button>}
          <div className="discovery-guide"><h3>{c.guideTitle}</h3><p>{c.guideText}</p></div>
        </aside>
        <section className="discovery-results" aria-label={c.results}>
          <div className="discovery-results-heading"><h2>{c.results}{!loading && !error && <span className="discovery-count" aria-live="polite">{visibleMentors.length}</span>}</h2><p>{c.countNote}</p></div>
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
        ) : visibleMentors.length ? (
          <div className="discovery-grid">
            {visibleMentors.map(m => <MentorPreviewCard key={m.id} name={m.full_name} city={m.city} title={directions.filter(d => m.direction_ids.includes(d.id)).map(name).join(" · ")} topics={directions.filter(d => m.direction_ids.includes(d.id)).map(name)} bio={m.expertise || m.bio} open={m.intake_open} capacity={m.capacity} href={`/catalog/${m.id}`} />)}
          </div>
        ) : (
          <EmptyState title={t.noMentors} description={q || direction || openOnly ? c.noMatches : t.noMentorsText} action={q || direction || openOnly ? <Button variant="secondary" onClick={resetFilters}>{c.reset}</Button> : undefined} />
        )}
        </section></div>
        <section className="discovery-demo-invite" aria-label={demoInvite[locale].title}><div><h2>{demoInvite[locale].title}</h2><p>{demoInvite[locale].body}</p></div><Button href="/demo/mentors" variant="secondary">{demoInvite[locale].action}</Button></section>
      </div>
    </AppShell>
  );
}
export default function CatalogPage() {
  const { tr } = useLocale();
  return (
    <Suspense
      fallback={<div className="loading-state">{tr("Загружаем каталог…")}</div>}
    >
      <CatalogContent />
    </Suspense>
  );
}
