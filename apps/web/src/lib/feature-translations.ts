import { collaborationTranslations } from "@/components/collaboration/translations";
import { aiTranslations } from "@/components/ai-assistant/translations";
import { notificationTranslations } from "@/components/notification-center/translations";
import { registrationTranslations } from "./registration-translations";
import { forumTranslations } from "./forum-translations";

export const featureTranslations: Record<string, readonly [string, string]> = {
  ...collaborationTranslations,
  ...aiTranslations,
  ...notificationTranslations,
  ...registrationTranslations,
  ...forumTranslations,
  Команда: ["Команда", "Team"],
  Материалы: ["Материалдар", "Resources"],
  Достижения: ["Жетістіктер", "Achievements"],
  "Отчёт платформы": ["Платформа есебі", "Platform report"],
  "Подбор ментора": ["Менторды таңдау", "Mentor matching"],
  "Выберите направление из своей анкеты и опишите цель. Вы сами выбираете ментора и отправляете заявку.":
    [
      "Сауалнамаңыздағы бағытты таңдап, мақсатыңызды сипаттаңыз. Менторды өзіңіз таңдап, өтініш жібересіз.",
      "Choose a direction from your profile and describe your goal. You choose the mentor and send an application yourself.",
    ],
  "Подбор доступен менти после одобрения анкеты.": [
    "Таңдау сауалнама мақұлданғаннан кейін ментиге қолжетімді.",
    "Matching is available to mentees after their profile is approved.",
  ],
  "В вашей анкете пока нет действующих направлений. Обновите профиль.": [
    "Сауалнамаңызда әзірге белсенді бағыттар жоқ. Профильді жаңартыңыз.",
    "Your profile has no active directions yet. Update your profile.",
  ],
};
