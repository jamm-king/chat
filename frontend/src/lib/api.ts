import { clearTokens, getAccessToken, getRefreshToken, saveTokens } from "./auth";

// 백엔드 공통 오류 형식 { error: { code, message, retryable } } 을 그대로 담는다
export class ApiError extends Error {
    status: number;
    code: string;
    retryable: boolean;

    constructor(status: number, code: string, message: string, retryable = false) {
        super(message);
        this.status = status;
        this.code = code;
        this.retryable = retryable;
    }
}

let refreshing: Promise<boolean> | null = null;

// 액세스 토큰이 만료되면 리프레시 토큰으로 새로 받는다.
// 여러 요청이 동시에 401 을 받아도 갱신은 한 번만 (리프레시 토큰은 한 번 쓰면 폐기되기 때문)
function refreshTokens(): Promise<boolean> {
    const refreshToken = getRefreshToken();
    if (!refreshToken) return Promise.resolve(false);
    if (!refreshing) {
        refreshing = fetch("/api/v1/auth/refresh", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ refresh_token: refreshToken }),
        })
            .then(async (response) => {
                if (!response.ok) return false;
                const data = await response.json();
                saveTokens(data.access_token, data.refresh_token);
                return true;
            })
            .catch(() => false)
            .finally(() => {
                refreshing = null;
            });
    }
    return refreshing;
}

// 인증이 필요한 요청. 401 이면 토큰을 갱신해 한 번 다시 보내고, 그래도 안 되면 로그인 화면으로
export async function apiFetch<T>(path: string, init: RequestInit = {}, retried = false): Promise<T> {
    const headers = new Headers(init.headers);
    const usedToken = getAccessToken();
    headers.set("Authorization", `Bearer ${usedToken ?? ""}`);
    if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");

    let response: Response;
    try {
        response = await fetch(path, { ...init, headers });
    } catch {
        throw new ApiError(0, "NETWORK", "서버에 연결할 수 없어요.");
    }

    if (response.status === 401 && !retried) {
        // 다른 요청이 그사이 이미 갱신했으면 새 토큰으로 다시 보내기만 한다
        const renewed = getAccessToken() !== usedToken || (await refreshTokens());
        if (renewed) return apiFetch<T>(path, init, true);
        clearTokens();
        window.location.replace("/login");
        throw new ApiError(401, "AUTH", "다시 로그인해 주세요.");
    }
    if (response.status === 204) return undefined as T;

    const data = await response.json().catch(() => null);
    if (!response.ok) {
        const error = data?.error;
        // 토큰의 사용자가 없어짐(탈퇴 등). 토큰을 지우고 로그인부터 다시
        if (error?.code === "USER_NOT_FOUND") {
            clearTokens();
            window.location.replace("/login");
        }
        throw new ApiError(response.status, error?.code ?? "UNKNOWN", error?.message ?? "요청을 처리하지 못했어요.", Boolean(error?.retryable));
    }
    return data as T;
}
