"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  ArrowUpRight,
  Compass,
  Flag,
  Lightbulb,
  MoveUpRight,
  Sparkles,
} from "lucide-react";
import { AppShell } from "@/components/shell";
import { Button, EmptyState, SectionHeading, TextLink } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { Direction } from "@/lib/types";
import { useLocale, translatePhrase as tr } from "@/lib/i18n";
export default function HomePage() {
  const { t, locale, tr } = useLocale();
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
      <section className="hero">
        <div className="container hero-inner">
          <div className="hero-copy">
            <p className="eyebrow">{t.heroEyebrow}</p>
            <h1>{t.heroTitle}</h1>
            <p>{t.heroText}</p>
            <div className="hero-actions">
              <Button href="/register/mentee" variant="accent">
                {tr("Стать менти")}
                <ArrowUpRight size={16} />
              </Button>
              <Button href="/register/mentor" variant="secondary">
                {t.becomeMentor}
              </Button>
            </div>
            <div className="hero-footnote">
              <Sparkles size={14} />
              {locale === "ru"
                ? "Знакомство начинается с одной беседы"
                : locale === "kk"
                  ? "Танысу бір әңгімеден басталады"
                  : "Every connection starts with a conversation"}
            </div>
          </div>
          <div className="hero-art" aria-hidden="true">
            <div className="orbit" />
            <div className="growth-symbol">↗</div>
            <div className="floating-card">
              <div className="art-icon">
                <Compass size={19} />
              </div>
              <div>
                <strong>
                  {locale === "ru"
                    ? "Новый взгляд"
                    : locale === "kk"
                      ? "Жаңа көзқарас"
                      : "A new perspective"}
                </strong>
                <small>{tr("Исследуйте свои возможности")}</small>
              </div>
            </div>
            <div className="floating-card second">
              <div className="art-icon">
                <Lightbulb size={19} />
              </div>
              <div>
                <strong>
                  {locale === "ru"
                    ? "Ваша следующая идея"
                    : locale === "kk"
                      ? "Сіздің келесі идеяңыз"
                      : "Your next idea"}
                </strong>
                <small>{tr("От идеи к действию")}</small>
              </div>
            </div>
            <span className="art-label">
              {tr("Знакомьтесь · Учитесь · Создавайте")}
            </span>
          </div>
        </div>
      </section>
      <section className="container section">
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
      <section className="section section-soft">
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
              {directions.map((d, i) => (
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
      <section className="container section">
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
      <section className="container section" style={{ paddingTop: 0 }}>
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
