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
  options: RequestInit & { retry?: boolean } = {},
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
  const { retry = false, ...requestOptions } = options;
  const timeout = AbortSignal.timeout(20000);
  const signal = options.signal
    ? AbortSignal.any([options.signal, timeout])
    : timeout;
  // Retry only explicitly opted-in reads, within the original timeout budget.
  // Mutations must never be replayed after an ambiguous response.
  const canRetry = (attempt: number) => retry &&
    (options.method ?? "GET").toUpperCase() === "GET" && attempt < 2 && !signal.aborted;
  const networkError = () => new ApiError(
    0,
    "Не удалось связаться с платформой. Проверьте подключение и повторите попытку.",
  );
  async function request(attempt: number): Promise<Response> {
    if (signal.aborted) throw networkError();
    let response: Response | undefined;
    try {
      response = await fetch(`/api/v1${path}`, {
        ...requestOptions,
        headers,
        signal,
        credentials: "include",
        cache: "no-store",
      });
    } catch {
      if (!canRetry(attempt)) throw networkError();
    }
    if (response && (!canRetry(attempt) || ![500, 502, 503, 504].includes(response.status))) return response;
    await response?.body?.cancel();
    await new Promise<void>((resolve) => setTimeout(resolve, 500 * 2 ** attempt));
    return request(attempt + 1);
  }
  const response = await request(0);
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
