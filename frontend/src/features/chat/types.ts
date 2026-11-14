export type Citation = {
    citationId: string;
    resourceId: string | null;
    title: string | null;
    excerpt: string | null;
    locator: { type: string; url?: string | null } | null;
};

// 세 값 모두 200 OK. 대화 기록 조회 응답에는 status 가 없다
export type AnswerStatus = "ANSWERED" | "INSUFFICIENT_EVIDENCE" | "REFUSED";

export type ChatMessage = {
    messageId: string;
    role: "USER" | "ASSISTANT";
    mode?: "GENERAL" | "RESOURCE";
    content: string;
    citations: Citation[];
    status?: AnswerStatus;
    // 화면에서만 쓰는 값: 보내지 못한 내 질문과 그 까닭
    failed?: string;
};

export type Answer = {
    answerId: string;
    mode: "GENERAL" | "RESOURCE";
    status: AnswerStatus;
    content: string;
    citations: Citation[];
};
