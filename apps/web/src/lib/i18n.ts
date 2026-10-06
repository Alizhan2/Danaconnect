"use client";
import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { phraseTranslations } from "./translations";
import { featureTranslations } from "./feature-translations";
export type Locale = "ru" | "kk" | "en";
const ru = {
  mentors: "Менторы",
  projects: "Проекты",
  showcase: "Результаты",
  dashboard: "Мой кабинет",
  calendar: "Встречи",
  messages: "Сообщения",
  admin: "Администрирование",
  login: "Войти",
  join: "Присоединиться",
  community: "Сообщество",
  aboutPlatform: "О платформе",
  getStarted: "Начать",
  demo: "Первая версия · демонстрационные данные",
  demoNote:
    "Среда для знакомства с платформой. Используйте только учебные данные.",
  findMentor: "Найти ментора",
  becomeMentor: "Стать ментором",
  heroEyebrow: "Менторская платформа Women in Tech Kazakhstan & DANA Connect",
  heroTitle: "Превращайте идеи в реальные проекты вместе с менторами",
  heroText:
    "Найдите ментора, присоединитесь к проекту или предложите собственную идею. Women in Tech Kazakhstan и DANA Connect объединяют участников и экспертов и помогают достигать измеримых результатов.",
  path: "Ваш путь на платформе",
  pathText: "От первого знакомства до результата, который можно показать.",
  step1: "Расскажите о себе",
  step1Text:
    "Выберите направление и заполните профиль. Команда проверит заявку.",
  step2: "Найдите своего ментора",
  step2Text: "Изучите опыт, отправьте заявку и обсудите цели вашей работы.",
  step3: "Двигайтесь к результату",
  step3Text: "Планируйте встречи, работайте над проектом и сохраняйте итог.",
  directions: "Выберите своё направление",
  directionsText: "Найдите опыт, который поможет сделать следующий шаг.",
  catalogTitle: "Найдите своего ментора",
  catalogText:
    "Ищите по направлению и опыту. Познакомьтесь с профилем перед отправкой заявки.",
  search: "Поиск по имени или опыту",
  allDirections: "Все направления",
  openIntake: "Набор открыт",
  closedIntake: "Набор закрыт",
  profile: "Посмотреть профиль",
  loading: "Загружаем…",
  retry: "Повторить",
  noMentors: "Менторы пока не найдены",
  noMentorsText: "Попробуйте другой запрос или направление.",
  about: "О менторе",
  expertise: "Экспертиза",
  city: "Город",
  timezone: "Часовой пояс",
  apply: "Отправить заявку",
  applyNote: "Заявки доступны после проверки профиля и согласий.",
  back: "Назад в каталог",
  footer: "Пространство для роста через менторство.",
  footerNote: "Вместе к следующему шагу.",
  joinTitle: "Есть опыт, которым хочется поделиться?",
  joinText:
    "Помогите участницам пройти следующий этап: от идеи и первых решений до готового проекта.",
  explore: "Смотреть проекты",
  readMore: "Подробнее",
  resultsTitle: "Идеи становятся результатами",
  resultsText:
    "Витрина объединит подтверждённые проекты участников, опубликованные с их согласия.",
  resultsLink: "Открыть витрину",
};
const kk: typeof ru = {
  mentors: "Менторлар",
  projects: "Жобалар",
  showcase: "Нәтижелер",
  dashboard: "Жеке кабинет",
  calendar: "Кездесулер",
  messages: "Хабарламалар",
  admin: "Әкімшілік",
  login: "Кіру",
  join: "Қосылу",
  community: "Қауымдастық",
  aboutPlatform: "Платформа туралы",
  getStarted: "Бастау",
  demo: "Алғашқы нұсқа · демонстрациялық деректер",
  demoNote: "Платформамен танысу ортасы. Тек оқу деректерін қолданыңыз.",
  findMentor: "Ментор табу",
  becomeMentor: "Ментор болу",
  heroEyebrow: "Women in Tech Kazakhstan & DANA Connect менторлық платформасы",
  heroTitle: "Идеяларды менторлармен бірге нақты жобаларға айналдырыңыз",
  heroText:
    "Ментор табыңыз, жобаға қосылыңыз немесе өз идеяңызды ұсыныңыз. Women in Tech Kazakhstan мен DANA Connect қатысушылар мен сарапшыларды біріктіріп, өлшенетін нәтижелерге қол жеткізуге көмектеседі.",
  path: "Платформадағы жолыңыз",
  pathText: "Алғашқы танысудан көрсетуге болатын нәтижеге дейін.",
  step1: "Өзіңіз туралы айтыңыз",
  step1Text: "Бағыт таңдап, профиль толтырыңыз. Команда өтінімді тексереді.",
  step2: "Менторыңызды табыңыз",
  step2Text:
    "Тәжірибені зерттеп, өтінім жіберіңіз және мақсаттарды талқылаңыз.",
  step3: "Нәтижеге қарай жүріңіз",
  step3Text: "Кездесу жоспарлап, жобамен жұмыс істеп, қорытындыны сақтаңыз.",
  directions: "Бағытыңызды таңдаңыз",
  directionsText: "Келесі қадамға көмектесетін тәжірибені табыңыз.",
  catalogTitle: "Өз менторыңызды табыңыз",
  catalogText:
    "Бағыт және тәжірибе бойынша іздеңіз. Өтінім жібермес бұрын профильмен танысыңыз.",
  search: "Аты немесе тәжірибесі бойынша іздеу",
  allDirections: "Барлық бағыттар",
  openIntake: "Қабылдау ашық",
  closedIntake: "Қабылдау жабық",
  profile: "Профильді көру",
  loading: "Жүктелуде…",
  retry: "Қайталау",
  noMentors: "Менторлар табылмады",
  noMentorsText: "Басқа сұрауды немесе бағытты таңдаңыз.",
  about: "Ментор туралы",
  expertise: "Сараптама",
  city: "Қала",
  timezone: "Уақыт белдеуі",
  apply: "Өтінім жіберу",
  applyNote:
    "Өтінімдер профиль және келісімдер тексерілгеннен кейін қолжетімді.",
  back: "Каталогқа оралу",
  footer: "Менторлық арқылы даму кеңістігі.",
  footerNote: "Келесі қадамға бірге.",
  joinTitle: "Бөліскіңіз келетін тәжірибе бар ма?",
  joinText:
    "Қатысушыларға идеядан дайын жобаға дейінгі келесі кезеңнен өтуге көмектесіңіз.",
  explore: "Жобаларды көру",
  readMore: "Толығырақ",
  resultsTitle: "Идеялар нәтижеге айналады",
  resultsText:
    "Көрмеде қатысушылардың келісімімен жарияланған расталған жобалар ұсынылады.",
  resultsLink: "Нәтижелерді көру",
};
const en: typeof ru = {
  mentors: "Mentors",
  projects: "Projects",
  showcase: "Outcomes",
  dashboard: "My workspace",
  calendar: "Meetings",
  messages: "Messages",
  admin: "Administration",
  login: "Log In",
  join: "Join",
  community: "Community",
  aboutPlatform: "About",
  getStarted: "Get Started",
  demo: "First release · demonstration data",
  demoNote: "A space to explore the platform. Use sample data only.",
  findMentor: "Find a Mentor",
  becomeMentor: "Become a mentor",
  heroEyebrow: "Women in Tech Kazakhstan & DANA Connect Mentoring Platform",
  heroTitle: "Turn Ideas into Real Projects with the support of Mentors",
  heroText:
    "Find a mentor, join a project or share your own idea. Women in Tech Kazakhstan and DANA Connect connect participants and experts and help them achieve measurable results.",
  path: "Your journey on the platform",
  pathText: "From the first conversation to an outcome you can share.",
  step1: "Tell us about yourself",
  step1Text:
    "Choose a direction and complete your profile. Our team reviews your application.",
  step2: "Find your mentor",
  step2Text:
    "Explore expertise, send a request, and discuss the goals of your work.",
  step3: "Build towards an outcome",
  step3Text:
    "Plan meetings, work on your project, and record what you achieve.",
  directions: "Choose your direction",
  directionsText: "Find the experience to help you take your next step.",
  catalogTitle: "Find your mentor",
  catalogText:
    "Search by direction and expertise. Explore profiles before sending a request.",
  search: "Search by name or expertise",
  allDirections: "All directions",
  openIntake: "Accepting mentees",
  closedIntake: "Intake closed",
  profile: "View profile",
  loading: "Loading…",
  retry: "Try again",
  noMentors: "No mentors found yet",
  noMentorsText: "Try a different search or direction.",
  about: "About the mentor",
  expertise: "Expertise",
  city: "City",
  timezone: "Time zone",
  apply: "Send a request",
  applyNote:
    "Requests are available after your profile and consents have been approved.",
  back: "Back to the catalog",
  footer: "A space for growth through mentorship.",
  footerNote: "Together towards your next step.",
  joinTitle: "Have experience worth sharing?",
  joinText:
    "Help participants take the next step, from an idea and first decisions to a completed project.",
  explore: "Explore Projects",
  readMore: "Learn more",
  resultsTitle: "Ideas become outcomes",
  resultsText:
    "The showcase brings together verified participant projects published with their consent.",
  resultsLink: "Explore outcomes",
};
export const dictionaries = { ru, kk, en };
export function getCurrentLocale(): Locale {
  if (typeof document !== "undefined") {
    const value = document.documentElement.lang;
    if (value === "ru" || value === "kk" || value === "en") return value;
  }
  return "ru";
}
export function translatePhrase(
  source: string,
  locale: Locale = getCurrentLocale(),
): string {
  const canonical = allPhraseTranslations[source] ? source : reversePhrases.get(source) || source;
  const translated = allPhraseTranslations[canonical];
  return locale === "ru" || !translated
    ? canonical
    : translated[locale === "kk" ? 0 : 1];
}
const allPhraseTranslations = {...phraseTranslations,...featureTranslations};
const reversePhrases = new Map(Object.entries(allPhraseTranslations).flatMap(([source, translations]) => translations.map(value => [value, source] as const)));
const LocaleContext = createContext({
  locale: "ru" as Locale,
  setLocale: (_value: Locale) => {},
  t: ru,
  tr: (source: string) => source,
});
export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, updateLocale] = useState<Locale>("ru");
  const setLocale = useCallback((value: Locale) => {
    document.documentElement.lang = value;
    try {
      localStorage.setItem("mentorship.locale", value);
    } catch {}
    updateLocale(value);
  }, []);
  useEffect(() => {
    try {
      const saved = localStorage.getItem("mentorship.locale");
      if (saved === "ru" || saved === "kk" || saved === "en") setLocale(saved);
    } catch {}
  }, [setLocale]);
  const tr = useCallback(
    (source: string) => translatePhrase(source, locale),
    [locale],
  );
  useEffect(() => {
    // Localize the shared title without erasing a route's specific metadata.
    const sharedTitles = Object.values(dictionaries).map((dictionary) => dictionary.heroEyebrow);
    if (sharedTitles.includes(document.title) || document.title === "DanaConnect — Менторство и развитие") {
      document.title = dictionaries[locale].heroEyebrow;
    }
  }, [locale]);
  const value = useMemo(
    () => ({ locale, setLocale, t: dictionaries[locale], tr }),
    [locale, setLocale, tr],
  );
  return createElement(LocaleContext.Provider, { value }, children);
}
export function useLocale() {
  return useContext(LocaleContext);
}
