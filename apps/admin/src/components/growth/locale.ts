"use client";
import { useLocale } from "@/lib/i18n";
import { growthTranslations } from "./translations";
const common: Record<string, readonly [string, string]> = {
  Направление: ["Бағыт", "Direction"],
  "Сохранить изменения": ["Өзгерістерді сақтау", "Save changes"],
  "Отменить редактирование": ["Өңдеуді болдырмау", "Cancel editing"],
  Опубликован: ["Жарияланды", "Published"],
  Черновик: ["Жоба нұсқасы", "Draft"],
  Редактировать: ["Өңдеу", "Edit"],
  Участник: ["Қатысушы", "Participant"],
  "Network unavailable": [
    "Сервермен байланыс жоқ",
    "Could not reach the server",
  ],
  Сохранено: ["Сақталды", "Saved"],
  "Произошла ошибка. Повторите попытку.": [
    "Қате пайда болды. Қайталап көріңіз.",
    "An error occurred. Try again.",
  ],
};
const phrases = { ...common, ...growthTranslations };
export function useGrowthLocale() {
  const { locale, t } = useLocale();
  return {
    locale,
    t,
    tr: (source: string) => {
      if (source === "Network unavailable") return t("network");
      if (source === "Войдите в аккаунт") return t("sessionExpired");
      if (source === "Доступ разрешён только администратору")
        return t("denied");
      if (/^HTTP \d+$/.test(source)) return t("error");
      return locale === "ru"
        ? source
        : phrases[source]?.[locale === "kk" ? 0 : 1] || source;
    },
  };
}
