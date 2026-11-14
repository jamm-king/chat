import { failedText, needsReconnect } from "./resourceApi";
import StatusChip from "./StatusChip";
import type { Resource } from "./types";
import "./resources.css";

type Props = {
    resources: Resource[];
    error: string;
    selected: string[];
    canAdd: boolean;
    titleOf: (resource: Resource) => string;
    onToggle: (resourceId: string) => void;
    onAdd: () => void;
    onRemove: (resourceId: string) => void;
    onRetry: (resource: Resource) => void;
    onReconnect: () => void;
};

// 왼쪽 칸의 자료 목록. 준비 완료(READY)된 자료만 골라서 대화에 쓸 수 있다
export default function ResourcePanel(props: Props) {
    const { resources, error, selected, canAdd, titleOf, onToggle, onAdd, onRemove, onRetry, onReconnect } = props;

    const remove = (resource: Resource) => {
        if (window.confirm(`"${titleOf(resource)}" 자료를 지울까요?`)) onRemove(resource.resourceId);
    };

    return (
        <section className="res">
            <div className="res-head">
                <h2>자료</h2>
                <button type="button" className="res-add" onClick={onAdd} disabled={!canAdd}>+ 추가</button>
            </div>
            {!canAdd && <p className="res-hint">노션을 먼저 연결하면 페이지를 자료로 등록할 수 있어요.</p>}
            {error && <p className="res-error">{error}</p>}
            {canAdd && resources.length === 0 && !error && (
                <p className="res-hint">노션 페이지를 등록하면 그 내용을 바탕으로 물어볼 수 있어요.</p>
            )}
            <ul className="res-list">
                {resources.map((resource) => {
                    const ready = resource.status === "READY";
                    const failure = resource.status === "FAILED" ? resource.error : null;
                    return (
                        <li key={resource.resourceId} className="res-item">
                            <label className={ready ? "res-pick" : "res-pick off"} title={titleOf(resource)}>
                                <input
                                    type="checkbox"
                                    checked={selected.includes(resource.resourceId)}
                                    disabled={!ready}
                                    onChange={() => onToggle(resource.resourceId)}
                                />
                                <span className="res-title">{titleOf(resource)}</span>
                            </label>
                            <StatusChip status={resource.status} />
                            <button type="button" className="res-remove" onClick={() => remove(resource)} aria-label="자료 지우기">×</button>
                            {resource.status === "COLLECTED" && (
                                <p className="res-note">수집 완료 · 검색 준비 전이라 대화에는 아직 쓸 수 없어요.</p>
                            )}
                            {resource.status === "FAILED" && (
                                <div className="res-fail">
                                    <p>{failedText(resource)}</p>
                                    {failure?.retryable && (
                                        <button type="button" className="res-link" onClick={() => onRetry(resource)}>다시 등록</button>
                                    )}
                                    {needsReconnect(failure?.code) && (
                                        <button type="button" className="res-link" onClick={onReconnect}>노션 다시 연결</button>
                                    )}
                                </div>
                            )}
                        </li>
                    );
                })}
            </ul>
            {resources.some((r) => r.status === "READY") && (
                <p className="res-hint">
                    {selected.length > 0 ? `고른 자료 ${selected.length}개를 참고해 답해요.` : "고르지 않으면 준비 완료된 자료 전체에서 찾아요."}
                </p>
            )}
        </section>
    );
}
