import { Navigate, Route, Routes} from "react-router-dom";
import ThemeToggle from "./components/ThemeToggle";
import LoginPage from "./pages/LoginPage";
import SignupPage from "./pages/SignupPage"
import ChatPage from "./pages/ChatPage";
import NotionCallbackPage from "./pages/NotionCallbackPage";


export default function App() {
  return(<>
   <ThemeToggle/>
   <Routes>
      <Route path="/" element={<Navigate to="/login" replace/>}/>
      <Route path ="/login" element={<LoginPage/>}/>
      <Route path ="/signup" element={<SignupPage/>}/>
      <Route path="/chat" element={<ChatPage/>}/>
      <Route path="/notion/callback" element={<NotionCallbackPage/>}/>

   </Routes>
  </>);
}