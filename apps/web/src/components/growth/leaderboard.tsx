"use client";
import { useLocale } from "@/lib/i18n";
import { api } from "@/lib/api";
import { Badge, EmptyState, SectionHeading } from "@/components/ui";
import { LoadState, useLoad } from "@/components/workflows/common";
import type { Leaderboard } from "./types";
export function PublicLeaderboard() {
  const { locale, tr } = useLocale();
  const load = useLoad(() => api<Leaderboard>("/leaderboard"), [locale]);
  return (
    <section className="panel">
      <SectionHeading
        title={tr("Рейтинг участников")}
        description={tr(
          "Здесь появляются только участники, которые сами включили публикацию отображаемого имени.",
        )}
      />
      <LoadState {...load} retry={load.reload}>
        {load.data?.demo_mode && (
          <div className="notice">{tr("Учебный пример")}</div>
        )}
        {!load.data?.entries.length ? (
          <EmptyState title={tr("В рейтинге пока нет участников")} />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{tr("Место")}</th>
                  <th>{tr("Отображаемое имя")}</th>
                  <th>{tr("Баллы")}</th>
                  <th>{tr("Значки")}</th>
                </tr>
              </thead>
              <tbody>
                {load.data.entries.map((row) => (
                  <tr key={row.rank}>
                    <td>{row.rank}</td>
                    <td>{row.alias}</td>
                    <td>{row.points}</td>
                    <td>
                      <div className="tags">
                        {row.badges.map((badge) => (
                          <Badge tone="gold" key={badge}>
                            {badge}
                          </Badge>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </LoadState>
    </section>
  );
}
