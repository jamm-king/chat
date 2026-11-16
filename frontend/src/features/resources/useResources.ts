import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../../lib/api";
import { createResource, deleteResource, getResource, listResources, resourceErrorText } from "./resourceApi";
import type { Resource } from "./types";

const POLL_MS = 3000;

const isGone = (error: unknown) => error instanceof ApiError && error.status === 404;

// 자료 목록 + 처리 중인 자료의 상태 확인.
// 레퍼런스 규칙: PROCESSING 인 동안만 상세 조회로 2~10초마다 묻고, COLLECTED · READY · FAILED 가 되면 멈춘다
export function useResources() {
    const [resources, setResources] = useState<Resource[]>([]);
    const [error, setError] = useState("");
    // 수집이 끝나기 전에는 title 이 null 이라, 고를 때 본 페이지 제목을 잠깐 대신 보여 준다
    const [titles, setTitles] = useState<Record<string, string>>({});

    const reload = useCallback(async () => {
        try {
            setResources(await listResources());
            setError("");
        } catch (e) {
            setError(resourceErrorText(e));
        }
    }, []);

    useEffect(() => {
        reload();
    }, [reload]);

    const processing = resources.filter((r) => r.status === "PROCESSING").map((r) => r.resourceId).join(",");

    useEffect(() => {
        if (!processing) return;
        const timer = window.setInterval(async () => {
            const ids = processing.split(",");
            const fresh = await Promise.all(
                ids.map((id) => getResource(id).catch((e) => (isGone(e) ? id : null))),
            );
            const gone = new Set(fresh.filter((f): f is string => typeof f === "string"));
            setResources((prev) =>
                prev
                    .filter((r) => !gone.has(r.resourceId))
                    .map((r) => fresh.find((f): f is Resource => typeof f === "object" && f?.resourceId === r.resourceId) ?? r),
            );
        }, POLL_MS);
        return () => window.clearInterval(timer);
    }, [processing]);

    const add = (resource: Resource, title?: string | null) => {
        setResources((prev) => [resource, ...prev.filter((r) => r.resourceId !== resource.resourceId)]);
        if (title) setTitles((prev) => ({ ...prev, [resource.resourceId]: title }));
    };

    const remove = async (resourceId: string) => {
        try {
            await deleteResource(resourceId);
        } catch (e) {
            if (!isGone(e)) {
                setError(resourceErrorText(e));
                return;
            }
        }
        setResources((prev) => prev.filter((r) => r.resourceId !== resourceId));
        setError("");
    };

    // 같은 연결 · 같은 페이지는 두 번 등록할 수 없어서(RESOURCE_ALREADY_EXISTS), 실패한 자료를 지우고 새로 등록한다
    const retry = async (resource: Resource) => {
        const { connectionId, pageId } = resource.source;
        if (!connectionId || !pageId) return;
        try {
            await deleteResource(resource.resourceId).catch((e) => {
                if (!isGone(e)) throw e;
            });
            const fresh = await createResource(connectionId, pageId);
            const title = resource.title ?? titles[resource.resourceId];
            setResources((prev) => prev.map((r) => (r.resourceId === resource.resourceId ? fresh : r)));
            if (title) setTitles((prev) => ({ ...prev, [fresh.resourceId]: title }));
            setError("");
        } catch (e) {
            setError(resourceErrorText(e));
            reload();
        }
    };

    const titleOf = (resource: Resource) =>
        resource.title ?? titles[resource.resourceId] ?? (resource.status === "PROCESSING" ? "제목 가져오는 중…" : "제목 없는 자료");

    return { resources, error, reload, add, remove, retry, titleOf };
}
