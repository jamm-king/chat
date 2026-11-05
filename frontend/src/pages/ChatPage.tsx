import { useEffect, useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { clearTokens, getAccessToken, getRefreshToken } from "../lib/auth";
import "../features/chat/chat.css";
import MessageBubble from "../features/chat/MessageBubble";

type Message = {
    role: "USER" | "ASSISTANT";
    content: string;
};

type Connection = {
    connectionId: string;
    workspaceName: string | null;
};

export default function ChatPage() {
    const [connections, setConnections] = useState<Connection[]>([]);
    const navigate = useNavigate();
    const [text, setText] = useState("");
    const [messages, setMessages] = useState<Message[]>([]);
    const [notionError, setNotionError] = useState("")
    const [connecting, setConnecting] = useState(false);
    useEffect(() => {
        if (!getAccessToken()) return;
        const load = async () => {
            const response = await fetch("/api/v1/messages", {
                headers: { Authorization: `Bearer ${getAccessToken()}` },
            });
            if (!response.ok) return;
            const data = await response.json();
            setMessages(data.messages);
        };
        load();
    }, []);
    useEffect(() => {
        if (!getAccessToken()) return;
        const loadConnections = async () => {
            const response = await fetch("/api/v1/integrations/notion/connections", {
                headers: { Authorization: `Bearer ${getAccessToken()}` },
            });
            if (!response.ok) return;
            const data = await response.json();
            setConnections(data.connections);
        };
        loadConnections();
    }, []);
    if (!getAccessToken()) {
        return <Navigate to="/login" replace />;
    }

    const send = async (event: FormEvent) => {
        event.preventDefault();
        const question = text;
        setText("");
        setMessages((prev) => [...prev, { role: "USER", content: question }]);

        const response = await fetch("/api/v1/messages", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                Authorization: `Bearer ${getAccessToken()}`,
            },
            body: JSON.stringify({ mode: "GENERAL", message: question }),
        });
        const data = await response.json();
        const answer = response.ok ? data.content : data.error?.message ?? "답변을 받지 못했어요.";
        setMessages((prev) => [...prev, { role: "ASSISTANT", content: answer }]);
    };

    const connectNotion = async () => {
        setNotionError("");
        setConnecting(true);
        try {
            const response = await fetch("/api/v1/integrations/notion/authorize", {
                method: "POST",
                headers: { Authorization: `Bearer ${getAccessToken()}` },
            });
            const data = await response.json();
            if (!response.ok) {
                setNotionError(data.error?.message ?? "노션 연결을 시작하지 못했어요.");
                return;
            }
            window.location.href = data.authorizationUrl;
        } finally {
            setConnecting(false);
        }
    };


    const logout = async () => {
        try {
            await fetch("/api/v1/auth/logout", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ refresh_token: getRefreshToken() }),
            });
        } finally {
            clearTokens();
            navigate("/login", { replace: true });
        }
    };

    return (
        <div className="chat">
            <aside className="chat-side">
                <div>
                    {connections.length > 0 ? (
                        <p className="chat-notion-done">
                            노션 연결됨 · {connections.map((c) => c.workspaceName ?? "이름 없는 워크스페이스").join(", ")}
                        </p>
                    ) : (
                        <button type="button" className="chat-notion" onClick={connectNotion} disabled={connecting}>
                            {connecting ? "연결 중…" : "노션 연결"}
                        </button>
                    )}

                    {notionError && <p className="chat-error">{notionError}</p>}
                    <p>자료 목록 자리</p>
                </div>

                <button type="button" className="chat-logout" onClick={logout}>로그아웃</button>
            </aside>
            <main className="chat-main">
                <header className="chat-head">대화</header>
                <section className="chat-list">
                    {messages.map((message, index) => (
                        <MessageBubble key={index} role={message.role} content={message.content} />
                    ))}
                </section>
                <form className="chat-input" onSubmit={send}>
                    <input
                        value={text}
                        onChange={(event) => setText(event.target.value)}
                        placeholder="질문을 입력하세요"
                    />
                    <button type="submit" disabled={!text.trim()}>보내기</button>
                </form>
            </main>
        </div>
    );
}
