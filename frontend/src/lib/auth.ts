const ACCESS_KEY = "chat.accessToken";
const REFRESH_KEY = "chat.refreshToken";

export function saveTokens(access: string, refresh: string) {
    // 토큰 브라우저에 저장
    localStorage.setItem(ACCESS_KEY, access);
    localStorage.setItem(REFRESH_KEY, refresh);
}
export function getAccessToken() {
    return localStorage.getItem(ACCESS_KEY)
}
export function getRefreshToken() {
    return localStorage.getItem(REFRESH_KEY);
}

export function clearTokens() {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
}
