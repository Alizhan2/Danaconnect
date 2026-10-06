"use client";
import { AppShell } from "./shell";
import { Button, TextLink } from "./ui";
import { useLocale } from "@/lib/i18n";
import { publicContent } from "@/lib/public-content";
import { ArrowUpRight, Compass, Lightbulb, Users } from "lucide-react";

export function PublicInfo({ kind }: { kind: "about" | "community" }) {
  const { locale } = useLocale();
  const c = publicContent[locale];
  const about = kind === "about";
  return <AppShell>
    <section className="wit-info-hero"><div className="container">
      <p className="eyebrow">{c.name}</p><h1>{about ? c.about : c.community}</h1>
      <p className="wit-info-lead">{about ? c.aboutIntro : c.communityIntro}</p>
      <p className="wit-info-description">{about ? c.aboutText : c.communityText}</p>
      <Button href="/register">{c.join}<ArrowUpRight size={18}/></Button>
    </div></section>
    <section className="container section">
      {about ? <><h2 className="wit-info-heading">{c.rolesTitle}</h2><div className="wit-role-grid">
        {[{title: c.mentee, text: c.menteeText, href:"/register/mentee", action:c.menteeAction}, {title: c.mentor, text:c.mentorText, href:"/register/mentor", action:c.mentorAction}].map((role) => <article className="wit-info-card" key={role.href}><Users size={28} strokeWidth={1.5}/><h3>{role.title}</h3><p>{role.text}</p><TextLink href={role.href}>{role.action}</TextLink></article>)}
      </div><h2 className="wit-info-heading wit-path-heading">{c.pathTitle}</h2><ol className="wit-path-list">{c.steps.map((step, i) => <li key={step}><span aria-hidden="true">0{i + 1}</span><p>{step}</p></li>)}</ol></> : <div className="wit-community-grid">{c.communityCards.map((card, index) => {
        const Icon = [Compass, Users, Lightbulb][index];
        return <article className="wit-info-card" key={card.href}><Icon size={28} strokeWidth={1.5}/><h2>{card.title}</h2><p>{card.text}</p><TextLink href={card.href}>{card.action}</TextLink></article>;
      })}</div>}
    </section>
    <section className="container section wit-info-results"><div><h2>{c.resultsTitle}</h2><p>{c.resultsText}</p></div><Button href="/showcase" variant="secondary">{c.resultsAction}</Button></section>
  </AppShell>;
}
