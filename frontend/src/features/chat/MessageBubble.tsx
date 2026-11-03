type Props = {
    role: "USER" | "ASSISTANT";
    content: string;
};

export default function MessageBubble({ role, content }: Props) {
    return (
        <p className={role === "USER" ? "bubble bubble-user" : "bubble bubble-assistant"}>
            {content}
        </p>
    );
}
