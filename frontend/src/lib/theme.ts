const KEY = "chat.theme";

export function loadTheme(){
    //배경 <일반, 야간> 모드 부르는 함수//
    const saved = localStorage.getItem(KEY)
    if (saved === "dark" || saved === "light"){
        return saved;
    }return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(theme: string) {
    document.documentElement.dataset.theme = theme;
}

export function saveTheme (theme: string) {
    localStorage.setItem(KEY, theme);
}