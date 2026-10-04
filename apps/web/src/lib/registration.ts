import type { User } from "./types";

export type ParticipantRole = "mentor" | "mentee";
export type RegistrationDraft = Pick<User, "full_name" | "email" | "timezone" | "city" | "direction_ids" | "phone" | "birth_date" | "bio" | "expertise" | "evidence_urls" | "capacity" | "organization" | "mentor_commitment"> & { role: string };

export function participantRole(value: string | null | undefined): ParticipantRole | undefined {
  return value === "mentor" || value === "mentee" ? value : undefined;
}

/** A link may suggest a role only until the participant has saved a choice. */
export function requestedRole(currentRole: string, suggestion: string | null | undefined): string {
  return currentRole === "unchosen" ? participantRole(suggestion) || currentRole : currentRole;
}

export function onboardingPath(role: string | null | undefined, returnTo: string): string {
  const query = new URLSearchParams({ returnTo });
  const accepted = participantRole(role);
  if (accepted) query.set("role", accepted);
  return `/onboarding?${query.toString()}`;
}

export function emptyRegistration(role: ParticipantRole): RegistrationDraft {
  return { role, email: "", full_name: "", city: "", timezone: "Asia/Almaty", phone: "", birth_date: "", bio: "", expertise: "", organization: "", mentor_commitment: false, evidence_urls: [], direction_ids: [], capacity: 3 };
}

/** Compare the editable values, excluding status, locale and server acceptance time. */
export function registrationValues(draft: RegistrationDraft) {
  return {
    full_name: draft.full_name.trim(), role: draft.role,
    timezone: draft.timezone, city: draft.city.trim(),
    phone: (draft.phone || "").trim(), organization: (draft.organization || "").trim(),
    birth_date: draft.birth_date?.slice(0, 10) || null,
    bio: (draft.bio || "").trim(), expertise: (draft.expertise || "").trim(),
    evidence_urls: (draft.evidence_urls || []).map(value => value.trim()).filter(Boolean).map(value => {
      try { return new URL(value).href; } catch { return value; }
    }),
    direction_ids: [...new Set(draft.direction_ids)].sort(),
    capacity: draft.role === "mentor" ? draft.capacity ?? null : draft.capacity ?? 3,
    mentor_commitment: draft.role === "mentor" && draft.mentor_commitment === true,
  };
}

export function profilePendingChanges(draft: RegistrationDraft, saved: RegistrationDraft): boolean {
  return JSON.stringify(registrationValues(draft)) !== JSON.stringify(registrationValues(saved));
}

export function evidenceProblem(values: string[]): string {
  const links = values.map(value => value.trim()).filter(Boolean);
  if (!links.length) return "Добавьте хотя бы одну ссылку на ваш опыт.";
  if (links.length > 10) return "Можно добавить не более 10 ссылок.";
  for (const link of links) {
    try {
      const url = new URL(link);
      if (!["http:", "https:"].includes(url.protocol) || link.length > 2083)
        return "Укажите полный адрес сайта, например https://github.com/username. Каждая ссылка — с новой строки.";
    } catch {
      return "Укажите полный адрес сайта, например https://github.com/username. Каждая ссылка — с новой строки.";
    }
  }
  return "";
}

export function registrationProblem(draft: RegistrationDraft, availableDirections: readonly { id: string }[]): string {
  if (!participantRole(draft.role)) return "Выберите роль";
  if (draft.full_name.trim().length < 2 || draft.full_name.trim().length > 160) return "Укажите имя и фамилию: от 2 до 160 символов.";
  if (!draft.city.trim() || draft.city.trim().length > 120) return "Укажите город: до 120 символов.";
  try { new Intl.DateTimeFormat("en", { timeZone: draft.timezone }); } catch { return "Выберите действующий часовой пояс IANA."; }
  if (!availableDirections.length) return "Направления пока не открыты. Команда платформы готовит список. Вы сможете завершить анкету, когда он появится.";
  if (!draft.direction_ids.length || draft.direction_ids.length > 10 || draft.direction_ids.some(id => !availableDirections.some(direction => direction.id === id))) return "Выберите от 1 до 10 доступных направлений.";
  if ((draft.bio || "").trim().length < 10 || (draft.bio || "").length > 5000) return "Описание должно содержать от 10 до 5000 символов.";
  if ((draft.organization || "").length > 300) return "Название организации: до 300 символов.";
  if ((draft.phone || "").length > 40) return "Телефон: до 40 символов.";
  if (draft.role === "mentee") {
    const birth = draft.birth_date?.slice(0, 10);
    const date = birth ? new Date(`${birth}T00:00:00Z`) : undefined;
    if (!date || !Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== birth || birth! > new Date().toISOString().slice(0, 10)) return "Укажите действительную дату рождения, не позднее сегодняшнего дня.";
  }
  if (draft.role === "mentor") {
    if (!(draft.phone || "").trim()) return "Для ментора укажите контактный телефон.";
    if (!(draft.organization || "").trim()) return "Для ментора укажите текущее место работы или учёбы.";
    if ((draft.expertise || "").trim().length < 10 || (draft.expertise || "").length > 3000) return "Опишите опыт: от 10 до 3000 символов.";
    const links = evidenceProblem(draft.evidence_urls || []);
    if (links) return links;
    if (!Number.isInteger(draft.capacity) || draft.capacity! < 0 || draft.capacity! > 50) return "Укажите число менти от 0 до 50.";
    if (draft.mentor_commitment !== true) return "Подтвердите готовность открывать набор и принимать минимум одну группу менти не реже одного раза в 3–6 месяцев.";
  }
  return "";
}
