import { useState } from 'react'
import { applyTheme, saveTheme } from "../lib/theme";

export default function ThemeToggle () {
    //야간모드 전환 단추//
    const [dark, setDark] = useState(document.documentElement.dataset.theme === "dark");

    const toggle = ()=>{
        const next = !dark;
        const theme = next ? "dark":"light"
        setDark(next);
        applyTheme(theme);
        saveTheme(theme);
    }
  return (
    <button
        type="button"
        className="theme-toggle"
        onClick={toggle}
        aria-label={dark ? "밝은 모드로 바꾸기" : "야간 모드로 바꾸기"}
        title={dark ? "밝은 모드" : "야간 모드"}
    >
        {dark ? (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round">
                <circle cx="12" cy="12" r="4" />
                <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
            </svg>
        ) : (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
            </svg>
        )}
    </button>
  )
}
