const ACCESS_KEY = "chat.accessToken";
const REFRESH_KEY = "chat.refreshToken";

export function saveTokens(access: string, refresh: string) {
    // 토큰 브라우저에 저장
    localStorage.setItem(ACCESS_KEY, access);
    localStorage.setItem(REFRESH_KEY, refresh);
}
