"use client";
import { AppShell } from "@/components/shell";
import { Button } from "@/components/ui";
import { useLocale } from "@/lib/i18n";

export default function RegistrationPage() {
  const { tr } = useLocale();
  return <AppShell title={tr("Регистрация участников")} description={tr("Выберите роль и посмотрите, какие данные нужны для анкеты.")}>
    <div className="container section stack narrow" style={{ paddingTop: 0 }}>
      <div className="grid-2">
        <section className="panel"><p className="eyebrow">01</p><h2>{tr("Я менти")}</h2><p>{tr("Ищу поддержку ментора для своей идеи, обучения или профессионального развития.")}</p><Button href="/register/mentee">{tr("Посмотреть анкету менти")}</Button></section>
        <section className="panel"><p className="eyebrow">02</p><h2>{tr("Я ментор")}</h2><p>{tr("Готов(а) делиться опытом и помогать менти двигаться к цели.")}</p><Button href="/register/mentor">{tr("Посмотреть анкету ментора")}</Button></section>
      </div>
      <p className="notice">{tr("Для просмотра полей вход не нужен. Регистрация начинается с подтверждения вашей почты.")}</p>
      <div className="actions"><Button href="/login" variant="secondary">{tr("Уже есть аккаунт — войти")}</Button></div>
    </div>
  </AppShell>;
}
