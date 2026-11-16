import { ApiError, apiFetch } from "../../lib/api";
import type { Connection, PageList, Resource } from "./types";

export const listConnections = () =>
    apiFetch<{ connections: Connection[] }>("/api/v1/integrations/notion/connections").then((data) => data.connections);

export const listResources = () => apiFetch<{ resources: Resource[] }>("/api/v1/resources").then((data) => data.resources);

export const getResource = (resourceId: string) => apiFetch<Resource>(`/api/v1/resources/${resourceId}`);

export const createResource = (connectionId: string, pageId: string) =>
    apiFetch<Resource>("/api/v1/resources", { method: "POST", body: JSON.stringify({ connectionId, pageId }) });

export const deleteResource = (resourceId: string) => apiFetch<void>(`/api/v1/resources/${resourceId}`, { method: "DELETE" });

// 검색어가 없으면 노션의 최근 페이지 순. 다음 묶음은 이전 응답의 nextCursor 로
export function searchPages(connectionId: string, query: string, cursor?: string | null) {
    const params = new URLSearchParams({ pageSize: "20" });
    if (query.trim()) params.set("query", query.trim());
    if (cursor) params.set("startCursor", cursor);
    return apiFetch<PageList>(`/api/v1/integrations/notion/connections/${connectionId}/pages?${params}`);
}

// 오류 코드를 화면에 보일 말로. Backend 오류는 message 가 한국어라 표에 없으면 그대로 쓰지만,
// AI 의 자료 처리 실패(resource.error)는 message 가 영어라 표에 없으면 기본 문장을 쓴다 (failedText)
const MESSAGES: Record<string, string> = {
    NOTION_CONNECTION_NOT_FOUND: "노션 연결을 찾을 수 없어요. 노션을 다시 연결해 주세요.",
    NOTION_REAUTHORIZATION_REQUIRED: "노션 권한이 만료됐어요. 노션을 다시 연결해 주세요.",
    NOTION_RATE_LIMITED: "노션 요청이 많아요. 잠시 뒤 다시 해 주세요.",
    RAG_SERVICE_UNAVAILABLE: "AI 서비스에 연결할 수 없어요. 잠시 뒤 다시 해 주세요.",
    RESOURCE_ALREADY_EXISTS: "이미 등록한 페이지예요.",
    RESOURCE_NOT_FOUND: "없는 자료예요. 목록을 새로 불러올게요.",
    VALIDATION_ERROR: "요청 값이 올바르지 않아요.",
    NETWORK: "서버에 연결할 수 없어요.",
    NOTION_ACCESS_DENIED: "이 페이지를 읽을 권한이 없어요. 노션 연결 때 이 페이지를 체크해 주세요.",
    NOTION_PAGE_NOT_FOUND: "페이지가 지워졌거나 연결에 공유되지 않았어요.",
    JOB_LOST: "처리 작업이 사라졌어요. 다시 등록해 주세요.",
    // AI 의 자료 처리 실패 코드 (ai/app/application/use_cases/ingestion.py, notion/client.py)
    CONNECTION_NOT_FOUND: "노션 연결을 찾을 수 없어요. 노션을 다시 연결해 주세요.",
    NOTION_TIMEOUT: "노션 응답이 늦어요. 잠시 뒤 다시 등록해 주세요.",
    NOTION_UNAVAILABLE: "노션에 연결할 수 없어요. 잠시 뒤 다시 등록해 주세요.",
    NOTION_OVERLOADED: "노션이 붐비고 있어요. 잠시 뒤 다시 등록해 주세요.",
    NOTION_INVALID_RESPONSE: "노션에서 받은 내용을 읽지 못했어요. 잠시 뒤 다시 등록해 주세요.",
    NOTION_INVALID_REQUEST: "노션이 이 페이지 요청을 받지 않았어요.",
    INGESTION_TIMEOUT: "처리 시간이 너무 오래 걸렸어요. 잠시 뒤 다시 등록해 주세요.",
    EMBEDDING_FAILED: "검색할 수 있게 준비하다가 실패했어요.",
    INDEX_WRITE_FAILED: "검색 자료를 저장하지 못했어요. 잠시 뒤 다시 등록해 주세요.",
    EMPTY_CONTENT: "페이지에 글이 없어서 등록할 수 없어요.",
    CONTENT_INCOMPLETE: "페이지 내용을 끝까지 가져오지 못했어요.",
    INTERNAL_ERROR: "AI 서버에서 오류가 났어요.",
};

const RECONNECT = new Set(["NOTION_CONNECTION_NOT_FOUND", "CONNECTION_NOT_FOUND", "NOTION_REAUTHORIZATION_REQUIRED"]);

export function resourceErrorText(error: unknown) {
    if (error instanceof ApiError) return MESSAGES[error.code] ?? error.message;
    return "요청을 처리하지 못했어요.";
}

// 실패한 자료의 안내. 표에 없는 코드는 AI 의 영어 message 대신 기본 문장으로
export function failedText(resource: Resource) {
    if (!resource.error) return "처리하지 못했어요.";
    return MESSAGES[resource.error.code] ?? "자료를 처리하지 못했어요.";
}

export const needsReconnect = (code: string | undefined) => code !== undefined && RECONNECT.has(code);

export const errorCode = (error: unknown) => (error instanceof ApiError ? error.code : undefined);
