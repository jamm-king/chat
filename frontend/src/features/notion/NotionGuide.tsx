import { useEffect, useState } from "react";
import GuidePicture from "./GuidePicture";
import "./notion.css";

type Props = {
    onClose: () => void;
    onConnect?: () => void;
};

type Step = {
    title: string;
    desc: string;
    tip?: string;
};

const STEPS: Step[] = [
    {
        title: "노션 연결 단추를 눌러요",
        desc: "왼쪽 칸 맨 위의 버튼을 눌러주세요.",
    },
    {
        title: "노션 계정으로 로그인해주세요",
        desc: "이미 로그인이 되어있는 계정은 자동으로 연결됩니다.",
    },
    {
        title: "사용할 페이지를 체크하고 허용해주세요",
        desc: "체크한 페이지의 하위 페이지도 자료로 사용 가능해요.",
        tip: "누락된 페이지는 나중에 다시 연결해서 사용할 수 있습니다.",
    },
    {
        title: "사이트로 돌아와 확인해주세요",
        desc: "\"연결됐어요\"가 보이면 \"대화 화면으로 돌아가기\"를 눌러주세요. 왼쪽 칸에 연결된 워크스페이스 이름을 확인해주세요.",
        tip: "같은 브라우저에서 10분 안에 끝내야 합니다. 시간이 지나면 재연결이 필요합니다.",
    },
];

export default function NotionGuide({ onClose, onConnect }: Props) {
    const [step, setStep] = useState(0);
    const current = STEPS[step];
    const isLast = step === STEPS.length - 1;

    useEffect(() => {
        const closeOnEscape = (event: KeyboardEvent) => {
            if (event.key === "Escape") onClose();
        };
        window.addEventListener("keydown", closeOnEscape);
        return () => window.removeEventListener("keydown", closeOnEscape);
    }, [onClose]);

    const finish = () => {
        onClose();
        onConnect?.();
    };

    return (
        <div className="guide-backdrop" onClick={onClose}>
            <div
                className="guide"
                role="dialog"
                aria-modal="true"
                aria-labelledby="guide-heading"
                onClick={(event) => event.stopPropagation()}
            >
                <div className="guide-top">
                    <h2 id="guide-heading">노션 연결 방법</h2>
                    <button type="button" className="guide-close" onClick={onClose} aria-label="닫기">✕</button>
                </div>
                <div className="guide-dots">
                    {STEPS.map((_, index) => (
                        <span key={index} className={index <= step ? "on" : ""} />
                    ))}
                </div>
                <GuidePicture step={step} />
                <p className="guide-step">{step + 1}단계</p>
                <p className="guide-title">{current.title}</p>
                <p className="guide-desc">{current.desc}</p>
                {current.tip && <p className="guide-tip">{current.tip}</p>}
                <div className="guide-btns">
                    <button type="button" className="guide-prev" onClick={() => setStep(step - 1)} disabled={step === 0}>
                        이전
                    </button>
                    {isLast ? (
                        <button type="button" className="guide-next" onClick={finish}>
                            {onConnect ? "지금 연결하기" : "닫기"}
                        </button>
                    ) : (
                        <button type="button" className="guide-next" onClick={() => setStep(step + 1)}>
                            다음
                        </button>
                    )}
                </div>
            </div>
        </div>
    );
}
