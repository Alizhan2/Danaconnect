"use client";
import { Suspense, useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AppShell } from "@/components/shell";
import { Button, Field } from "@/components/ui";
import { usePlatformStatus } from "@/components/platform-status";
import { useLocale } from "@/lib/i18n";
import { api, ApiError } from "@/lib/api";
import type { User } from "@/lib/types";
import { onboardingPath, participantRole } from "@/lib/registration";
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
  delivery_status?: "queued" | "sent" | "development";
};
type MfaChallenge = {
  mfa_required: true;
  mfa_challenge_id: string;
  method: "totp";
  expires_in: number;
  enrollment?: { qr_data_url: string; manual_entry_key: string };
};
function Login() {
  const { locale, t, tr } = useLocale();
  const { health } = usePlatformStatus();
  const router = useRouter();
  const search = useSearchParams();
  const action = useAction();
  const returnTo = safeReturnTo(search.get("returnTo"));
  const role = participantRole(search.get("role"));
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [challenge, setChallenge] = useState<Challenge>();
  const [mfa, setMfa] = useState<MfaChallenge & { deadline: number }>();
  const [expired, setExpired] = useState(false);
  const [qrFailed, setQrFailed] = useState(false);
  const attempt = useRef(0);
  const resetLogin = useCallback((timedOut = false) => {
    attempt.current++;
    setChallenge(undefined);
    setMfa(undefined);
    setCode("");
    setExpired(timedOut);
    setQrFailed(false);
  }, []);
  useEffect(() => {
    const leave = () => resetLogin();
    const restore = (event: PageTransitionEvent) => { if (event.persisted) resetLogin(); };
    window.addEventListener("pagehide", leave);
    window.addEventListener("pageshow", restore);
    return () => {
      attempt.current++;
      window.removeEventListener("pagehide", leave);
      window.removeEventListener("pageshow", restore);
    };
  }, [resetLogin]);
  const deadline = mfa?.deadline;
  useEffect(() => {
    if (deadline === undefined) return;
    const checkTime = () => {
      if (Date.now() >= deadline) resetLogin(true);
    };
    const timer = window.setTimeout(checkTime, Math.max(0, deadline - Date.now()));
    document.addEventListener("visibilitychange", checkTime);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", checkTime);
    };
  }, [deadline, resetLogin]);
  const enrollment = mfa?.enrollment;
  const image = enrollment?.qr_data_url;
  const showQr = !qrFailed && typeof image === "string" && image.length <= 200000 &&
    /^data:image\/svg\+xml;base64,[A-Za-z0-9+/]+={0,2}$/.test(image);
  const providers = useLoad(() =>
    api<{ email: boolean; google: boolean; admin_mfa: boolean }>(
      "/auth/providers",
    ),
  );
  function finish(user: User) {
    resetLogin();
    router.push(
      user.role === "unchosen" || user.account_status !== "active" || (user.role !== "admin" && user.profile_completed === false)
        ? onboardingPath(user.role === "unchosen" ? role : undefined, returnTo)
        : returnTo,
    );
    router.refresh();
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    const currentAttempt = attempt.current;
    await action.run(
      async () => {
        if (mfa) {
          if (Date.now() >= mfa.deadline) {
            resetLogin(true);
            return;
          }
          try {
            const user = await mutate<User>("/auth/mfa/verify", {
              mfa_challenge_id: mfa.mfa_challenge_id,
              code,
            });
            if (currentAttempt === attempt.current) finish(user);
          } catch (error) {
            if (currentAttempt !== attempt.current) return;
            if (error instanceof ApiError && error.status === 410) {
              resetLogin(true);
              return;
            }
            throw error;
          }
        } else if (!challenge) {
          setExpired(false);
          const issued = await mutate<Challenge>("/auth/request-code", { email, locale });
          if (currentAttempt === attempt.current) setChallenge(issued);
        } else {
          const response = await mutate<User | MfaChallenge>(
            "/auth/verify-code",
            { challenge_id: challenge.challenge_id, code },
          );
          if (currentAttempt !== attempt.current) return;
          if ("mfa_required" in response) {
            setMfa({ ...response, deadline: Date.now() + response.expires_in * 1000 });
            setCode("");
          } else finish(response);
        }
      },
      !challenge ? "Код запрошен" : mfa ? "" : "Код проверен",
    );
  }
  async function google() {
    await action.run(async () => {
      const query = new URLSearchParams({ locale, return_to: returnTo });
      if (role) query.set("role", role);
      const result = await api<{ authorization_url: string }>(`/auth/google/start?${query.toString()}`);
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
          {role && !mfa && <p className="notice">{tr(role === "mentor" ? "Регистрация ментора: подтвердите свою почту, затем заполните анкету." : "Регистрация менти: подтвердите свою почту, затем заполните анкету.")}</p>}
          <p>
            {tr(enrollment ? "Отсканируйте QR в приложении-аутентификаторе, затем введите шестизначный код."
              : mfa ? "Введите шестизначный код из приложения." : "Войдите по одноразовому коду.")}
            {health?.demo_mode && (
              <> {tr("Для демонстрации используйте только учебный email.")}</>
            )}
          </p>
          {expired ? <p className="notice" role="status">{tr("Срок подтверждения истёк. Запросите новый код на почту.")}</p> : <ActionNotice action={action} />}
          {enrollment && (
            <section aria-labelledby="authenticator-setup" className="stack">
              <h2 id="authenticator-setup">{tr("Добавьте DanaConnect в приложение-аутентификатор")}</h2>
              {showQr ? (
                <img src={image} alt={tr("QR-код для настройки аутентификатора")}
                  width={256} height={256} style={{ maxWidth: "100%", height: "auto" }}
                  referrerPolicy="no-referrer" onError={() => setQrFailed(true)} />
              ) : <p role="status">{tr("QR не загрузился. Используйте ключ для ручной настройки.")}</p>}
              <details>
                <summary>{tr("Ввести ключ вручную")}</summary>
                <p>{tr("Выберите одноразовые коды по времени (TOTP) и введите ключ.")}</p>
                <code style={{ overflowWrap: "anywhere" }}>{enrollment.manual_entry_key}</code>
              </details>
            </section>
          )}
          {!mfa && (challenge?.delivery_status === "queued" || challenge?.delivery_status === "sent") && (
            <div className="notice">
              {tr(
                challenge.delivery_status === "sent"
                  ? "Код отправлен на вашу почту. Проверьте входящие и папку «Спам»."
                  : "Код будет отправлен на вашу почту. Проверьте входящие и папку «Спам».",
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
                {!mfa && challenge.debug_code && health?.demo_mode && (
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
                  resetLogin();
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
          <div className="actions"><Button href="/register" variant="ghost">{tr("Посмотреть поля регистрации")}</Button></div>
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
