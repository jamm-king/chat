import { ApiError, apiFetch } from "../../lib/api";
import type { Answer, ChatMessage } from "./types";

export const MAX_LENGTH = 4000;

export const loadMessages = () => apiFetch<{ messages: ChatMessage[] }>("/api/v1/messages").then((data) => data.messages);

// AUTO: 자료가 필요한 질문인지는 RAG 시스템이 판단. 자료를 골랐으면 그 자료만, 안 골랐으면 READY 자료 전체가 대상
export function sendMessage(message: string, resourceIds: string[]) {
    const body = resourceIds.length > 0 ? { mode: "AUTO", message, resourceIds } : { mode: "AUTO", message };
    return apiFetch<Answer>("/api/v1/messages", { method: "POST", body: JSON.stringify(body) });
}

export const clearMessages = () => apiFetch<void>("/api/v1/messages", { method: "DELETE" });

// 레퍼런스 4.1.1 Error Response
const MESSAGES: Record<string, string> = {
    ANSWER_IN_PROGRESS: "앞 질문의 답을 아직 만들고 있어요. 끝난 뒤 다시 보내 주세요.",
    RESOURCE_NOT_READY: "고른 자료 중에 아직 준비되지 않은 자료가 있어요.",
    RESOURCE_NOT_FOUND: "고른 자료 중에 지워진 자료가 있어요. 자료 목록을 새로 불러왔어요.",
    RESOURCE_SCOPE_CHANGED: "답을 만드는 동안 자료가 바뀌었어요. 자료 목록을 새로 불러왔으니 다시 보내 주세요.",
    VALIDATION_ERROR: `질문은 1~${MAX_LENGTH.toLocaleString()}자로 써 주세요.`,
    RAG_SERVICE_UNAVAILABLE: "AI 답변을 만들지 못했어요. 잠시 뒤 다시 보내 주세요.",
    NETWORK: "서버에 연결할 수 없어요.",
};

// 자료 상태가 화면과 달라졌다는 뜻이라 자료 목록을 다시 받아야 하는 오류
const RESOURCE_CODES = new Set(["RESOURCE_NOT_READY", "RESOURCE_NOT_FOUND", "RESOURCE_SCOPE_CHANGED"]);

export const isResourceError = (error: unknown) => error instanceof ApiError && RESOURCE_CODES.has(error.code);

// 답을 만드는 동안 대화 기록이 지워짐. 이 답은 저장되지 않으니 화면에서 그냥 버린다
export const isCleared = (error: unknown) => error instanceof ApiError && error.code === "CONVERSATION_CLEARED";

export function messageErrorText(error: unknown) {
    if (error instanceof ApiError) return MESSAGES[error.code] ?? "답변을 받지 못했어요.";
    return "답변을 받지 못했어요.";
}
