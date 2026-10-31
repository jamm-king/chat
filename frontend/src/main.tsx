import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles/tokens.css";
import { applyTheme, loadTheme} from "./lib/theme";

applyTheme(loadTheme());

createRoot(document.getElementById("root")!).render(<App />);