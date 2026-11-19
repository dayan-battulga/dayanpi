import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AuthFrame } from "@/components/auth/AuthFrame";
import { openCamera, type CameraProblem } from "@/components/track/cameraTracker";
import { describeDevice, findBackends, runSpeedTest, startCheckWorker, type CheckWorker } from "@/components/track/checkRuns";
import { sendToLogin } from "@/lib/http";
import {
  CHECKS_PER_BACKEND,
  describeLoop,
  describeSpeed,
  formatReport,
  splitSegments,
  summarizeChecks,
  WARMUP_CHECKS,
  type BackendChoice,
  type CheckRecord,
  type GapRecord,
  type Loop,
  type Place,
  type SpeedResult,
} from "@/lib/trackTest";
import { loadModel, MODEL_NAMES } from "@/lib/vision/models";

// /track/test: can this laptop run the Pi's models fast enough, in the background too? The camera only starts on
// a click, nothing is sent anywhere or kept, and the numbers end up in a box to copy. No mockup: it's a tool, in
// the sign-in page's frame.

type Stage = "idle" | "starting" | "speed" | "between" | "background" | "done";

const CAMERA_PROBLEMS: Record<CameraProblem, string> = {
  chrome: "This test needs Chrome: this browser can't hand camera frames to a background worker.",
  denied: "The camera is blocked. Click the camera icon in the address bar, allow it, then press Start again.",
  missing: "No camera found. Check it's plugged in and turned on, then press Start again.",
  busy: "Another app is using the camera. Close it (Zoom, FaceTime, Photo Booth...), then press Start again.",
};
const LOOPS: Loop[] = ["page", "worker"];
const BACKGROUND_MAX_MS = 20 * 60_000;
const PHONE_MIN = 0.5; // the tracker's

function describeCheck(choice: BackendChoice, record: CheckRecord, count: number): string {
  const phone = record.phone >= PHONE_MIN ? `phone ${record.phone.toFixed(2)}` : "no phone";
  const seen = record.fresh ? `person ${record.person.toFixed(2)} · ${phone}` : "no new frame";
  const text = `${choice.label} · check ${count} of ${WARMUP_CHECKS + CHECKS_PER_BACKEND} · ${Math.round(record.ms)} ms · ${seen}${record.sign ? " · peace sign!" : ""}`;
  return text;
}

function pickFastest(results: SpeedResult[]): BackendChoice {
  const working = results.filter((result) => result.problem === null && result.records.length > WARMUP_CHECKS);
  const fastest = working.reduce<SpeedResult | null>((best, result) => (best === null || summarizeChecks(result.records).medianMs < summarizeChecks(best.records).medianMs ? result : best), null);
  const choice = (fastest ?? results[results.length - 1]).choice;
  return choice;
}

function describeLastGap(gaps: GapRecord[], loop: Loop): string {
  const mine = gaps.filter((gap) => gap.loop === loop);
  const last = mine.length > 1 ? `, last gap ${((mine[mine.length - 1].at - mine[mine.length - 2].at) / 1000).toFixed(2)} s` : "";
  const text = `${describeLoop(loop)}: ${mine.length} checks${last}`;
  return text;
}

