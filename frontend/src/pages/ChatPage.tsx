import { Navigate } from "react-router-dom";
import { getAccessToken } from "../lib/auth";
import "../features/chat/chat.css";
import MessageBubble from "../features/chat/MessageBubble";

export default function ChatPage() {
    if (!getAccessToken()) {
        return <Navigate to="/login" replace />;
    }
    return (
        <div className="chat">
            <aside className="chat-side">자료 목록 자리</aside>
            <main className="chat-main">
                <header className="chat-head">대화</header>
                <section className="chat-list">
                    <MessageBubble role="USER" content="등록된 노션 페이지의 핵심 내용을 요약해줘." />
                    <MessageBubble role="ASSISTANT" content="노션 페이지의 핵심 요약은 다음과 같습니다." />
                </section>
                <form className="chat-input">입력 칸 자리</form>
            </main>
        </div>
    );
}
