import { useEffect, useState } from "react";
import { createResource, errorCode, needsReconnect, resourceErrorText, searchPages } from "./resourceApi";
import type { Connection, NotionPage, Resource } from "./types";
import "./resources.css";

type Props = {
    connections: Connection[];
    resources: Resource[];
    onAdded: (resource: Resource, title: string | null) => void;
    onReconnect: () => void;
    onClose: () => void;
};

const SEARCH_DELAY_MS = 400;

// 노션 페이지 검색 → 고르기 → 등록 (레퍼런스 3.2.4 · 3.1.1). 한 번에 한 페이지씩 등록하고, 창은 닫을 때까지 열려 있다
export default function PagePicker({ connections, resources, onAdded, onReconnect, onClose }: Props) {
    const [connectionId, setConnectionId] = useState(connections[0]?.connectionId ?? "");
    const [query, setQuery] = useState("");
    const [pages, setPages] = useState<NotionPage[]>([]);
    const [cursor, setCursor] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState("");
    const [code, setCode] = useState<string | undefined>();
    const [adding, setAdding] = useState("");

    const registered = new Set(
        resources.filter((r) => r.source.connectionId === connectionId).map((r) => r.source.pageId),
    );

    const fail = (e: unknown) => {
        setError(resourceErrorText(e));
        setCode(errorCode(e));
    };

    useEffect(() => {
        if (!connectionId) return;
        let stale = false;
        const timer = window.setTimeout(async () => {
            setLoading(true);
            try {
                const data = await searchPages(connectionId, query);
                if (stale) return;
                setPages(data.pages);
                setCursor(data.hasMore ? data.nextCursor : null);
                setError("");
                setCode(undefined);
            } catch (e) {
                if (!stale) fail(e);
            } finally {
                if (!stale) setLoading(false);
            }
        }, SEARCH_DELAY_MS);
        return () => {
            stale = true;
            window.clearTimeout(timer);
        };
    }, [connectionId, query]);

    useEffect(() => {
        const closeOnEscape = (event: KeyboardEvent) => {
            if (event.key === "Escape") onClose();
        };
        window.addEventListener("keydown", closeOnEscape);
        return () => window.removeEventListener("keydown", closeOnEscape);
    }, [onClose]);

    const more = async () => {
        if (!cursor) return;
        setLoading(true);
        try {
            const data = await searchPages(connectionId, query, cursor);
            setPages((prev) => [...prev, ...data.pages]);
            setCursor(data.hasMore ? data.nextCursor : null);
        } catch (e) {
            fail(e);
        } finally {
            setLoading(false);
        }
    };

    const add = async (page: NotionPage) => {
        setAdding(page.pageId);
        try {
            onAdded(await createResource(connectionId, page.pageId), page.title);
            setError("");
            setCode(undefined);
        } catch (e) {
            fail(e);
        } finally {
            setAdding("");
        }
    };

    return (
        <div className="pick-backdrop" onClick={onClose}>
            <div className="pick" role="dialog" aria-modal="true" aria-labelledby="pick-heading" onClick={(event) => event.stopPropagation()}>
                <div className="pick-top">
                    <h2 id="pick-heading">노션 페이지 고르기</h2>
                    <button type="button" className="pick-close" onClick={onClose} aria-label="닫기">✕</button>
                </div>
                {connections.length > 1 && (
                    <select className="pick-field" value={connectionId} onChange={(event) => setConnectionId(event.target.value)}>
                        {connections.map((c) => (
                            <option key={c.connectionId} value={c.connectionId}>{c.workspaceName ?? "이름 없는 워크스페이스"}</option>
                        ))}
                    </select>
                )}
                <input
                    className="pick-field"
                    value={query}
                    maxLength={1000}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="페이지 제목으로 찾기 (비우면 최근 페이지)"
                    autoFocus
                />
                {error && (
                    <p className="res-error">
                        {error}
                        {needsReconnect(code) && (
                            <button type="button" className="res-link" onClick={onReconnect}>노션 다시 연결</button>
                        )}
                    </p>
                )}
                <ul className="pick-list">
                    {pages.map((page) => {
                        const done = registered.has(page.pageId);
                        return (
                            <li key={page.pageId} className="pick-item">
                                <div className="pick-info">
                                    <span className="pick-title">{page.title || "제목 없는 페이지"}</span>
                                    {page.lastEditedTime && <span className="pick-date">{page.lastEditedTime.slice(0, 10)} 수정</span>}
                                </div>
                                <button type="button" className="pick-add" onClick={() => add(page)} disabled={done || adding !== ""}>
                                    {done ? "등록됨" : adding === page.pageId ? "등록 중…" : "등록"}
                                </button>
                            </li>
                        );
                    })}
                </ul>
                {loading && <p className="res-hint">불러오는 중…</p>}
                {!loading && pages.length === 0 && !error && <p className="res-hint">찾은 페이지가 없어요. 노션 연결 때 체크한 페이지만 보여요.</p>}
                {cursor && !loading && <button type="button" className="pick-more" onClick={more}>더 보기</button>}
            </div>
        </div>
    );
}
