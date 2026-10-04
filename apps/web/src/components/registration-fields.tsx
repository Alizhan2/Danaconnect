"use client";
import { useLocale } from "@/lib/i18n";
import type { Direction } from "@/lib/types";
import { evidenceProblem, type RegistrationDraft } from "@/lib/registration";
import { Button, Field } from "./ui";

/** Both the public review and the authenticated form render these same fields. */
export function RegistrationFields({ draft, directions, update, preview = false, reloadDirections, loading = false }: {
  draft: RegistrationDraft;
  directions: readonly Direction[];
  update: (name: keyof RegistrationDraft, value: unknown) => void;
  preview?: boolean;
  reloadDirections: () => void;
  loading?: boolean;
}) {
  const { locale, tr, t } = useLocale();
  const mentor = draft.role === "mentor";
  const evidenceError = mentor ? evidenceProblem(draft.evidence_urls || []) : "";
  const requiredLabel = (label: string) => `${tr(label)} *`;
  return <>
    <p className="field-hint full-width">{tr("* — обязательное поле")}</p>
    <Field label={requiredLabel("ФИО")} hint={tr("Имя, фамилия и отчество, если есть.")}><input name="full_name" required minLength={2} maxLength={160} autoComplete="name" value={draft.full_name} onChange={e => update("full_name", e.target.value)} /></Field>
    <Field label={tr(preview ? "Email — подтверждается при регистрации" : "Подтверждённый email")} hint={tr(preview ? "Сначала подтвердите свою почту одноразовым кодом. Здесь email не собирается." : "Почта подтверждена при входе. Изменить её в анкете нельзя.")}>
      <input name="email" type="email" value={draft.email} readOnly disabled={preview} placeholder={preview ? tr("После подтверждения почты") : undefined} />
    </Field>
    {draft.role === "mentee" && <Field label={requiredLabel("Дата рождения")}><input name="birth_date" type="date" required max={new Date().toISOString().slice(0, 10)} value={draft.birth_date?.slice(0, 10) || ""} onChange={e => update("birth_date", e.target.value)} /></Field>}
    <Field label={mentor ? requiredLabel("Контактный телефон") : tr("Телефон (необязательно)")}><input name="phone" type="tel" required={mentor} maxLength={40} autoComplete="tel" value={draft.phone || ""} onChange={e => update("phone", e.target.value)} /></Field>
    <Field label={`${t.city} *`}><input name="city" required maxLength={120} autoComplete="address-level2" value={draft.city} onChange={e => update("city", e.target.value)} /></Field>
    <Field label={`${t.timezone} *`} hint={tr("Название IANA, например Asia/Oral или Asia/Almaty")}><input name="timezone" required maxLength={100} value={draft.timezone} onChange={e => update("timezone", e.target.value)} /></Field>
    <div className="full-width"><Field label={mentor ? requiredLabel("Текущее место работы или учёбы") : tr("Место учёбы или работы (необязательно)")}><input name="organization" required={mentor} maxLength={300} autoComplete="organization" value={draft.organization || ""} onChange={e => update("organization", e.target.value)} /></Field></div>
    <div className="full-width"><Field label={requiredLabel(mentor ? "Кратко о себе" : "Идея и мотивация участия")}><textarea name="bio" required minLength={10} maxLength={5000} value={draft.bio || ""} onChange={e => update("bio", e.target.value)} /></Field></div>
    {mentor && <>
      <div className="full-width"><Field label={requiredLabel("Профессиональный опыт и экспертиза")}><textarea name="expertise" required minLength={10} maxLength={3000} value={draft.expertise || ""} onChange={e => update("expertise", e.target.value)} /></Field></div>
      <Field label={requiredLabel("Ссылки на опыт")} hint={tr("Ссылки на LinkedIn, GitHub, портфолио или публикации — по одной в строке, до 10. Видны только команде проверки.")}>
        <textarea name="evidence_urls" required placeholder={"https://www.linkedin.com/in/username\nhttps://github.com/username"} aria-invalid={Boolean(evidenceError && draft.evidence_urls?.some(value => value.trim()))} aria-describedby={evidenceError ? "evidence-error" : undefined} value={(draft.evidence_urls || []).join("\n")} onChange={e => {
          const links = e.target.value.split("\n");
          e.currentTarget.setCustomValidity(tr(evidenceProblem(links)));
          update("evidence_urls", links);
        }} />
        {evidenceError && draft.evidence_urls?.some(value => value.trim()) && <span id="evidence-error" className="field-hint">{tr(evidenceError)}</span>}
      </Field>
      <Field label={requiredLabel("Сколько менти готовы вести одновременно")} hint={tr("Например, 3 — до трёх менти одновременно. 0 — свободных мест нет.")}><input name="capacity" type="number" min={0} max={50} required value={draft.capacity ?? ""} onChange={e => update("capacity", e.target.value === "" ? undefined : Number(e.target.value))} /></Field>
    </>}
    <fieldset className="full-width panel"><legend>{requiredLabel("Направления")}</legend>
      {!directions.length ? <div className="notice" role="status"><p>{tr("Направления пока не открыты. Команда платформы готовит список. Вы сможете завершить анкету, когда он появится.")}</p><Button onClick={reloadDirections} disabled={loading} variant="secondary">{tr("Обновить список направлений")}</Button></div> : <p className="field-hint">{tr("Выберите от 1 до 10 доступных направлений.")}</p>}
      <div className="tags">{directions.map(direction => <label className="check-row" key={direction.id}><input name="direction_ids" type="checkbox" checked={draft.direction_ids.includes(direction.id)} onChange={e => update("direction_ids", e.target.checked ? [...draft.direction_ids, direction.id] : draft.direction_ids.filter(id => id !== direction.id))} />{direction[`name_${locale}`]}</label>)}</div>
    </fieldset>
    {mentor && <fieldset className="full-width panel"><legend>{requiredLabel("Готовность к менторству")}</legend><label className="check-row"><input name="mentor_commitment" type="checkbox" required checked={draft.mentor_commitment === true} onChange={e => update("mentor_commitment", e.target.checked)} /><span>{tr("Готов(а) открывать набор и принимать минимум одну группу менти не реже одного раза в 3–6 месяцев.")}</span></label><p className="field-hint">{tr("Это подтверждение готовности. Набор открывается отдельно после одобрения анкеты.")}</p></fieldset>}
  </>;
}
