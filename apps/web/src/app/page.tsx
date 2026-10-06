"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  ArrowUpRight,
  Compass,
  Flag,
  Lightbulb,
} from "lucide-react";
import { AppShell } from "@/components/shell";
import { Button, EmptyState, SectionHeading, TextLink } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { Direction } from "@/lib/types";
import { useLocale } from "@/lib/i18n";
import { publicContent } from "@/lib/public-content";
import { PublicSummary } from "@/components/public-summary";
export default function HomePage() {
  const { t, locale, tr } = useLocale();
  const c = publicContent[locale];
  const [directions, setDirections] = useState<Direction[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  function load() {
    setLoading(true);
    setError("");
    api<Direction[]>("/directions")
      .then(setDirections)
      .catch((e) => setError(errorMessage(e)))
      .finally(() => setLoading(false));
  }
  useEffect(() => {
    load();
  }, []);
  const name = (d: Direction) =>
    locale === "kk" ? d.name_kk : locale === "en" ? d.name_en : d.name_ru;
  return (
    <AppShell>
      <section className="wit-hero">
        <div className="container wit-hero-inner">
          <div className="wit-hero-copy">
            <p className="eyebrow">{c.name}</p>
            <h1>{c.headline}</h1>
            <p className="wit-hero-description">{c.description}</p>
            <div className="wit-hero-actions">
              <Button href="/catalog">{c.findMentor}<ArrowUpRight size={18}/></Button>
              <Button href="/projects" variant="secondary">{c.projects}</Button>
            </div>
          </div>
          <div className="wit-connection-art" aria-hidden="true">
            <svg className="wit-connection-lines" viewBox="0 0 440 440" fill="none">
              <circle cx="220" cy="220" r="178" stroke="#030ba6" strokeOpacity=".12" strokeDasharray="4 9"/>
              <circle cx="220" cy="220" r="108" fill="#fafae6"/>
              <path d="M100 130L326 182L215 330Z" stroke="#030ba6" strokeOpacity=".28" strokeWidth="2"/>
              <path d="M100 130Q120 340 326 182" stroke="#030ba6" strokeOpacity=".12" strokeWidth="2"/>
              <circle cx="65" cy="245" r="9" fill="#e5cf67"/><circle cx="347" cy="305" r="13" fill="#05f2f2"/>
              <circle cx="250" cy="43" r="6" fill="#030ba6"/>
            </svg>
            <div className="wit-network-card wit-network-idea"><Lightbulb size={25}/><span>{c.idea}</span></div>
            <div className="wit-network-card wit-network-mentor"><Compass size={25}/><span>{c.support}</span></div>
            <div className="wit-network-card wit-network-project"><Flag size={25}/><span>{c.result}</span></div>
            <p className="wit-art-caption">{c.connection}</p>
          </div>
        </div>
      </section>
      <PublicSummary />
      <section className="container section wit-home-path">
        <SectionHeading
          eyebrow={`01 / ${tr("Начните путь")}`}
          title={t.path}
          description={t.pathText}
        />
        <div className="steps-grid">
          {[
            [t.step1, t.step1Text],
            [t.step2, t.step2Text],
            [t.step3, t.step3Text],
          ].map(([title, text], i) => (
            <article className="step-card" key={title}>
              <span className="step-number">0{i + 1}</span>
              <h3>{title}</h3>
              <p>{text}</p>
            </article>
          ))}
        </div>
      </section>
      <section className="section section-soft wit-home-directions">
        <div className="container">
          <SectionHeading
            eyebrow={`02 / ${tr("Найдите направление")}`}
            title={t.directions}
            description={t.directionsText}
            action={<TextLink href="/catalog">{t.findMentor}</TextLink>}
          />
          {loading ? (
            <div className="loading-state">
              <div className="spinner" />
              {t.loading}
            </div>
          ) : error ? (
            <EmptyState
              title={
                locale === "ru"
                  ? tr("Направления временно недоступны")
                  : locale === "kk"
                    ? "Бағыттар уақытша қолжетімсіз"
                    : "Directions are temporarily unavailable"
              }
              description={error}
              action={
                <Button onClick={load} variant="secondary">
                  {t.retry}
                </Button>
              }
            />
          ) : directions.length ? (
            <div className="direction-grid">
              {directions.map((d) => (
                <Link
                  href={`/catalog?direction=${d.id}`}
                  className="direction-card"
                  key={d.id}
                >
                  <div className="direction-icon">
                    <Compass size={24} strokeWidth={1.3} />
                    <ArrowUpRight size={17} />
                  </div>
                  <h3>{name(d)}</h3>
                  <p>{locale === "ru" ? d.description_ru : t.directionsText}</p>
                </Link>
              ))}
            </div>
          ) : (
            <EmptyState
              title={
                locale === "ru"
                  ? tr("Направления скоро появятся")
                  : locale === "kk"
                    ? "Бағыттар жақында пайда болады"
                    : "Directions will appear here soon"
              }
            />
          )}
        </div>
      </section>
      <section className="container section wit-home-result">
        <div className="results-panel">
          <div className="results-art" aria-hidden="true">
            <Flag />
          </div>
          <div className="results-copy">
            <p className="eyebrow">03 / {tr("Достигайте результата")}</p>
            <h2>{t.resultsTitle}</h2>
            <p>{t.resultsText}</p>
            <TextLink href="/showcase">{t.resultsLink}</TextLink>
          </div>
        </div>
      </section>
      <section className="container section wit-home-join" style={{ paddingTop: 0 }}>
        <div className="join-panel">
          <div>
            <h2>{t.joinTitle}</h2>
            <p>{t.joinText}</p>
          </div>
          <Button href="/register/mentor" variant="accent">
            {t.becomeMentor}
            <ArrowRight size={16} />
          </Button>
        </div>
      </section>
    </AppShell>
  );
}
