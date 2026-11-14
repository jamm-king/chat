import { useEffect, useState } from "react";

const SLOW_MS = 15000;

// 답변 생성은 최대 1분 정도 걸릴 수 있어서(레퍼런스 4.1.1), 오래 걸리면 안내를 한 줄 더 보인다
export default function PendingBubble() {
    const [slow, setSlow] = useState(false);

    useEffect(() => {
        const timer = window.setTimeout(() => setSlow(true), SLOW_MS);
        return () => window.clearTimeout(timer);
    }, []);

    return (
        <div className="bubble bubble-assistant bubble-pending" role="status">
            <span className="bubble-text">
                답을 만들고 있어요<span className="dots" aria-hidden="true" />
            </span>
            {slow && <span className="bubble-slow">자료가 많으면 1분 정도 걸릴 수 있어요.</span>}
        </div>
    );
}
