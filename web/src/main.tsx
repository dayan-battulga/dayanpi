import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router";
import { App } from "@/App";
import { JoinPage } from "@/components/auth/JoinPage";
import { LoginPage } from "@/components/auth/LoginPage";
import { SettingsPage } from "@/components/settings/SettingsPage";
import "@/index.css";

// The Pi serves index.html at /, /login, /join/<code> and /settings; anything else here is the dashboard.
createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/join/:code" element={<JoinPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<App />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
