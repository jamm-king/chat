import "./notion.css";

type Props = {
    onClose: () => void;
};

export default function NotionGuide({ onClose }: Props) {
    return (
        <div className="guide-backdrop" onClick={onClose}>
            <div className="guide" onClick={(event) => event.stopPropagation()}>
                <div className="guide-top">
                    <h2>노션 연결 방법</h2>
                    <button type="button" className="guide-close" onClick={onClose} aria-label="닫기">✕</button>
                </div>
                <p>단계</p>
            </div>
        </div>
    );
}
