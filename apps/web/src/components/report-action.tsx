"use client";

import { Button } from "@/components/ui";
import { useLocale } from "@/lib/i18n";

export function ReportAction({ type, entity }: { type: "project" | "mentor"; entity: string }) {
  const { locale } = useLocale();
  const label = locale === "kk" ? "Қолдауға хабарласу" : locale === "en" ? "Contact support" : "Обратиться в поддержку";
  return <Button variant="ghost" href={`/support?type=${type}&entity=${encodeURIComponent(entity)}`}>{label}</Button>;
}
