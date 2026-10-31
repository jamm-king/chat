import { useState, type FormEvent } from "react";
import {Link} from "react-router-dom";
import "../features/auth/auth.css";

export default function LoginPage() {
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");

    const submit = (event: FormEvent) =>{
        event.preventDefault();
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
        <button type="submit" disabled={!email || !password}>로그인</button>
        <p className="auth-link">처음이신가요? <Link to="/signup">회원가입</Link></p>
      </form>
    </main>)
}