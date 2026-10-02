"use client";
import { use, useEffect, useState } from "react";
import { ArrowLeft, ArrowUpRight, MapPin } from "lucide-react";
import { AppShell } from "@/components/shell";
import { Badge, Button, EmptyState } from "@/components/ui";
import { ReportAction } from "@/components/report-action";
import { api, errorMessage } from "@/lib/api";
import type { Direction, Mentor } from "@/lib/types";
import { useLocale, translatePhrase as tr } from "@/lib/i18n";
export default function MentorPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const { t, locale, tr } = useLocale();
  const [mentor, setMentor] = useState<Mentor | null>(null);
  const [directions, setDirections] = useState<Direction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let live = true;
    setLoading(true);
    Promise.all([
      api<Mentor>(`/mentors/${id}`),
      api<Direction[]>("/directions"),
    ])
      .then(([m, d]) => {
        if (live) {
          setMentor(m);
          setDirections(d);
          setError("");
        }
      })
      .catch((e) => {
        if (live) setError(errorMessage(e));
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [id, revision]);
  return (
    <AppShell>
      <div className="container page-content">
        <div style={{ paddingBlock: 28 }}>
          <Button href="/catalog" variant="ghost">
            <ArrowLeft size={15} />
            {t.back}
          </Button>
        </div>
        {loading ? (
          <div className="loading-state">
            <div className="spinner" />
            {t.loading}
          </div>
        ) : error || !mentor ? (
          <EmptyState
            title={
              locale === "ru"
                ? tr("Профиль недоступен")
                : locale === "kk"
                  ? "Профиль қолжетімсіз"
                  : "Profile unavailable"
            }
            description={error}
            action={
              <Button onClick={() => setRevision((r) => r + 1)}>
                {t.retry}
              </Button>
            }
          />
        ) : (
          <>
            <div className="profile-hero">
              <div className="avatar avatar-large" aria-hidden="true">
                {mentor.full_name
                  .split(" ")
                  .map((n) => n[0])
                  .slice(0, 2)
                  .join("")}
              </div>
              <div>
                <p className="eyebrow" style={{ color: "var(--cyan)" }}>
                  {tr("Профиль ментора")}
                </p>
                <h1>{mentor.full_name}</h1>
                <ReportAction type="mentor" entity={id} />
                <p>
                  <MapPin size={12} /> {mentor.city || "—"}
                </p>
              </div>
            </div>
            <div className="profile-grid">
              <div className="panel">
                <h2>{t.about}</h2>
                <p className="pre-line">{mentor.bio || "—"}</p>
                <hr className="divider" />
                <h3>{t.expertise}</h3>
                <p className="pre-line">{mentor.expertise || "—"}</p>
                <div className="tags">
                  {directions
                    .filter((d) => mentor.direction_ids.includes(d.id))
                    .map((d) => (
                      <Badge tone="blue" key={d.id}>
                        {locale === "kk"
                          ? d.name_kk
                          : locale === "en"
                            ? d.name_en
                            : d.name_ru}
                      </Badge>
                    ))}
                </div>
              </div>
              <aside className="panel">
                <Badge tone={mentor.intake_open ? "success" : "neutral"}>
                  {mentor.intake_open ? t.openIntake : t.closedIntake}
                </Badge>
                <dl className="detail-list">
                  <div>
                    <dt>{t.city}</dt>
                    <dd>{mentor.city || "—"}</dd>
                  </div>
                  <div>
                    <dt>{t.timezone}</dt>
                    <dd>{mentor.timezone}</dd>
                  </div>
                </dl>
                <Button
                  href={`/dashboard?mentor=${mentor.id}`}
                  disabled={!mentor.intake_open}
                >
                  {t.apply}
                  <ArrowUpRight size={15} />
                </Button>
                <p style={{ marginTop: 15, fontSize: 11 }}>{t.applyNote}</p>
              </aside>
            </div>
          </>
        )}
      </div>
    </AppShell>
  );
}
