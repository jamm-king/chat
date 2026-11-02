import { Navigate } from "react-router-dom";
import { getAccessToken } from "../lib/auth";

export default function ChatPage() {
    if (!getAccessToken()) {
        return <Navigate to="/login" replace />;
    }
    return <h1>대화</h1>;
}
