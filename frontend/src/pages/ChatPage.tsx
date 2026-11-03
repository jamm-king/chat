import { useEffect, useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { getAccessToken } from "../lib/auth";
import "../features/chat/chat.css";
import MessageBubble from "../features/chat/MessageBubble";

type Message = {
    role: "USER" | "ASSISTANT";
    content: string;
};

export default function ChatPage() {
    const [text, setText] = useState("");
    const [messages, setMessages] = useState<Message[]>([]);
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

    return (
        <div className="chat">
            <aside className="chat-side">자료 목록 자리</aside>
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
