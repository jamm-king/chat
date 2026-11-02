import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import "../features/auth/auth.css";

export default function SignupPage() {
    const navigate = useNavigate();
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [error, setError] = useState("");

    const submit = async (event: FormEvent) => {
        event.preventDefault();
        const response = await fetch("/api/v1/auth/signup", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, password }),
        });
        const data = await response.json();
        if (!response.ok) {
            setError(data.error?.message ?? "회원가입에 실패했어요.");
            return;
        }
        navigate("/login");
    };

    return (
        <main className="auth">
            <form className="auth-card" onSubmit={submit}>
                <h1>chat</h1>
                <p className="auth-sub">새 계정 만들기</p>
                <label>
                    이메일
                    <input type="email" value={email}
                        onChange={(event) => setEmail(event.target.value)}
                        autoComplete="email"/>
                </label>
                <label>
                    비밀번호
                    <input
                        type="password"value={password}
                        onChange={(event) => setPassword(event.target.value)}
                        autoComplete="new-password"/>
                </label>
                {error && <p className="auth-error">{error}</p>}
                <button type="submit" disabled={!email || !password}>회원가입</button>
                <p className="auth-link">이미 계정이 있나요? <Link to="/login">로그인</Link></p>
            </form>
        </main>
    );
}
