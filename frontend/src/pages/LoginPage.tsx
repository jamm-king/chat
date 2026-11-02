import { useState, type FormEvent } from "react";
import {Link} from "react-router-dom";
import "../features/auth/auth.css";
import { saveTokens } from "../lib/auth";


export default function LoginPage() {
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [error, setError] = useState("");

    const submit = async (event: FormEvent) =>{
        event.preventDefault();
        const response = await fetch("/api/v1/auth/login",{
          method: "POST",
          headers: { "Content-type": "application/json"},
          body: JSON.stringify({email,password}),
        });
        const data = await response.json();
        if (!response.ok) {
          setError(data.error?.message ?? "로그인하지 못했어요.")
          return
        }
        setError("");
        saveTokens(data.access_token, data.refresh_token);

    }
    return ( <main className="auth">
      <form className="auth-card" onSubmit={submit}>
        <h1>chat</h1>
        <p className="auth-sub">리서치 파트너 찾</p>
        <label>
          이메일
          <input
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            autoComplete="email"
          />
        </label>
        <label>
          비밀번호
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
          />
        </label>
          {error && <p className="auth-error">{error}</p>}
        <button type="submit" disabled={!email || !password}>로그인</button>
        <p className="auth-link">처음이신가요? <Link to="/signup">회원가입</Link></p>
      </form>
    </main>)
}