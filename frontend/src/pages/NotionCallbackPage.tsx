import { Link, useSearchParams } from "react-router-dom";
import "../features/auth/auth.css";
import "../features/notion/notion.css";

const FAIL_MESSAGES: Record<string, string> = {
    denied: "노션 화면에서 취소했어요.",
    expired: "연결 시간이 지났어요. 다시 연결해 주세요.",
    failed: "노션을 연결하지 못했어요. 잠시 후 다시 해 주세요.",
};

export default function NotionCallbackPage() {
    const [params] = useSearchParams();
    const connected = params.get("status") === "connected";
    const reason = params.get("reason") ?? "failed";
    const message = connected
        ? "이제 노션 페이지 주소를 넣어 자료로 등록할 수 있어요."
        : FAIL_MESSAGES[reason] ?? FAIL_MESSAGES.failed;

    return (
        <main className="auth">
            <div className={connected ? "auth-card notion-result" : "auth-card notion-result notion-fail"}>
                <div className="notion-icon">
                    {connected ? (
                        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M5 12.5l4.2 4.2L19 7" />
                        </svg>
                    ) : (
                        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round">
                            <path d="M12 7v6" />
                            <path d="M12 17.2v.1" />
                        </svg>
                    )}
                </div>
                <h1>{connected ? "노션이 연결됐어요" : "연결하지 못했어요"}</h1>
                <p>{message}</p>
                <Link to="/chat" className="notion-button">대화 화면으로</Link>
            </div>
        </main>
    );
}
