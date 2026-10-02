"use client";
import { useState, type FormEvent } from "react";
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
  useAction,
  useLoad,
} from "./common";
import { api } from "@/lib/api";
import { useGrowthLocale as useLocale } from "./locale";
import type { Direction } from "@/lib/types";
import type { Award, Material } from "./types";
type LocalizedDraft = {
  title_ru: string;
  title_kk: string;
  title_en: string;
  description_ru: string;
  description_kk: string;
  description_en: string;
};
const blankText: LocalizedDraft = {
  title_ru: "",
  title_kk: "",
  title_en: "",
  description_ru: "",
  description_kk: "",
  description_en: "",
};
type MaterialDraft = LocalizedDraft & {
  direction_id: string | null;
  url: string;
  kind: string;
  content_language: string;
  active: boolean;
};
const blankMaterial: MaterialDraft = {
  ...blankText,
  direction_id: null,
  url: "",
  kind: "guide",
  content_language: "ru",
  active: false,
};
function LocalizedFields({
  value,
  onChange,
}: {
  value: LocalizedDraft;
  onChange: (key: keyof LocalizedDraft, value: string) => void;
}) {
  const { tr } = useLocale();
  return (
    <div className="form-grid">
      {(["ru", "kk", "en"] as const).map((locale) => (
        <div className="stack" key={locale}>
          <Field
            label={`${tr("Название")} · ${locale.toUpperCase().replace("KK", "KZ")}`}
          >
            <input
              minLength={locale === "ru" ? 3 : undefined}
              maxLength={220}
              required={locale === "ru"}
              value={value[`title_${locale}`]}
              onChange={(event) =>
                onChange(`title_${locale}`, event.target.value)
              }
            />
          </Field>
          <Field
            label={`${tr("Описание")} · ${locale.toUpperCase().replace("KK", "KZ")}`}
          >
            <textarea
              minLength={locale === "ru" ? 10 : undefined}
              maxLength={5000}
              required={locale === "ru"}
              value={value[`description_${locale}`]}
              onChange={(event) =>
                onChange(`description_${locale}`, event.target.value)
              }
            />
          </Field>
        </div>
      ))}
    </div>
  );
}
export function GrowthAdministration() {
  const { locale, tr } = useLocale();
  const action = useAction();
  const [editing, setEditing] = useState("");
  const [material, setMaterial] = useState<MaterialDraft>(blankMaterial);
  const [recipient, setRecipient] = useState("");
  const [kind, setKind] = useState("certificate");
  const [result, setResult] = useState("");
  const [text, setText] = useState<LocalizedDraft>(blankText);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const load = useLoad(async () => {
    const [materials, awards, directions, users] = await Promise.all([
      api<Material[]>("/admin/materials"),
      api<Award[]>("/admin/awards"),
      api<Direction[]>("/directions"),
      api<{ id: string; full_name: string; role: string }[]>(
        "/admin/growth/users",
      ),
    ]);
    return { materials, awards, directions, users };
  }, [locale]);
  const sources = useLoad(
    () =>
      recipient
        ? api<{ id: string; summary: string }[]>(
            `/admin/growth/results?user_id=${encodeURIComponent(recipient)}`,
          )
        : Promise.resolve([]),
    [recipient],
  );
  function edit(row: Material) {
    setEditing(row.id);
    setMaterial({
      direction_id: row.direction_id,
      url: row.url,
      kind: row.kind,
      content_language: row.content_language,
      active: row.active,
      title_ru: row.title_ru || "",
      title_kk: row.title_kk || "",
      title_en: row.title_en || "",
      description_ru: row.description_ru || "",
      description_kk: row.description_kk || "",
      description_en: row.description_en || "",
    });
    action.clear();
  }
  async function saveMaterial(event: FormEvent) {
    event.preventDefault();
    await action.run(async () => {
      await mutate(
        editing ? `/admin/materials/${editing}` : "/admin/materials",
        material,
        editing ? "PUT" : "POST",
      );
      setMaterial(blankMaterial);
      setEditing("");
      await load.reload();
    }, "Материал сохранён");
  }
  async function saveAward(event: FormEvent) {
    event.preventDefault();
    await action.run(async () => {
      await mutate("/admin/awards", {
        ...text,
        user_id: recipient,
        kind,
        result_id: result || null,
      });
      setText(blankText);
      setResult("");
      await load.reload();
    }, "Награда выдана");
  }
  return (
    <LoadState {...load} retry={load.reload}>
      <div className="stack">
        <ActionNotice action={action} />
        <section className="panel stack">
          <SectionHeading
            title={tr("Учебные материалы")}
            description={tr(
              "Публикуйте проверенные ссылки и описания. Перевод без названия и описания не сохраняется.",
            )}
          />
          <form className="form-stack" onSubmit={saveMaterial}>
            <LocalizedFields
              value={material}
              onChange={(key, value) =>
                setMaterial({ ...material, [key]: value })
              }
            />
            <div className="form-grid">
              <Field label={tr("Направление")}>
                <select
                  value={material.direction_id || ""}
                  onChange={(event) =>
                    setMaterial({
                      ...material,
                      direction_id: event.target.value || null,
                    })
                  }
                >
                  <option value="">{tr("Для всех направлений")}</option>
                  {load.data?.directions.map((direction) => (
                    <option value={direction.id} key={direction.id}>
                      {direction[`name_${locale}`]}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label={tr("Публичная HTTPS-ссылка")}>
                <input
                  type="url"
                  required
                  maxLength={2048}
                  value={material.url}
                  onChange={(event) =>
                    setMaterial({ ...material, url: event.target.value })
                  }
                />
              </Field>
              <Field label={tr("Формат материала")}>
                <select
                  value={material.kind}
                  onChange={(event) =>
                    setMaterial({ ...material, kind: event.target.value })
                  }
                >
                  {[
                    ["guide", "Руководство"],
                    ["article", "Статья"],
                    ["video", "Видео"],
                    ["course", "Курс"],
                  ].map(([value, label]) => (
                    <option key={value} value={value}>
                      {tr(label)}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label={tr("Язык источника")}>
                <select
                  value={material.content_language}
                  onChange={(event) =>
                    setMaterial({
                      ...material,
                      content_language: event.target.value,
                    })
                  }
                >
                  <option value="ru">RU</option>
                  <option value="kk">KZ</option>
                  <option value="en">EN</option>
                </select>
              </Field>
            </div>
            <label className="check-row">
              <input
                type="checkbox"
                checked={material.active}
                onChange={(event) =>
                  setMaterial({ ...material, active: event.target.checked })
                }
              />
              {tr("Опубликовать материал")}
            </label>
            <div className="actions">
              <Button type="submit" disabled={action.busy}>
                {tr(editing ? "Сохранить изменения" : "Добавить материал")}
              </Button>
              {editing && (
                <Button
                  variant="ghost"
                  onClick={() => {
                    setEditing("");
                    setMaterial(blankMaterial);
                  }}
                >
                  {tr("Отменить редактирование")}
                </Button>
              )}
            </div>
          </form>
          {!load.data?.materials.length ? (
            <EmptyState title={tr("Материалов пока нет")} />
          ) : (
            <div className="grid-2">
              {load.data.materials.map((row) => (
                <article className="card" key={row.id}>
                  <Badge tone={row.active ? "success" : "neutral"}>
                    {tr(row.active ? "Опубликован" : "Черновик")}
                  </Badge>
                  <h3>{row.title}</h3>
                  <Button variant="secondary" onClick={() => edit(row)}>
                    {tr("Редактировать")}
                  </Button>
                </article>
              ))}
            </div>
          )}
        </section>
        <section className="panel stack">
          <SectionHeading
            title={tr("Выдача номинаций и сертификатов")}
            description={tr(
              "Сертификат доступен только за подтверждённый результат выбранного участника. Номинации выдаются по решению команды.",
            )}
          />
          <form className="form-stack" onSubmit={saveAward}>
            <div className="form-grid">
              <Field label={tr("Участник")}>
                <select
                  value={recipient}
                  required
                  onChange={(event) => {
                    setRecipient(event.target.value);
                    setResult("");
                  }}
                >
                  <option value="">{tr("Выберите участника")}</option>
                  {load.data?.users.map((user) => (
                    <option value={user.id} key={user.id}>
                      {user.full_name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label={tr("Тип награды")}>
                <select
                  value={kind}
                  onChange={(event) => setKind(event.target.value)}
                >
                  <option value="certificate">
                    {tr("Сертификат платформы")}
                  </option>
                  <option value="nomination">{tr("Номинация")}</option>
                </select>
              </Field>
            </div>
            <LoadState {...sources} retry={sources.reload}>
              <Field label={tr("Подтверждённый результат")}>
                <select
                  required={kind === "certificate"}
                  value={result}
                  onChange={(event) => setResult(event.target.value)}
                >
                  <option value="">{tr("Выберите результат")}</option>
                  {sources.data?.map((row) => (
                    <option key={row.id} value={row.id}>
                      {row.summary.slice(0, 100)}
                    </option>
                  ))}
                </select>
              </Field>
            </LoadState>
            <LocalizedFields
              value={text}
              onChange={(key, value) => setText({ ...text, [key]: value })}
            />
            <Button
              type="submit"
              disabled={
                action.busy || !recipient || (kind === "certificate" && !result)
              }
            >
              {tr("Выдать награду")}
            </Button>
          </form>
          <div className="grid-2">
            {load.data?.awards.map((award) => (
              <article className="card stack" key={award.id}>
                <Badge tone={award.revoked_at ? "danger" : "gold"}>
                  {tr(
                    award.revoked_at
                      ? "Отозвано"
                      : award.kind === "certificate"
                        ? "Сертификат платформы"
                        : "Номинация",
                  )}
                </Badge>
                <h3>{award.title}</h3>
                <p>{award.issued_name}</p>
                <small>{dateTime(award.issued_at, undefined, locale)}</small>
                {!award.revoked_at && (
                  <>
                    <Field label={tr("Причина отзыва награды")}>
                      <textarea
                        value={reasons[award.id] || ""}
                        maxLength={2000}
                        onChange={(event) =>
                          setReasons({
                            ...reasons,
                            [award.id]: event.target.value,
                          })
                        }
                      />
                    </Field>
                    <Button
                      variant="danger"
                      disabled={
                        action.busy ||
                        (reasons[award.id] || "").trim().length < 5
                      }
                      onClick={() =>
                        action.run(async () => {
                          await mutate(`/admin/awards/${award.id}/revoke`, {
                            reason: reasons[award.id],
                          });
                          await load.reload();
                        }, "Награда отозвана")
                      }
                    >
                      {tr("Отозвать награду")}
                    </Button>
                  </>
                )}
              </article>
            ))}
          </div>
        </section>
      </div>
    </LoadState>
  );
}
