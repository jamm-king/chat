import type { ResourceStatus } from "./types";

// 레퍼런스 3.1 Resource Status 의 "Frontend 표시"
const LABEL: Record<ResourceStatus, string> = {
    PROCESSING: "처리 중",
    COLLECTED: "수집 완료",
    READY: "준비 완료",
    FAILED: "실패",
};

export default function StatusChip({ status }: { status: ResourceStatus }) {
    return <span className={`chip chip-${status.toLowerCase()}`}>{LABEL[status]}</span>;
}
