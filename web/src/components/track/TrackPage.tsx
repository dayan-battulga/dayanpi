import { Video, VideoOff, type LucideIcon } from "lucide-react";
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { ThemeToggle } from "@/components/shared/ThemeToggle";
import { measureMemory, openCamera, type CameraProblem } from "@/components/track/checkRuns";
import { useNow } from "@/hooks/useNow";
import { formatClock } from "@/lib/format";
import { fetchJson, request, sendToLogin } from "@/lib/http";
import { STATE_COPY } from "@/lib/timeline";
import { describeLoad, type TrackBox, type Tracked, type TrackerReply } from "@/lib/track";
import { LOW_BATTERY, type PaceReason } from "@/lib/trackPace";
import type { FocusState, FocusStatus } from "@/lib/types";

// /track (Track.dc.html): this browser's camera feeds the viewer's own desk. The camera only starts on a click, the
// models run in a worker (tracker.worker.ts) that sends the Pi each check's numbers, and the video never leaves this
// computer. Plain on purpose: no motion beyond the live dot, since the models need the CPU.

type Step = "ask" | "running" | "paused" | "problem";
type ProblemKind = CameraProblem | "refused" | "failed";

interface Problem {
  title: string;
  text: string;
  toSettings: boolean;
}

const PROBLEMS: Record<ProblemKind, Problem> = {
  denied: { title: "Camera is blocked", text: "Click the camera icon in the address bar, allow it, then reload.", toSettings: false },
  missing: { title: "No camera found", text: "Check it's plugged in and turned on, then try again.", toSettings: false },
  busy: { title: "The camera is busy", text: "Another app is using it (Zoom, FaceTime, Photo Booth…). Close it, then try again.", toSettings: false },
  chrome: { title: "This needs Chrome", text: "Open this page in Chrome. Other browsers can't hand the camera to the tracker.", toSettings: false },
  refused: { title: "Your desk uses the Pi's cameras", text: "Pick This browser's camera in Settings → Camera to track from here.", toSettings: true },
  failed: { title: "The tracker stopped", text: "The models stopped running. Try again, or reload the page.", toSettings: false },
};
const MEMORY_EVERY_MS = 60_000;
const DOT_COLORS: Record<FocusState, string> = { working: "var(--work)", phone: "var(--phone)", away: "var(--away)", unknown: "var(--muted)" };

interface TrackCardProps {
  icon: LucideIcon;
  isHot?: boolean;
  title: string;
  text: string;
  children: ReactNode;
}

function TrackCard({ icon: Icon, isHot = false, title, text, children }: TrackCardProps) {
  return (
    <div className="track-ask">
      <span className={isHot ? "track-icon is-hot" : "track-icon"} aria-hidden="true">
        <Icon size={24} strokeWidth={1.8} />
      </span>
      <h1 className="track-title">{title}</h1>
      <p className="track-text">{text}</p>
      {children}
    </div>
  );
}

// Low and not plugged in. Chrome has a battery to ask; a desktop without one is never low.
function isLowBattery(battery: BatteryManager | null): boolean {
  const low = battery !== null && !battery.charging && battery.level < LOW_BATTERY;
  return low;
}

