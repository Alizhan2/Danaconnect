"use client";

import { ArrowUpRight, MapPin } from "lucide-react";
import { useLocale } from "@/lib/i18n";
import { Badge, Button } from "./ui";

export const discoveryText = {
  ru: { eyebrow: "Women in Tech Kazakhstan · Менторство", title: "Найдите человека, который поможет двигаться дальше", description: "Выберите направление, познакомьтесь с опытом ментора и обсудите, чего хотите достичь вместе.", stepOne: "Найдите свой фокус", stepTwo: "Изучите опыт", stepThree: "Обсудите цель", filters: "Подбор ментора", results: "Менторы", search: "Имя, опыт или тема", direction: "Направление", all: "Все направления", openOnly: "Открыт набор", reset: "Сбросить фильтры", profile: "Познакомиться", open: "Открыт набор", closed: "Набор закрыт", capacity: "Размер группы", years: "лет опыта", spaces: "Свободные места", location: "Город не указан", help: "С чем поможет", demo: "Демо-профиль", demoLabel: "Демонстрационный каталог", demoTitle: "Познакомьтесь с форматом менторства", demoDescription: "Шесть вымышленных профилей: попробуйте поиск, фильтры и заполнение пробной заявки.", countNote: "По выбранным фильтрам", noMatches: "Попробуйте другое направление или измените запрос.", guideTitle: "Начните с вашей цели", guideText: "Выберите опыт, который поможет вашей задаче. Условия и формат работы можно обсудить с ментором." },
  kk: { eyebrow: "Women in Tech Kazakhstan · Менторлық", title: "Алға жылжуға көмектесетін адамды табыңыз", description: "Бағыт таңдап, ментордың тәжірибесімен танысыңыз және бірге қандай нәтижеге жеткіңіз келетінін талқылаңыз.", stepOne: "Бағытыңызды таңдаңыз", stepTwo: "Тәжірибені зерттеңіз", stepThree: "Мақсатты талқылаңыз", filters: "Менторды таңдау", results: "Менторлар", search: "Аты, тәжірибесі немесе тақырып", direction: "Бағыт", all: "Барлық бағыттар", openOnly: "Қабылдау ашық", reset: "Сүзгілерді тазалау", profile: "Танысу", open: "Қабылдау ашық", closed: "Қабылдау жабық", capacity: "Топ көлемі", years: "жыл тәжірибе", spaces: "Бос орындар", location: "Қала көрсетілмеген", help: "Қандай қолдау көрсетеді", demo: "Демо-профиль", demoLabel: "Демонстрациялық каталог", demoTitle: "Менторлық форматымен танысыңыз", demoDescription: "Алты ойдан шығарылған профиль: іздеу, сүзгілер және сынақ өтінімін толтыруды байқап көріңіз.", countNote: "Таңдалған сүзгілер бойынша", noMatches: "Басқа бағытты таңдаңыз немесе сұрауды өзгертіңіз.", guideTitle: "Мақсатыңыздан бастаңыз", guideText: "Міндетіңізге көмектесетін тәжірибені таңдаңыз. Жұмыс шарттары мен форматын ментормен талқылауға болады." },
  en: { eyebrow: "Women in Tech Kazakhstan · Mentoring", title: "Find someone to help you take the next step", description: "Choose a field, explore a mentor’s experience and discuss what you want to achieve together.", stepOne: "Find your focus", stepTwo: "Explore their experience", stepThree: "Discuss your goal", filters: "Find your mentor", results: "Mentors", search: "Name, experience or topic", direction: "Field", all: "All fields", openOnly: "Accepting mentees", reset: "Clear filters", profile: "Meet the mentor", open: "Accepting mentees", closed: "Intake closed", capacity: "Group capacity", years: "years of experience", spaces: "Available places", location: "City not specified", help: "How they can help", demo: "Demo profile", demoLabel: "Demonstration catalogue", demoTitle: "Explore the mentoring experience", demoDescription: "Six fictional profiles: try the search, filters and practice application.", countNote: "Matching your filters", noMatches: "Try another field or change your search.", guideTitle: "Start with your goal", guideText: "Choose experience that fits your task. Discuss the working arrangements and format with your mentor." },
};

export function MentorCatalogIntro({ demo = false }: { demo?: boolean }) {
  const { locale } = useLocale();
  const c = discoveryText[locale];
  return <section className="discovery-intro">
    <div className="container discovery-intro-inner">
      <div className="discovery-intro-copy">
        <p className="eyebrow">{demo ? c.demoLabel : c.eyebrow}</p>
        <h1>{demo ? c.demoTitle : c.title}</h1>
        <p className="discovery-lead">{demo ? c.demoDescription : c.description}</p>
      </div>
      <ol className="discovery-steps" aria-label={c.filters}>
        {[c.stepOne, c.stepTwo, c.stepThree].map((step, index) => <li key={step}><span aria-hidden="true">0{index + 1}</span>{step}</li>)}
      </ol>
    </div>
  </section>;
}

export function MentorDirectionFilter({ options, value, onChange, label, allLabel }: {
  options: { id: string; label: string }[]; value: string; onChange: (value: string) => void; label: string; allLabel: string;
}) {
  return <div className="discovery-direction-filter" role="group" aria-label={label}>
    {[{ id: "", label: allLabel }, ...options].map(option => <button key={option.id} type="button" data-direction={option.id} aria-pressed={value === option.id} onClick={() => onChange(option.id)}>{option.label}</button>)}
  </div>;
}

export function MentorPreviewCard({ name, city, title, bio, topics, open, href, demo = false, experience, capacity, available, languages }: {
  name: string; city: string; title: string; bio: string; topics: string[]; open: boolean; href: string;
  demo?: boolean; experience?: number; capacity?: number; available?: number; languages?: string[];
}) {
  const { locale } = useLocale();
  const c = discoveryText[locale];
  const initials = name.split("·")[0].trim().split(/\s+/).map(part => part[0]).slice(0, 2).join("");
  return <article className={`discovery-card${demo ? " discovery-card-demo" : ""}`}>
    <div className="discovery-card-status">
      <span className={`discovery-status${open ? " discovery-status-open" : ""}`}><span aria-hidden="true" />{open ? c.open : c.closed}</span>
      {demo && <Badge tone="warning">{c.demo}</Badge>}
    </div>
    <div className="discovery-person">
      <div className="discovery-avatar" aria-hidden="true">{initials}</div>
      <div className="discovery-person-copy"><h3>{name}</h3>{title && <p>{title}</p>}<span className="discovery-location"><MapPin size={14} strokeWidth={1.6} aria-hidden="true" />{city || c.location}</span></div>
    </div>
    <div className="discovery-card-body"><p>{bio}</p></div>
    <div className="discovery-topics">{[...new Set(topics)].map(topic => <span key={topic}>{topic}</span>)}</div>
    {(experience !== undefined || capacity !== undefined || !!languages?.length) && <dl className="discovery-details">
      {experience !== undefined && <div><dt>{c.years}</dt><dd>{experience}</dd></div>}
      {capacity !== undefined && <div><dt>{available !== undefined ? c.spaces : c.capacity}</dt><dd>{available !== undefined ? `${available} / ${capacity}` : capacity}</dd></div>}
      {!!languages?.length && <div><dt>{locale === "kk" ? "Тілдер" : locale === "en" ? "Languages" : "Языки"}</dt><dd>{languages.join(" · ")}</dd></div>}
    </dl>}
    <Button href={href} variant="secondary" className="discovery-profile-button">{c.profile}<ArrowUpRight size={17} strokeWidth={1.6} aria-hidden="true" /></Button>
  </article>;
}
