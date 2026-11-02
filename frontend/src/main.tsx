import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./styles/tokens.css";
import { applyTheme, loadTheme} from "./lib/theme";

applyTheme(loadTheme());

createRoot(document.getElementById("root")!).render(
<BrowserRouter>
 <App/>
</BrowserRouter>)