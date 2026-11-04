import { Link, useSearchParams } from "react-router-dom";
import "../features/auth/auth.css";

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
        ? "이제 노션 페이지를 자료로 등록할 수 있어요."
        : FAIL_MESSAGES[reason] ?? FAIL_MESSAGES.failed;

    return (
        <main className="auth">
            <div className="auth-card">
                <h1>{connected ? "연결됐어요" : "연결 실패"}</h1>
                <p className="auth-sub">{message}</p>
                <p className="auth-link"><Link to="/chat">대화 화면으로 돌아가기</Link></p>
            </div>
        </main>
    );
}
