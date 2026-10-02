"use client";
import { Suspense, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AppShell } from "@/components/shell";
import { Button, Field } from "@/components/ui";
import { usePlatformStatus } from "@/components/platform-status";
import { useLocale } from "@/lib/i18n";
import { api } from "@/lib/api";
import type { User } from "@/lib/types";
import {
  ActionNotice,
  LoadState,
  mutate,
  safeReturnTo,
  useAction,
  useLoad,
} from "@/components/workflows/common";
type Challenge = {
  challenge_id: string;
  debug_code?: string;
  delivery_status?: "queued" | "development";
};
type MfaChallenge = {
  mfa_required: true;
  mfa_challenge_id: string;
  method: "totp";
  expires_in: number;
};
function Login() {
  const { locale, t, tr } = useLocale();
  const { health } = usePlatformStatus();
  const router = useRouter();
  const search = useSearchParams();
  const action = useAction();
  const returnTo = safeReturnTo(search.get("returnTo"));
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [challenge, setChallenge] = useState<Challenge>();
  const [mfa, setMfa] = useState<MfaChallenge>();
  const providers = useLoad(() =>
    api<{ email: boolean; google: boolean; admin_mfa: boolean }>(
      "/auth/providers",
    ),
  );
  function finish(user: User) {
    router.push(
      user.role === "unchosen" || user.account_status !== "active"
        ? `/onboarding?returnTo=${encodeURIComponent(returnTo)}`
        : returnTo,
    );
    router.refresh();
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    await action.run(
      async () => {
        if (mfa) {
          finish(
            await mutate<User>("/auth/mfa/verify", {
              mfa_challenge_id: mfa.mfa_challenge_id,
              code,
            }),
          );
        } else if (!challenge) {
          setChallenge(
            await mutate<Challenge>("/auth/request-code", { email, locale }),
          );
        } else {
          const response = await mutate<User | MfaChallenge>(
            "/auth/verify-code",
            { challenge_id: challenge.challenge_id, code },
          );
          if ("mfa_required" in response) {
            setMfa(response);
            setCode("");
          } else finish(response);
        }
      },
      !challenge ? "Код запрошен" : mfa ? "Вход выполнен" : "Код проверен",
    );
  }
  async function google() {
    await action.run(async () => {
      const result = await api<{ authorization_url: string }>(
        `/auth/google/start?locale=${locale}`,
      );
      const target = new URL(result.authorization_url);
      if (
        target.protocol !== "https:" ||
        target.hostname !== "accounts.google.com"
      )
        throw new Error("Не удалось начать вход через Google.");
      window.location.assign(target.href);
    }, "Переход к Google");
  }
  return (
    <AppShell>
      <div className="auth-container">
        <div className="panel auth-card">
          <p className="eyebrow">DANACONNECT</p>
          <h1>{mfa ? tr("Защита аккаунта") : t.login}</h1>
          <p>
            {tr("Войдите по одноразовому коду.")}
            {health?.demo_mode && (
              <> {tr("Для демонстрации используйте только учебный email.")}</>
            )}
          </p>
          <ActionNotice action={action} />
          {challenge?.delivery_status === "queued" && (
            <div className="notice">
              {tr(
                "Код будет отправлен на вашу почту. Проверьте входящие и папку «Спам».",
              )}
            </div>
          )}
          <form className="form-stack" onSubmit={submit}>
            <Field label="Email">
              <input
                type="email"
                autoComplete="email"
                required
                maxLength={254}
                value={email}
                disabled={Boolean(challenge)}
                onChange={(event) => setEmail(event.target.value)}
              />
            </Field>
            {challenge && (
              <>
                <Field
                  label={
                    mfa
                      ? tr("Код из приложения аутентификатора")
                      : tr("Одноразовый код")
                  }
                >
                  <input
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    pattern="[0-9]{6}"
                    maxLength={6}
                    required
                    value={code}
                    onChange={(event) => setCode(event.target.value)}
                  />
                </Field>
                {challenge.debug_code && health?.demo_mode && (
                  <div className="notice">
                    {tr("Режим разработки: код")}{" "}
                    <strong>{challenge.debug_code}</strong>
                    {tr(". Отправка писем в этом режиме не подключена.")}
                  </div>
                )}
              </>
            )}
            <Button type="submit" disabled={action.busy}>
              {action.busy
                ? t.loading
                : mfa
                  ? tr("Подтвердить вход")
                  : challenge
                    ? t.login
                    : tr("Получить код")}
            </Button>
            {challenge && (
              <Button
                variant="ghost"
                onClick={() => {
                  setChallenge(undefined);
                  setMfa(undefined);
                  setCode("");
                  action.clear();
                }}
              >
                {tr("Изменить email / запросить новый код")}
              </Button>
            )}
          </form>
          <LoadState {...providers} retry={providers.reload}>
            {providers.data?.google && (
              <div className="actions">
                <Button
                  variant="secondary"
                  onClick={google}
                  disabled={action.busy}
                >
                  {tr("Войти через Google")}
                </Button>
              </div>
            )}
          </LoadState>
        </div>
      </div>
    </AppShell>
  );
}
export default function LoginPage() {
  const { t } = useLocale();
  return (
    <Suspense fallback={<div className="loading-state">{t.loading}</div>}>
      <Login />
    </Suspense>
  );
}
