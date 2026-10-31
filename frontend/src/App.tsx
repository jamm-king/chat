import { Link, Navigate, Route, Routes} from "react-router-dom";
import ThemeToggle from "./components/ThemeToggle";
import LoginPage from "./pages/LoginPage";
import SignupPage from "./pages/SignupPage";

export default function App() {
  return(<>
    <nav>
      <Link to="/login">로그인</Link>
      <Link to="/signup">회원가입</Link>
    </nav>
   <ThemeToggle/>
   <Routes>
      <Route path="/" element={<Navigate to="/login" replace/>}/>
      <Route path ="/login" element={<LoginPage/>}/>
      <Route path ="/signup" element={<SignupPage/>}/>
   </Routes>
  </>);
}