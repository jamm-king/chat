import { useState } from 'react'

export default function ThemeToggle () {
    //야간모드 전환 단추//
    const [dark, setDark] = useState(false);

    const toggle = ()=>{
        const next = !dark;
        setDark(next);
        document.documentElement.dataset.theme = next ? "dark":"light"
    }
  return (
    <button type="button" onClick={toggle}>
        {dark ? "밝은 모드" : "야간 모드"}
    </button>
  )
}
