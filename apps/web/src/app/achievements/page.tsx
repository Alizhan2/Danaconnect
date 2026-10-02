"use client";
import { useEffect, useState, type FormEvent } from "react";
import { Award, CheckCircle2, LockKeyhole } from "lucide-react";
import { AppShell } from "@/components/shell";
import {
  Badge,
  Button,
  EmptyState,
  Field,
  SectionHeading,
} from "@/components/ui";
import {
  ActionNotice,
  dateTime,
  LoadState,
  mutate,
  safeUrl,
  useAction,
  useLoad,
} from "@/components/workflows/common";
import { PublicLeaderboard } from "@/components/growth/leaderboard";
import type {
  AchievementData,
  Portfolio,
  Preference,
} from "@/components/growth/types";
import { api, errorMessage } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
function LeaderboardConsent({
  preference,
  refresh,
}: {
  preference: Preference;
  refresh: () => Promise<void>;
}) {
  const { tr, t } = useLocale();
  const action = useAction();
  const [alias, setAlias] = useState(preference.alias);
  const [checked, setChecked] = useState(false);
  useEffect(() => {
    setAlias(preference.alias);
    setChecked(false);
  }, [preference]);
  async function save(event: FormEvent) {
    event.preventDefault();
    await action.run(async () => {
      await mutate(
        "/me/leaderboard-preference",
        { visible: true, alias, consent_version: preference.required_version },
        "PUT",
      );
      await refresh();
    }, "Видимость в рейтинге обновлена");
  }
  return (
    <section className="panel stack">
      <SectionHeading
        title={tr("Видимость в рейтинге")}
        description={tr(
          "Ваши достижения доступны вам независимо от участия в публичном рейтинге.",
        )}
      />
      <ActionNotice action={action} />
      <Badge tone={preference.visible ? "success" : "neutral"}>
        {tr(
          preference.visible ? "Публикация включена" : "Публикация отключена",
        )}
      </Badge>
      <form className="form-stack" onSubmit={save}>
        <Field
          label={tr("Отображаемое имя")}
          hint={tr("Выберите псевдоним без контактов и других личных данных.")}
        >
          <input
            minLength={2}
            maxLength={60}
            value={alias}
            required
            onChange={(event) => setAlias(event.target.value)}
          />
        </Field>
        <p className="document-content">{preference.terms}</p>
        <label className="check-row">
          <input
            type="checkbox"
            checked={checked}
            onChange={(event) => setChecked(event.target.checked)}
          />
          {tr("Я прочитал(а) условия и разрешаю эту публикацию")}
        </label>
        <div className="actions">
          <Button type="submit" disabled={action.busy || !checked}>
            {action.busy ? t.loading : tr("Сохранить и включить публикацию")}
          </Button>
          <Button
            variant="secondary"
            disabled={action.busy || !preference.visible}
            onClick={() =>
              action.run(async () => {
                await mutate(
                  "/me/leaderboard-preference",
                  { visible: false, alias },
                  "PUT",
                );
                await refresh();
              }, "Публикация в рейтинге отключена")
            }
          >
            {tr("Отключить публикацию")}
          </Button>
        </div>
      </form>
    </section>
  );
}
export default function AchievementsPage() {
  const { locale, tr } = useLocale();
  const action = useAction();
  const [downloadError, setDownloadError] = useState("");
  const [downloading, setDownloading] = useState("");
  const load = useLoad(async () => {
    const [achievements, portfolio] = await Promise.all([
      api<AchievementData>("/me/achievements"),
      api<Portfolio>("/me/portfolio"),
    ]);
    return { achievements, portfolio };
  }, [locale]);
  async function download(identifier: string) {
    setDownloadError("");
    setDownloading(identifier);
    try {
      const response = await fetch(
        `/api/v1/me/certificates/${identifier}/download`,
        {
          credentials: "include",
          headers: { "Accept-Language": locale },
          signal: AbortSignal.timeout(20000),
        },
      );
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(
          typeof body.detail === "string"
            ? body.detail
            : "Сертификат недоступен",
        );
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `DanaConnect-certificate-${identifier}.pdf`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch (error) {
      setDownloadError(errorMessage(error));
    } finally {
      setDownloading("");
    }
  }
  const labels: Record<string, string> = {
    completed_meeting: "Проведённая встреча",
    verified_result: "Подтверждённый результат",
  };
  return (
    <AppShell
      title={tr("Мои достижения")}
      description={tr(
        "Баллы и значки за реальные записи встреч и подтверждённые результаты.",
      )}
      dashboard
    >
      <LoadState {...load} retry={load.reload}>
        {load.data && (
          <div className="stack">
            <div className="grid-3">
              <article className="card">
                <p>{tr("Баллы")}</p>
                <strong className="stat">
                  {load.data.achievements.points}
                </strong>
              </article>
              <article className="card">
                <p>{tr("Проведённые встречи")}</p>
                <strong className="stat">
                  {load.data.achievements.counts.completed_meeting}
                </strong>
              </article>
              <article className="card">
                <p>{tr("Подтверждённые результаты")}</p>
                <strong className="stat">
                  {load.data.achievements.counts.verified_result}
                </strong>
              </article>
            </div>
            <section className="panel">
              <SectionHeading title={tr("Значки прогресса")} />
              <div className="grid-2">
                {load.data.achievements.badges.map((badge) => (
                  <article className="card" key={badge.code}>
                    <div className="row">
                      <Award size={28} color="var(--blue)" />
                      <Badge tone={badge.earned ? "gold" : "neutral"}>
                        {tr(badge.earned ? "Получено" : "В процессе")}
                      </Badge>
                    </div>
                    <h3 style={{ marginTop: 16 }}>{badge.title}</h3>
                    <p>
                      {badge.progress} / {badge.threshold}
                    </p>
                  </article>
                ))}
              </div>
              <p className="field-hint" style={{ marginTop: 20 }}>
                {tr("Проведённая встреча")}: +
                {load.data.achievements.rules.completed_meeting}.{" "}
                {tr("Подтверждённый результат")}: +
                {load.data.achievements.rules.verified_result}.{" "}
                {tr("Каждая запись учитывается один раз.")}
              </p>
            </section>
            <section className="panel">
              <SectionHeading
                title={tr("Номинации и сертификаты")}
                description={tr(
                  "Выдаются командой платформы. Сертификаты подтверждают результаты, проверенные ментором или администратором.",
                )}
              />
              {downloadError && (
                <div className="error" role="alert">
                  {tr(downloadError)}
                </div>
              )}
              {!load.data.achievements.awards.length ? (
                <EmptyState title={tr("Наград пока нет")} />
              ) : (
                <div className="grid-2">
                  {load.data.achievements.awards.map((award) => (
                    <article className="card stack" key={award.id}>
                      <div className="tags">
                        <Badge tone={award.revoked_at ? "danger" : "gold"}>
                          {tr(
                            award.revoked_at
                              ? "Отозвано"
                              : award.kind === "certificate"
                                ? "Сертификат платформы"
                                : "Номинация",
                          )}
                        </Badge>
                        {award.text_locale !== locale && (
                          <Badge>{tr("Описание доступно на русском")}</Badge>
                        )}
                      </div>
                      <h3 lang={award.text_locale}>{award.title}</h3>
                      <p lang={award.text_locale}>{award.description}</p>
                      <p>{dateTime(award.issued_at, undefined, locale)}</p>
                      {award.revocation_reason && (
                        <p>{award.revocation_reason}</p>
                      )}
                      {award.certificate_available && (
                        <Button
                          variant="secondary"
                          disabled={Boolean(downloading)}
                          onClick={() => download(award.id)}
                        >
                          {tr(
                            downloading === award.id
                              ? "Подготавливаем PDF…"
                              : "Скачать сертификат PDF",
                          )}
                        </Button>
                      )}
                    </article>
                  ))}
                </div>
              )}
            </section>
            <section className="panel">
              <SectionHeading
                title={tr("Моё портфолио")}
                description={tr(
                  "Раздел виден только вам. Публикация проектов в витрине требует отдельных согласий.",
                )}
              />
              {!load.data.portfolio.results.length ? (
                <EmptyState title={tr("Подтверждённых результатов пока нет")} />
              ) : (
                <div className="grid-2">
                  {load.data.portfolio.results.map((result) => (
                    <article className="card stack" key={result.id}>
                      <CheckCircle2 size={23} color="var(--blue)" />
                      <p className="pre-line">{result.summary}</p>
                      <small>
                        {dateTime(result.completed_at, undefined, locale)}
                      </small>
                      {safeUrl(result.artifact_url) && (
                        <a
                          className="text-link"
                          href={safeUrl(result.artifact_url)}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          {tr("Открыть результат")}
                        </a>
                      )}
                    </article>
                  ))}
                </div>
              )}
            </section>
            <LeaderboardConsent
              preference={load.data.achievements.leaderboard_preference}
              refresh={load.reload}
            />
            <PublicLeaderboard />
            <section className="panel">
              <details>
                <summary>{tr("История начислений")}</summary>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>{tr("Событие")}</th>
                        <th>{tr("Баллы")}</th>
                        <th>{tr("Дата")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {load.data.achievements.events.map((event) => (
                        <tr key={event.id}>
                          <td>
                            {tr(labels[event.source_type] || event.source_type)}
                          </td>
                          <td>+{event.points}</td>
                          <td>
                            {dateTime(event.earned_at, undefined, locale)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            </section>
          </div>
        )}
      </LoadState>
    </AppShell>
  );
}
