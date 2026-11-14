import { useEffect, useRef, useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { apiFetch } from "../lib/api";
import { clearTokens, getAccessToken, getRefreshToken } from "../lib/auth";
import "../features/chat/chat.css";
import MessageBubble from "../features/chat/MessageBubble";
import PendingBubble from "../features/chat/PendingBubble";
import {
    MAX_LENGTH,
    clearMessages,
    isCleared,
    isResourceError,
    loadMessages,
    messageErrorText,
    sendMessage,
} from "../features/chat/messageApi";
import type { ChatMessage } from "../features/chat/types";
import NotionGuide from "../features/notion/NotionGuide";
import PagePicker from "../features/resources/PagePicker";
import ResourcePanel from "../features/resources/ResourcePanel";
import { listConnections, resourceErrorText } from "../features/resources/resourceApi";
import type { Connection } from "../features/resources/types";
import { useResources } from "../features/resources/useResources";

const MAX_RESOURCES = 100;
const COUNT_FROM = 3500;

// 로그인 확인을 먼저 하고, 화면(훅을 쓰는 부분)은 토큰이 있을 때만 그린다
export default function ChatPage() {
    if (!getAccessToken()) return <Navigate to="/login" replace />;
    return <ChatScreen />;
}

function ChatScreen() {
    const navigate = useNavigate();
    const [connections, setConnections] = useState<Connection[]>([]);
    const [notionError, setNotionError] = useState("");
    const [connecting, setConnecting] = useState(false);
    const [guideOpen, setGuideOpen] = useState(false);
    const [pickerOpen, setPickerOpen] = useState(false);

    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [text, setText] = useState("");
    const [sending, setSending] = useState(false);
    const [chatError, setChatError] = useState("");
    const [selected, setSelected] = useState<string[]>([]);
    // 기록을 지우면 1 늘린다. 지우기 전에 보낸 질문의 답이 늦게 와도 화면에 붙이지 않기 위해
    const generation = useRef(0);
    const listRef = useRef<HTMLElement>(null);

    const { resources, error: resourceError, reload, add, remove, retry, titleOf } = useResources();

    // 고른 자료 중 지금도 READY 인 것만 보낸다 (지워지거나 상태가 바뀐 자료는 저절로 빠짐)
    const ready = new Set(resources.filter((r) => r.status === "READY").map((r) => r.resourceId));
    const chosen = selected.filter((id) => ready.has(id));
    const chosenTitles = chosen.map((id) => {
        const resource = resources.find((r) => r.resourceId === id);
        return resource ? titleOf(resource) : "";
    });
    const citationTitle = (resourceId: string | null) => resources.find((r) => r.resourceId === resourceId)?.title ?? null;

    useEffect(() => {
        loadMessages()
            .then(setMessages)
            .catch((e) => setChatError(messageErrorText(e)));
        listConnections()
            .then(setConnections)
            .catch((e) => setNotionError(resourceErrorText(e)));
    }, []);

    useEffect(() => {
        const list = listRef.current;
        if (list) list.scrollTop = list.scrollHeight;
    }, [messages, sending]);

    const ask = async (question: string) => {
        const turn = generation.current;
        const local: ChatMessage = { messageId: `local-${Date.now()}`, role: "USER", content: question, citations: [] };
        setMessages((prev) => [...prev, local]);
        setSending(true);
        setChatError("");
        try {
            const answer = await sendMessage(question, chosen);
            if (turn !== generation.current) return;
            setMessages((prev) => [
                ...prev,
                {
                    messageId: answer.answerId,
                    role: "ASSISTANT",
                    mode: answer.mode,
                    status: answer.status,
                    content: answer.content,
                    citations: answer.citations ?? [],
                },
            ]);
        } catch (e) {
            if (turn !== generation.current) return;
            if (isCleared(e)) {
                setMessages((prev) => prev.filter((m) => m.messageId !== local.messageId));
                return;
            }
            if (isResourceError(e)) reload();
            setMessages((prev) => prev.map((m) => (m.messageId === local.messageId ? { ...m, failed: messageErrorText(e) } : m)));
        } finally {
            if (turn === generation.current) setSending(false);
        }
    };

    const send = (event: FormEvent) => {
        event.preventDefault();
        const question = text.trim();
        if (!question || sending) return;
        setText("");
        ask(question);
    };

    const resend = (message: ChatMessage) => {
        if (sending) return;
        setMessages((prev) => prev.filter((m) => m.messageId !== message.messageId));
        ask(message.content);
    };

    const clearHistory = async () => {
        if (!window.confirm("대화 기록을 모두 지울까요? 되돌릴 수 없어요.")) return;
        try {
            await clearMessages();
            generation.current += 1;
            setMessages([]);
            setSending(false);
            setChatError("");
        } catch (e) {
            setChatError(messageErrorText(e));
        }
    };

    const toggle = (resourceId: string) =>
        setSelected((prev) => {
            if (prev.includes(resourceId)) return prev.filter((id) => id !== resourceId);
            return prev.length >= MAX_RESOURCES ? prev : [...prev, resourceId];
        });

    const connectNotion = async () => {
        setNotionError("");
        setConnecting(true);
        try {
            const data = await apiFetch<{ authorizationUrl: string }>("/api/v1/integrations/notion/authorize", { method: "POST" });
            window.location.href = data.authorizationUrl;
        } catch {
            setNotionError("노션 연결을 시작하지 못했어요.");
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
                <div className="chat-side-top">
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
                    <button type="button" className="chat-guide-link" onClick={() => setGuideOpen(true)}>
                        노션 연결은 어떻게 하나요?
                    </button>

                    <ResourcePanel
                        resources={resources}
                        error={resourceError}
                        selected={chosen}
                        canAdd={connections.length > 0}
                        titleOf={titleOf}
                        onToggle={toggle}
                        onAdd={() => setPickerOpen(true)}
                        onRemove={remove}
                        onRetry={retry}
                        onReconnect={connectNotion}
                    />
                </div>

                <button type="button" className="chat-logout" onClick={logout}>로그아웃</button>
            </aside>
            <main className="chat-main">
                <header className="chat-head">
                    <span>대화</span>
                    <button
                        type="button"
                        className="chat-clear"
                        onClick={clearHistory}
                        disabled={messages.length === 0 && !sending}
                    >
                        기록 지우기
                    </button>
                </header>
                <section className="chat-list" ref={listRef}>
                    {messages.length === 0 && !sending && !chatError && (
                        <p className="chat-empty">
                            궁금한 것을 물어보세요. 등록한 노션 자료가 필요한 질문이면 자료에서 찾아 출처와 함께 답해요.
                        </p>
                    )}
                    {messages.map((message) => (
                        <MessageBubble
                            key={message.messageId}
                            message={message}
                            titleOf={citationTitle}
                            onRetry={message.failed && !sending ? () => resend(message) : undefined}
                        />
                    ))}
                    {sending && <PendingBubble />}
                    {chatError && <p className="chat-error">{chatError}</p>}
                </section>
                <footer className="chat-foot">
                    {chosen.length > 0 && (
                        <div className="chat-scope">
                            <span className="chat-scope-text" title={chosenTitles.join(", ")}>
                                고른 자료 {chosen.length}개 참고 · {chosenTitles.join(", ")}
                            </span>
                            <button type="button" className="chat-scope-clear" onClick={() => setSelected([])}>선택 해제</button>
                        </div>
                    )}
                    <form className="chat-input" onSubmit={send}>
                        <input
                            value={text}
                            maxLength={MAX_LENGTH}
                            onChange={(event) => setText(event.target.value)}
                            placeholder="질문을 입력하세요"
                        />
                        <button type="submit" disabled={!text.trim() || sending}>{sending ? "답 기다리는 중" : "보내기"}</button>
                    </form>
                    {text.length >= COUNT_FROM && (
                        <p className="chat-count">{text.length.toLocaleString()} / {MAX_LENGTH.toLocaleString()}자</p>
                    )}
                </footer>
            </main>
            {guideOpen && (
                <NotionGuide
                    onClose={() => setGuideOpen(false)}
                    onConnect={connections.length > 0 ? undefined : connectNotion}
                />
            )}
            {pickerOpen && (
                <PagePicker
                    connections={connections}
                    resources={resources}
                    onAdded={add}
                    onReconnect={connectNotion}
                    onClose={() => setPickerOpen(false)}
                />
            )}
        </div>
    );
}
