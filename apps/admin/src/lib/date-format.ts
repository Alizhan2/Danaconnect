export type DateLocale = "ru" | "kk" | "en";

// Keep both apps' lib/date-format.ts files in sync. The two independently
// built services cannot import files outside their Turbopack roots.
const months: Record<DateLocale, readonly string[]> = {
  ru: ["янв.", "февр.", "мар.", "апр.", "мая", "июн.", "июл.", "авг.", "сент.", "окт.", "нояб.", "дек."],
  kk: ["қаң.", "ақп.", "нау.", "сәу.", "мам.", "мау.", "шіл.", "там.", "қыр.", "қаз.", "қар.", "жел."],
  en: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sept", "Oct", "Nov", "Dec"],
};
const formatters = new Map<string, Intl.DateTimeFormat>();

function partsInZone(value: string, timezone: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) throw new RangeError("Invalid date");
  let formatter = formatters.get(timezone);
  if (!formatter) {
    // Numeric Gregorian parts work even when a runtime lacks Kazakh locale data.
    // Intl continues to calculate IANA offsets and daylight saving transitions.
    formatter = new Intl.DateTimeFormat("en-GB-u-ca-gregory-nu-latn", {
      timeZone: timezone,
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hourCycle: "h23",
    });
    if (formatters.size >= 32) formatters.delete(formatters.keys().next().value!);
    formatters.set(timezone, formatter);
  }
  return Object.fromEntries(formatter.formatToParts(date).map(part => [part.type, part.value]));
}

function calendarDate(parts: Record<string, string>, locale: DateLocale) {
  const month = months[locale][Number(parts.month) - 1];
  if (locale === "kk") return `${parts.year} ж. ${parts.day.padStart(2, "0")} ${month}`;
  const day = Number(parts.day);
  return locale === "ru" ? `${day} ${month} ${parts.year} г.` : `${day} ${month} ${parts.year}`;
}

export function formatDateTime(value: string, timezone = "Asia/Oral", locale: DateLocale = "ru") {
  try {
    const parts = partsInZone(value, timezone);
    return `${calendarDate(parts, locale)}, ${parts.hour.padStart(2, "0")}:${parts.minute.padStart(2, "0")}`;
  } catch {
    return value;
  }
}

// Calendar-only dates (for example a birthday) use UTC, so the day never shifts
// with the browser's or participant's timezone.
export function formatDate(value: string, locale: DateLocale = "ru") {
  try {
    return calendarDate(partsInZone(value, "UTC"), locale);
  } catch {
    return value;
  }
}