export function TrackPage() {
  const [step, setStep] = useState<Step>("ask");
  const [problem, setProblem] = useState<Problem>(PROBLEMS.failed);
  const [tracked, setTracked] = useState<{ tracked: Tracked; at: number } | null>(null);
  const [check, setCheck] = useState<{ ms: number; boxes: TrackBox[]; reason: PaceReason } | null>(null);
  const [backend, setBackend] = useState<string | null>(null);
  const [memory, setMemory] = useState<number | null>(null);
  const [preview, setPreview] = useState<MediaStream | null>(null);
  const [ratio, setRatio] = useState(16 / 9);
  const tracks = useRef<MediaStreamTrack[]>([]);
  const worker = useRef<Worker | null>(null);
  const video = useRef<HTMLVideoElement | null>(null);
  const now = useNow();

  const stopTracking = () => {
    worker.current?.terminate();
    worker.current = null;
    tracks.current.forEach((track) => track.stop());
    tracks.current = [];
    setPreview(null);
    setCheck(null);
  };
  const showProblem = (kind: ProblemKind) => {
    stopTracking();
    setProblem(PROBLEMS[kind]);
    setStep("problem");
  };
  const keepTracked = (answer: Tracked) => setTracked({ tracked: answer, at: Date.now() / 1000 });

  const handleReply = (reply: TrackerReply) => {
    if (reply.type === "ready") {
      setBackend(reply.backend);
    } else if (reply.type === "check") {
      setCheck({ ms: reply.ms, boxes: reply.boxes, reason: reply.pace.reason });
    } else if (reply.type === "tracked") {
      keepTracked(reply);
    } else if (reply.type === "signed-out") {
      sendToLogin();
    } else {
      showProblem(reply.type === "refused" ? "refused" : "failed");
    }
  };

  const startTracking = async () => {
    const opened = await openCamera();
    if (opened.stream === null) {
      showProblem(opened.problem ?? "missing");
    } else {
      const [track] = opened.stream.getVideoTracks();
      const copy = track.clone();
      const { width, height } = track.getSettings();
      const frames = new (MediaStreamTrackProcessor as NonNullable<typeof MediaStreamTrackProcessor>)({ track: copy }).readable;
      const battery = (await navigator.getBattery?.().catch(() => null)) ?? null;
      const started = new Worker(new URL("./tracker.worker.ts", import.meta.url), { type: "module", name: "tracker" });
      started.onmessage = (event: MessageEvent<TrackerReply>) => handleReply(event.data);
      started.onerror = () => showProblem("failed");
      started.postMessage({ type: "start", frames, lowBattery: isLowBattery(battery) }, [frames]);
      if (battery !== null) {
        // Assigned, not added: Chrome hands back the same battery on every Resume.
        battery.onlevelchange = battery.onchargingchange = () => started.postMessage({ type: "battery", low: isLowBattery(battery) });
      }
      worker.current = started;
      tracks.current = [track, copy];
      setRatio(width && height ? width / height : 16 / 9);
      setPreview(opened.stream);
      setStep("running");
    }
  };

  const pauseTracking = async () => {
    stopTracking();
    setStep("paused");
    const reply = await request<Tracked>("POST", "/api/track/pause", {});
    if (reply.body !== null) {
      keepTracked(reply.body);
    }
  };

  // The desk's state before the first check lands, and whether it's waiting on a pause or on the Pi's cameras.
  useEffect(() => {
    let current = true;
    fetchJson<FocusStatus>("/api/focus").then((focus) => {
      if (current && focus !== null) {
        keepTracked({ state: focus.state, seconds_in_state: focus.seconds_in_state, paused: focus.camera_paused ?? false });
        if (focus.camera_source === "pi") {
          setProblem(PROBLEMS.refused);
        }
        setStep((shown) => (shown !== "ask" ? shown : focus.camera_source === "pi" ? "problem" : focus.camera_paused ? "paused" : "ask"));
      }
    });
    return () => {
      current = false;
      worker.current?.terminate();
      tracks.current.forEach((track) => track.stop());
    };
  }, []);

  useEffect(() => {
    if (video.current !== null) {
      video.current.srcObject = preview;
    }
  }, [preview]);

  // The page and its workers. Chrome answers at its next garbage collection, so it lags a little.
  useEffect(() => {
    let current = true;
    const measure = () => void measureMemory().then((bytes) => current && bytes !== null && setMemory(bytes));
    const timer = step === "running" ? window.setInterval(measure, MEMORY_EVERY_MS) : undefined;
    if (step === "running") {
      measure();
    }
    return () => {
      current = false;
      window.clearInterval(timer);
    };
  }, [step]);

  const state = tracked?.tracked.state ?? "unknown";
  const seconds = tracked === null ? 0 : tracked.tracked.seconds_in_state + Math.max(0, now - tracked.at);

  return (
    <div className="track">
      <header className="topbar topbar-auth">
        <span className="wordmark">dayanpi</span>
        <div className="topbar-end">
          <a className="track-back" href="/">
            Back to the room
          </a>
          <ThemeToggle />
        </div>
      </header>
      <main className="track-main">
        {step === "ask" && (
          <TrackCard icon={Video} title="Turn on your camera" text="Your video stays on this computer. Only the numbers go to the room.">
            <button type="button" className="button button-ink button-block track-ask-button" onClick={() => void startTracking()}>
              Allow camera
            </button>
          </TrackCard>
        )}
        {step === "paused" && (
          <TrackCard icon={Video} title="Tracking is paused" text="The camera's off, and your desk says paused until you resume.">
            <button type="button" className="button button-ink button-block track-ask-button" onClick={() => void startTracking()}>
              Resume
            </button>
          </TrackCard>
        )}
        {step === "problem" && (
          <TrackCard icon={VideoOff} isHot title={problem.title} text={problem.text}>
            {problem.toSettings ? (
              <a className="button button-line button-block track-ask-button" href="/settings">
                Open Settings
              </a>
            ) : (
              <button type="button" className="button button-line button-block track-ask-button" onClick={() => void startTracking()}>
                Try again
              </button>
            )}
          </TrackCard>
        )}
        {step === "running" && (
          <div className="track-running" style={{ "--ratio": ratio } as CSSProperties}>
            <div className="track-preview">
              <video ref={video} className="track-video" autoPlay muted playsInline />
              {(check?.boxes ?? []).map((box, index) => (
                <span
                  key={`${box.kind}-${index}`}
                  className="track-box"
                  data-kind={box.kind}
                  style={{ left: `${box.x * 100}%`, top: `${box.y * 100}%`, width: `${box.width * 100}%`, height: `${box.height * 100}%` }}
                />
              ))}
              <span className="track-chip">Only you see this</span>
            </div>
            <div className="track-row">
              <p className="track-state" style={{ "--pulse": DOT_COLORS[state] } as CSSProperties}>
                <span className="track-dot" />
                {STATE_COPY[state].label}
                {state !== "unknown" && <span className="track-timer">{formatClock(seconds)}</span>}
              </p>
              <button type="button" className="button button-line track-button" onClick={() => void pauseTracking()}>
                Pause
              </button>
            </div>
            <p className="track-note">Keep this tab open. It keeps going behind other tabs and windows.</p>
            <p className="track-load">{describeLoad(check?.ms ?? null, memory, backend, check?.reason ?? "normal")}</p>
          </div>
        )}
      </main>
    </div>
  );
}
