from typing import Literal

Operation = Literal["COLLECT", "COLLECT_AND_INDEX"]
JobStatus = Literal["QUEUED", "EXTRACTING", "EXTRACTED", "INDEXING", "SUCCEEDED", "FAILED", "CANCELLED"]
ResourceStatus = Literal["PROCESSING", "COLLECTED", "READY", "FAILED", "DELETED"]
TERMINAL = frozenset({"SUCCEEDED", "FAILED", "CANCELLED"})
