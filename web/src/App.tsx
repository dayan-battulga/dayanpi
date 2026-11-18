import { Suspense, lazy } from "react";
import { Navigate, Route, Routes } from "react-router";
import { DeskPage } from "@/components/desk/DeskPage";
import { Frame } from "@/components/frame/Frame";
import { RoomPage } from "@/components/room/RoomPage";

// Downloaded only when you open them, so /me doesn't pay for them.
const SettingsPage = lazy(() => import("@/components/settings/SettingsPage").then((module) => ({ default: module.SettingsPage })));
const PiPage = lazy(() => import("@/components/pi/PiPage").then((module) => ({ default: module.PiPage })));
const LoginPage = lazy(() => import("@/components/auth/LoginPage").then((module) => ({ default: module.LoginPage })));
const JoinPage = lazy(() => import("@/components/auth/JoinPage").then((module) => ({ default: module.JoinPage })));
// Its worker brings ONNX Runtime, which no other page loads.
const TrackTestPage = lazy(() => import("@/components/track/TrackTestPage").then((module) => ({ default: module.TrackTestPage })));
const TheirDeskPage = lazy(() => import("@/components/people/TheirDeskPage").then((module) => ({ default: module.TheirDeskPage })));
const TrackPage = lazy(() => import("@/components/track/TrackPage").then((module) => ({ default: module.TrackPage })));
const SignPage = lazy(() => import("@/components/sign/SignPage").then((module) => ({ default: module.SignPage })));

// The Pi serves index.html at /, /me, /pi, /settings, /track, /track/test, /sign, /login and /join/<code>. Sign-in and
// join have their own small frame (no stream, no /api/me: you aren't signed in yet), and so do the tracker and its
// camera test, so nothing else runs on the page next to the models. The desk sign is full screen, with no frame at
// all. Everything else is inside Frame.
export function App() {
  return (
    <Suspense fallback={null}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/join/:code" element={<JoinPage />} />
        <Route path="/track" element={<TrackPage />} />
        <Route path="/track/test" element={<TrackTestPage />} />
        <Route path="/sign" element={<SignPage />} />
        <Route element={<Frame />}>
          <Route path="/" element={<RoomPage />} />
          <Route path="/me" element={<DeskPage />} />
          <Route path="/people/:username" element={<TheirDeskPage />} />
          <Route path="/pi" element={<PiPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          {/* Anything unknown goes to the room, where everyone lands after signing in. */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
