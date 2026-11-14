import type { ReactNode } from "react";
import CitationList from "./CitationList";
import type { ChatMessage, Citation } from "./types";

type Props = {
    message: ChatMessage;
    titleOf: (resourceId: string | null) => string | null;
    onRetry?: () => void;
};

// INSUFFICIENT_EVIDENCE · REFUSED 는 오류가 아니라 정상 답이라, 빨간 글씨 대신 안내 꼬리표로
const NOTE = {
    INSUFFICIENT_EVIDENCE: "자료에서 근거를 찾지 못했어요",
    REFUSED: "답할 수 없는 질문이에요",
} as const;

// 본문의 [1], [2] 중 출처가 있는 번호만 작은 위첨자로 바꾼다
function withMarks(content: string, citations: Citation[]): ReactNode[] {
    const ids = new Set(citations.map((c) => c.citationId));
    return content.split(/(\[\d+\])/g).map((part, index) => {
        const id = /^\[(\d+)\]$/.exec(part)?.[1];
        return id && ids.has(id) ? <sup key={index} className="cite-mark">{id}</sup> : part;
    });
}

export default function MessageBubble({ message, titleOf, onRetry }: Props) {
    if (message.role === "USER") {
        return (
            <>
                <div className={message.failed ? "bubble bubble-user is-failed" : "bubble bubble-user"}>{message.content}</div>
                {message.failed && (
                    <p className="bubble-fail">
                        {message.failed}
                        {onRetry && <button type="button" className="bubble-retry" onClick={onRetry}>다시 보내기</button>}
                    </p>
                )}
            </>
        );
    }

    const note = message.status && message.status !== "ANSWERED" ? NOTE[message.status] : null;
    const tag = note ?? (message.mode === "RESOURCE" ? "자료 참고" : null);

    return (
        <div className="bubble bubble-assistant">
            {tag && <span className={note ? "bubble-tag is-note" : "bubble-tag"}>{tag}</span>}
            <p className="bubble-text">{withMarks(message.content, message.citations)}</p>
            {message.citations.length > 0 && <CitationList citations={message.citations} titleOf={titleOf} />}
        </div>
    );
}
