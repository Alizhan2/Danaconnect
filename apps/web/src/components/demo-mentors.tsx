"use client";

import { useState, type FormEvent } from "react";
import { ArrowLeft, ArrowUpRight, MapPin, Search } from "lucide-react";
import { AppShell } from "@/components/shell";
import { Badge, Button, EmptyState, Field, TextLink } from "@/components/ui";
import { useLocale } from "@/lib/i18n";
import {
  demoDirections,
  demoMentors,
  demoText,
  getDemoDirectionLabel,
  getDemoMentor,
} from "@/lib/demo-mentors";

function DemoNotice() {
  const { locale } = useLocale();
  const text = demoText[locale];
  return (
    <div className="demo-banner">
      <Badge tone="warning">{text.badge}</Badge>
      <p>{text.disclaimer}</p>
      <TextLink href="/catalog">{text.realCatalog}</TextLink>
    </div>
  );
}

function initials(name: string) {
  return name.split("·")[0].trim().split(/\s+/).map((part) => part[0]).slice(0, 2).join("");
}

export function DemoMentorCatalog() {
  const { locale } = useLocale();
  const text = demoText[locale];
  const [q, setQ] = useState("");
  const [direction, setDirection] = useState("");
  const [openOnly, setOpenOnly] = useState(false);
  const query = q.trim().toLocaleLowerCase();
  const mentors = demoMentors.filter((mentor) => {
    if (direction && mentor.direction !== direction) return false;
    if (openOnly && mentor.occupied >= mentor.capacity) return false;
    const searchable = [
      mentor.name,
      ...Object.values(mentor.title),
      ...Object.values(mentor.city),
      ...Object.values(mentor.bio),
      ...Object.values(mentor.expertise).flat(),
    ].join(" ").toLocaleLowerCase();
    return !query || searchable.includes(query);
  });
  function resetFilters() {
    setQ("");
    setDirection("");
    setOpenOnly(false);
  }

  return (
    <AppShell title={text.title} description={text.subtitle}>
      <div className="container page-content">
        <DemoNotice />
        <div className="demo-toolbar">
          <label className="search-box">
            <Search size={18} aria-hidden="true" />
            <input name="q" aria-label={text.searchLabel} placeholder={text.searchPlaceholder} value={q} onChange={(event) => setQ(event.target.value)} />
          </label>
          <label className="demo-label">
            <span>{text.filterLabel}</span>
            <select name="direction" aria-label={text.filterLabel} value={direction} onChange={(event) => setDirection(event.target.value)}>
              <option value="">{text.allDirections}</option>
              {demoDirections.map((item) => <option key={item.id} value={item.id}>{item.label[locale]}</option>)}
            </select>
          </label>
          <label className="demo-checkbox">
            <input type="checkbox" name="openOnly" checked={openOnly} onChange={(event) => setOpenOnly(event.target.checked)} />
            <span>{text.availableOnly}</span>
          </label>
        </div>
        <p className="demo-summary" aria-live="polite">{text.mentorsCount}: {mentors.length}</p>
        {mentors.length ? (
          <div className="mentor-grid">
            {mentors.map((mentor) => {
              const available = Math.max(0, mentor.capacity - mentor.occupied);
              return (
                <article className="mentor-card demo-card" key={mentor.id}>
                  <div className="mentor-card-top">
                    <div className={`avatar demo-avatar-${mentor.direction}`} aria-hidden="true">{initials(mentor.name)}</div>
                    <div>
                      <h3>{mentor.name}</h3>
                      <span className="mentor-meta"><MapPin size={12} aria-hidden="true" />{mentor.city[locale]}</span>
                    </div>
                    <Badge tone="warning">{text.badge}</Badge>
                  </div>
                  <div className="tags"><Badge tone="blue">{getDemoDirectionLabel(mentor.direction, locale)}</Badge></div>
                  <h4>{mentor.title[locale]}</h4>
                  <p>{mentor.bio[locale]}</p>
                  <div className="tags">{mentor.expertise[locale].map((item) => <Badge key={item}>{item}</Badge>)}</div>
                  <dl className="demo-metrics">
                    <div><dt>{text.experience}</dt><dd>{mentor.experienceYears} {text.experienceUnit}</dd></div>
                    <div><dt>{text.availability}</dt><dd>{available} {text.placesSuffix} {mentor.capacity}</dd></div>
                  </dl>
                  <div className="mentor-card-bottom">
                    <Badge tone={available > 0 ? "success" : "neutral"}>{available > 0 ? text.availableOnly : text.full}</Badge>
                    <TextLink href={`/demo/mentors/${mentor.id}`}>{text.profileCta}</TextLink>
                  </div>
                </article>
              );
            })}
          </div>
        ) : <EmptyState title={text.noResults} action={<Button variant="secondary" onClick={resetFilters}>{text.resetFilters}</Button>} />}
      </div>
    </AppShell>
  );
}

