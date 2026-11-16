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

// 레퍼런스(3.1 · 3.2.4)의 오류 코드를 화면에 보일 말로. Backend 의 message 는 영어라 코드로 고른다
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
};

const RECONNECT = new Set(["NOTION_CONNECTION_NOT_FOUND", "NOTION_REAUTHORIZATION_REQUIRED"]);

export function resourceErrorText(error: unknown) {
    if (error instanceof ApiError) return MESSAGES[error.code] ?? error.message;
    return "요청을 처리하지 못했어요.";
}

// 실패한 자료는 RAG 시스템이 준 메시지를 그대로 보이되, 아는 코드는 한국어 안내로
export function failedText(resource: Resource) {
    if (!resource.error) return "처리하지 못했어요.";
    return MESSAGES[resource.error.code] ?? resource.error.message;
}

export const needsReconnect = (code: string | undefined) => code !== undefined && RECONNECT.has(code);

export const errorCode = (error: unknown) => (error instanceof ApiError ? error.code : undefined);