export function TrackTestPage() {
  const [stage, setStage] = useState<Stage>("idle");
  const [problem, setProblem] = useState<string | null>(null);
  const [device, setDevice] = useState<string[]>([]);
  const [speed, setSpeed] = useState<SpeedResult[]>([]);
  const [live, setLive] = useState<string | null>(null);
  const [gaps, setGaps] = useState<GapRecord[]>([]);
  const [background, setBackground] = useState<BackendChoice | null>(null);
  const [popOut, setPopOut] = useState<Window | null>(null);
  const [copied, setCopied] = useState(false);
  const camera = useRef<MediaStream | null>(null);
  const runs = useRef<CheckWorker[]>([]);
  // Read when a check lands, outside a render.
  const isPoppedOut = useRef(false);

  const stopEverything = () => {
    runs.current.forEach((run) => run.stop());
    runs.current = [];
    camera.current?.getTracks().forEach((track) => track.stop());
    camera.current = null;
  };

  useEffect(() => {
    return () => {
      stopEverything();
    };
  }, []);

  const runSpeedTests = async (stream: MediaStream) => {
    const track = stream.getVideoTracks()[0];
    const { choices, gpu } = await findBackends();
    setDevice(await describeDevice(track, gpu));
    setStage("speed");
    const results: SpeedResult[] = [];
    for (const choice of choices) {
      setLive(`${choice.label} · loading the models`);
      results.push(await runSpeedTest(track, choice, (record, count) => setLive(describeCheck(choice, record, count))));
      setSpeed([...results]);
    }
    setLive(null);
    setStage("between");
  };

  const startTest = async () => {
    setProblem(null);
    setStage("starting");
    const opened = await openCamera();
    if (opened.stream === null) {
      setProblem(CAMERA_PROBLEMS[opened.problem ?? "missing"]);
      setStage("idle");
    } else {
      camera.current = opened.stream;
      try {
        // Into Cache Storage once, here, where a 401 can go to the sign-in; the workers read them from there.
        await Promise.all(Object.values(MODEL_NAMES).map(loadModel));
        await runSpeedTests(opened.stream);
      } catch (error) {
        if ((error as Error).cause === 401) {
          sendToLogin();
        }
        stopEverything();
        setProblem(`Couldn't get the models: ${(error as Error).message}`);
        setStage("idle");
      }
    }
  };

  const findPlace = (): Place => (document.visibilityState === "visible" ? "visible" : isPoppedOut.current ? "pop-out" : "hidden");

  const finishBackground = () => {
    stopEverything();
    popOut?.close();
    setStage("done");
  };

  const startBackground = () => {
    const track = camera.current?.getVideoTracks()[0];
    const choice = pickFastest(speed);
    if (track !== undefined) {
      setBackground(choice);
      setStage("background");
      runs.current = LOOPS.map((loop) =>
        startCheckWorker(track, choice, loop, (reply) => {
          if (reply.type === "check") {
            setGaps((list) => [...list, { loop, place: findPlace(), at: reply.at, fresh: reply.fresh }]);
          } else if (reply.type === "failed") {
            setProblem(`${describeLoop(loop)} failed: ${reply.message}`);
          }
        }),
      );
      const cap = setTimeout(() => runs.current.length > 0 && finishBackground(), BACKGROUND_MAX_MS);
      runs.current.push({ stop: () => clearTimeout(cap) });
    }
  };

  const openPopOut = async () => {
    const opened = await window.documentPictureInPicture?.requestWindow({ width: 340, height: 120 });
    if (opened !== undefined) {
      isPoppedOut.current = true;
      setPopOut(opened);
      opened.addEventListener("pagehide", () => {
        isPoppedOut.current = false;
        setPopOut(null);
      });
    }
  };

  const report = formatReport({ device, speed, background: background === null ? null : { choice: background, segments: splitSegments(gaps) } });

  const copyReport = async () => {
    try {
      await navigator.clipboard.writeText(report);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setProblem("Couldn't copy. Select the text in the box and copy it by hand.");
    }
  };

  return (
    <AuthFrame className="track-card">
      <h1 className="auth-title">Camera test</h1>
      <p className="auth-intro">
        Checks whether this laptop can run the desk camera's models fast enough, the same way the Pi does. The camera only turns on when you press Start.
        Nothing is sent or saved: the numbers stay on this page until you copy them.
      </p>
      {problem !== null && (
        <p className="form-note" data-tone="error" role="alert">
          {problem}
        </p>
      )}
      {stage === "idle" && (
        <button type="button" className="button button-ink button-block" onClick={() => void startTest()}>
          Start the test
        </button>
      )}
      {stage === "starting" && <p className="form-note">Turning on the camera and getting the models (about 18 MB the first time)…</p>}

      {(stage === "speed" || speed.length > 0) && (
        <section className="track-section" aria-labelledby="track-speed">
          <h2 id="track-speed" className="track-heading">
            Speed
          </h2>
          <p className="form-note">
            Each way this browser can run the models, one check a second, about a minute each. Keep this tab in front and sit at your desk like you normally
            would.
          </p>
          {live !== null && (
            <p className="form-note track-live" aria-live="polite">
              {live}
            </p>
          )}
          {speed.length > 0 && (
            <ul className="track-rows">
              {speed.map((result) => (
                <li key={result.choice.backend}>
                  <strong>{result.choice.label}</strong> {describeSpeed(result)}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {(stage === "between" || stage === "background") && (
        <section className="track-section" aria-labelledby="track-background">
          <h2 id="track-background" className="track-heading">
            In the background
          </h2>
          <ol className="track-steps">
            <li>Press Start below and leave this tab in front for a minute.</li>
            <li>Switch to another tab for 6 minutes, then come back.</li>
            <li>Minimize the window for 2 minutes, then come back.</li>
            {window.documentPictureInPicture !== undefined && <li>Press Pop out, switch to another tab or app for 2 minutes, then come back.</li>}
            <li>Press Stop.</li>
          </ol>
          <div className="track-actions">
            {stage === "between" ? (
              <button type="button" className="button button-ink" onClick={startBackground}>
                Start
              </button>
            ) : (
              <>
                {window.documentPictureInPicture !== undefined && (
                  <button type="button" className="button button-line" onClick={() => void openPopOut()} disabled={popOut !== null}>
                    Pop out
                  </button>
                )}
                <button type="button" className="button button-ink" onClick={finishBackground}>
                  Stop
                </button>
              </>
            )}
          </div>
          {stage === "background" && (
            <p className="form-note track-live" aria-live="polite">
              {LOOPS.map((loop) => describeLastGap(gaps, loop)).join(" · ")}
            </p>
          )}
        </section>
      )}

      {device.length > 0 && (
        <section className="track-section" aria-labelledby="track-results">
          <h2 id="track-results" className="track-heading">
            Results
          </h2>
          <p className="form-note">{stage === "done" ? "All done. Copy this and send it back." : "This fills in as the test runs."}</p>
          <pre className="track-results">{report}</pre>
          <div className="track-actions">
            <button type="button" className="button button-line" onClick={() => void copyReport()}>
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
        </section>
      )}

      {popOut !== null &&
        createPortal(
          <div style={{ font: "14px system-ui, sans-serif", padding: 12, lineHeight: 1.5 }}>
            <strong>dayanpi camera test</strong>
            {LOOPS.map((loop) => (
              <div key={loop}>{describeLastGap(gaps, loop)}</div>
            ))}
          </div>,
          popOut.document.body,
        )}
    </AuthFrame>
  );
}
