import { getCurrentLocale, translatePhrase } from "./i18n";
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public requestId?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  if (
    !path.startsWith("/") ||
    path.startsWith("//") ||
    path.startsWith("/api/v1")
  )
    throw new Error("API paths must begin with / and omit the /api/v1 prefix.");
  const headers = new Headers(options.headers);
  headers.set("Accept-Language", getCurrentLocale());
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  let response: Response;
  const timeout = AbortSignal.timeout(20000);
  const signal = options.signal
    ? AbortSignal.any([options.signal, timeout])
    : timeout;
  try {
    response = await fetch(`/api/v1${path}`, {
      ...options,
      headers,
      signal,
      credentials: "include",
      cache: "no-store",
    });
  } catch {
    throw new ApiError(
      0,
      "Не удалось связаться с платформой. Проверьте подключение и повторите попытку.",
    );
  }
  const data =
    response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) {
    const detail =
      typeof data?.detail === "string"
        ? data.detail
        : response.status === 401
          ? "Войдите в аккаунт, чтобы продолжить."
          : response.status === 403
            ? "Это действие недоступно для вашего аккаунта."
            : "Не удалось выполнить запрос. Повторите попытку.";
    const headerId = response.headers.get("X-Request-ID");
    const requestId = headerId && /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(headerId) ? headerId : undefined;
    throw new ApiError(response.status, detail, requestId);
  }
  return data as T;
}
export function errorMessage(error: unknown) {
  const message = translatePhrase(
    error instanceof Error
      ? error.message
      : "Произошла ошибка. Повторите попытку.",
  );
  if (error instanceof ApiError && error.requestId) {
    const label = {ru: "Номер запроса", kk: "Сұрау нөмірі", en: "Request ID"}[getCurrentLocale()];
    return `${message} ${label}: ${error.requestId}`;
  }
  return message;
}
