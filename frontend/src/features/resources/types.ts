export type ResourceStatus = "PROCESSING" | "COLLECTED" | "READY" | "FAILED";

export type Resource = {
    resourceId: string;
    title: string | null;
    source: {
        type: "NOTION_PAGE";
        connectionId: string | null;
        pageId: string | null;
        url: string | null;
    };
    parentResourceId: string | null;
    status: ResourceStatus;
    job: { jobId: string; operation: string; status: string } | null;
    error: { code: string; message: string; retryable: boolean } | null;
    createdAt: string;
    updatedAt: string;
};

export type Connection = {
    connectionId: string;
    workspaceName: string | null;
};

export type NotionPage = {
    pageId: string;
    title: string | null;
    url: string | null;
    lastEditedTime: string | null;
};

export type PageList = {
    pages: NotionPage[];
    hasMore: boolean;
    nextCursor: string | null;
};
