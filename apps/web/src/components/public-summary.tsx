"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { publicContent } from "@/lib/public-content";
import { Button } from "./ui";

type Summary = { mentors: number; participants: number; projects: number; demo_mode: boolean };

export function PublicSummary() {
  const { locale } = useLocale();
  const c = publicContent[locale];
  const [summary, setSummary] = useState<Summary | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setState("loading");
    setSummary(null);
    api<Summary>("/public-summary", { signal: controller.signal }).then((value) => {
      if (![value.mentors, value.participants, value.projects].every((n) => Number.isSafeInteger(n) && n >= 0) || typeof value.demo_mode !== "boolean") throw new Error("Invalid summary");
      if (!controller.signal.aborted) { setSummary(value); setState("ready"); }
    }).catch(() => { if (!controller.signal.aborted) setState("error"); });
    return () => controller.abort();
  }, [attempt]);
  return <section className="container wit-summary" aria-label={c.statsTitle}>
    <h2>{c.statsTitle}</h2>
    {summary?.demo_mode && <p className="wit-demo-marker">{c.demoStats}</p>}
    <dl className="wit-summary-grid" aria-busy={state === "loading"}>
      {([ [c.mentors, summary?.mentors], [c.participants, summary?.participants], [c.projectsLabel, summary?.projects] ] as const).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{state === "ready" && value !== undefined ? value.toLocaleString(locale) : "—"}</dd></div>)}
    </dl>
    <div aria-live="polite">{state === "loading" ? <p>{c.loading}</p> : state === "error" ? <div className="wit-summary-error"><p>{c.statsError}</p><Button variant="secondary" onClick={() => setAttempt((n) => n + 1)}>{c.retry}</Button></div> : null}</div>
    <p className="wit-summary-note">{c.statsNote}</p>
  </section>;
}