export function DemoMentorProfile({ id }: { id: string }) {
  const { locale } = useLocale();
  const text = demoText[locale];
  const [motivation, setMotivation] = useState("");
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState(false);
  const mentor = getDemoMentor(id);
  const available = mentor ? Math.max(0, mentor.capacity - mentor.occupied) : 0;
  const closed = available === 0;

  function submitDemo(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!mentor || closed) return;
    const trimmed = motivation.trim();
    if (trimmed.length < 10 || trimmed.length > 1000) {
      setError(true);
      setSuccess(false);
      return;
    }
    setMotivation(trimmed);
    setError(false);
    setSuccess(true);
  }

  return (
    <AppShell>
      <div className="container page-content demo-profile">
        <DemoNotice />
        <div className="demo-actions"><Button href="/demo/mentors" variant="ghost"><ArrowLeft size={15} />{text.back}</Button></div>
        {!mentor ? <EmptyState title={text.notFound} action={<Button href="/demo/mentors" variant="secondary">{text.back}</Button>} /> : (
          <>
            <div className="profile-hero">
              <div className={`avatar avatar-large demo-avatar-${mentor.direction}`} aria-hidden="true">{initials(mentor.name)}</div>
              <div>
                <Badge tone="warning">{text.badge}</Badge>
                <p className="eyebrow">{text.demoNotice}</p>
                <h1>{mentor.name}</h1>
                <p>{mentor.title[locale]}</p>
                <p><MapPin size={14} aria-hidden="true" /> {mentor.city[locale]}</p>
              </div>
            </div>
            <div className="profile-grid">
              <div className="panel">
                <h2>{text.about}</h2>
                <p>{mentor.bio[locale]}</p>
                <hr className="divider" />
                <h3>{text.expertise}</h3>
                <div className="tags"><Badge tone="blue">{getDemoDirectionLabel(mentor.direction, locale)}</Badge>{mentor.expertise[locale].map((item) => <Badge key={item}>{item}</Badge>)}</div>
                <hr className="divider" />
                <h3>{text.help}</h3>
                <ul className="demo-profile-help">{mentor.help[locale].map((item) => <li key={item}>{item}</li>)}</ul>
              </div>
              <aside className="panel">
                <Badge tone={closed ? "neutral" : "success"}>{closed ? text.full : text.availableOnly}</Badge>
                <dl className="detail-list">
                  <div><dt>{text.experience}</dt><dd>{mentor.experienceYears} {text.experienceUnit}</dd></div>
                  <div><dt>{text.languages}</dt><dd>{mentor.languages.join(" · ")}</dd></div>
                  <div><dt>{text.format}</dt><dd>{mentor.format[locale]}</dd></div>
                  <div><dt>{text.availability}</dt><dd>{available} {text.placesSuffix} {mentor.capacity}</dd></div>
                  <div><dt>{text.occupied}</dt><dd>{mentor.occupied}</dd></div>
                </dl>
                <p className="muted">{text.demoNotice}</p>
                <TextLink href="/catalog">{text.realCatalog}</TextLink>
              </aside>
            </div>
            <section className="panel demo-form" aria-labelledby="demo-application-title">
              <h2 id="demo-application-title">{text.applicationTitle}</h2>
              <p>{text.applicationDescription}</p>
              {closed && <p className="demo-summary" role="status">{text.applicationClosed}</p>}
              {success ? (
                <div role="status" className="demo-success">
                  <h3>{text.applicationSuccess}</h3>
                  <p>{text.applicationSuccessDescription}</p>
                  <p className="pre-line">{motivation}</p>
                  <Button variant="secondary" onClick={() => { setSuccess(false); setMotivation(""); }}>{text.tryAgain}</Button>
                </div>
              ) : (
                <form onSubmit={submitDemo}>
                  <Field label={text.motivationLabel} hint={text.motivationHint}>
                    <textarea name="motivation" aria-describedby={error ? "demo-motivation-error" : undefined} aria-invalid={error} minLength={10} maxLength={1000} required disabled={closed} placeholder={text.motivationPlaceholder} value={motivation} onChange={(event) => { setMotivation(event.target.value); setError(false); }} />
                  </Field>
                  {error && <p id="demo-motivation-error" role="alert">{text.motivationError}</p>}
                  <Button type="submit" disabled={closed}>{text.submitApplication}<ArrowUpRight size={15} /></Button>
                </form>
              )}
            </section>
          </>
        )}
      </div>
    </AppShell>
  );
}
