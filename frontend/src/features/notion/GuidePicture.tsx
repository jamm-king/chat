type Props = {
    step: number;
};

function Check() {
    return (
        <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="4">
            <path d="M4 12l5 5L20 6" />
        </svg>
    );
}

function ConnectPicture() {
    return (
        <>
            <div className="gp-side">
                <div className="gp-btn">노션 연결</div>
                <div className="gp-line" />
                <div className="gp-line" style={{ width: "70%" }} />
            </div>
            <svg className="gp-cursor" viewBox="0 0 24 24">
                <path d="M4 2l15 9-7 1.5L8.5 20z" />
            </svg>
            <div className="gp-body">
                <div className="gp-line" />
                <div className="gp-line" style={{ width: "80%" }} />
                <div className="gp-line" style={{ width: "60%" }} />
            </div>
        </>
    );
}

function LoginPicture() {
    return (
        <div className="gp-center">
            <div className="gp-login">
                <p>노션 로그인</p>
                <div className="gp-field">이메일</div>
                <div className="gp-field gp-dark">계속</div>
            </div>
        </div>
    );
}

function PagesPicture() {
    const pages = [
        { title: "프로젝트 참고 문서", checked: true },
        { title: "RAG 스터디 정리", checked: true },
        { title: "개인 메모", checked: false },
    ];
    return (
        <>
            <div className="gp-pages">
                {pages.map((page) => (
                    <div key={page.title} className={page.checked ? "gp-page" : "gp-page gp-off"}>
                        <span className={page.checked ? "gp-box on" : "gp-box"}>{page.checked && <Check />}</span>
                        {page.title}
                    </div>
                ))}
            </div>
            <div className="gp-allow">허용</div>
        </>
    );
}

function DonePicture() {
    return (
        <div className="gp-center">
            <div className="gp-done">
                <div className="gp-ring">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M5 12.5l4.2 4.2L19 7" />
                    </svg>
                </div>
                연결됐어요
            </div>
        </div>
    );
}

const PICTURES = [ConnectPicture, LoginPicture, PagesPicture, DonePicture];

export default function GuidePicture({ step }: Props) {
    const Picture = PICTURES[step];
    return (
        <div className="gp" aria-hidden="true">
            <div className="gp-win">
                <div className="gp-bar">
                    <i />
                    <i />
                    <i />
                </div>
                <Picture />
            </div>
        </div>
    );
}
