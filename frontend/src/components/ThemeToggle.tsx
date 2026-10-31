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
    <button type="button" className="theme-toggle" onClick={toggle}>
        {dark ? "밝은 모드" : "야간 모드"}
    </button>
  )
}
