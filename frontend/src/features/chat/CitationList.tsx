import type { Citation } from "./types";

type Props = {
    citations: Citation[];
    titleOf: (resourceId: string | null) => string | null;
};

// 답 아래 출처 카드. 번호는 본문의 [1], [2] 와 같다
export default function CitationList({ citations, titleOf }: Props) {
    return (
        <ol className="cites">
            {citations.map((citation) => {
                const url = citation.locator?.url;
                const title = citation.title ?? titleOf(citation.resourceId) ?? `출처 ${citation.citationId}`;
                return (
                    <li key={citation.citationId} className="cite">
                        <span className="cite-no">{citation.citationId}</span>
                        <div className="cite-body">
                            <span className="cite-title">{title}</span>
                            {citation.excerpt && <span className="cite-excerpt">{citation.excerpt}</span>}
                            {url && (
                                <a className="cite-link" href={url} target="_blank" rel="noreferrer">노션에서 보기</a>
                            )}
                        </div>
                    </li>
                );
            })}
        </ol>
    );
}
