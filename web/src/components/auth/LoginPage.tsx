import { useRef, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router";
import { AuthFrame } from "@/components/auth/AuthFrame";
import { Field } from "@/components/shared/Field";
import { FormNote, buildErrorNote, type Note } from "@/components/shared/FormNote";
import { useNow } from "@/hooks/useNow";
import { readSafeNext, request } from "@/lib/http";
import { loadPage } from "@/lib/navigation";

// SPEC's shake: replayed on every miss, which el.animate() does and a CSS animation doesn't.
const SHAKE = [0, -7, 6, -4, 2, 0].map((x) => ({ transform: `translateX(${x}px)` }));
const SHAKE_OPTIONS = { duration: 500, easing: "ease-in-out" };
const FALLBACK_WAIT_S = 30; // the lockout's first wait, if a 429 ever comes without a Retry-After

interface Lock {
  until: number; // epoch seconds
  seconds: number; // the whole wait, said once to screen readers instead of every tick
}

function formatWait(seconds: number): string {
  const text = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
  return text;
}

export function LoginPage() {
  const [params] = useSearchParams();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [wrong, setWrong] = useState(false);
  const [lock, setLock] = useState<Lock | null>(null);
  const [note, setNote] = useState<Note | null>(null);
  const [busy, setBusy] = useState(false);
  const fields = useRef<HTMLDivElement>(null);
  const now = useNow();
  // useNow's last tick can be up to a second old, so the time left never shows more than the whole wait.
  const waitLeft = lock == null ? 0 : Math.max(0, Math.ceil(lock.until - Math.max(now, lock.until - lock.seconds)));

  const shake = () => {
    if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      fields.current?.animate(SHAKE, SHAKE_OPTIONS);
    }
  };
  const signIn = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setWrong(false);
    setNote(null);
    const reply = await request("POST", "/api/login", { username, password });
    if (reply.ok) {
      loadPage(readSafeNext(params.get("next")));
    } else {
      if (reply.status === 429) {
        const seconds = reply.retryAfterS ?? FALLBACK_WAIT_S;
        setLock({ until: Date.now() / 1000 + seconds, seconds });
      } else if (reply.status === 401) {
        setWrong(true);
        shake();
      } else {
        setNote(buildErrorNote(reply.detail));
      }
      setBusy(false);
    }
  };

  return (
    <AuthFrame>
      <form onSubmit={signIn}>
        <span className="auth-dot" aria-hidden="true" />
        <h1 className="auth-title">Sign in</h1>
        <p className="auth-intro">Welcome back to the study room.</p>
        <div ref={fields} className="auth-fields">
          <Field label="Username" name="username" autoComplete="username" autoCapitalize="none" spellCheck={false} required value={username} onChange={(event) => setUsername(event.target.value)} />
          <Field
            label="Password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            aria-invalid={wrong || undefined}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </div>
        {wrong && (
          <p role="alert" className="form-note" data-tone="error">
            Wrong username or password.
          </p>
        )}
        {lock != null && waitLeft > 0 && (
          <p role="alert" className="form-note" data-tone="warn">
            Too many tries. Try again in <span aria-hidden="true">{formatWait(waitLeft)}</span>
            <span className="sr-only">{lock.seconds} seconds</span>.
          </p>
        )}
        <FormNote note={note} />
        <button type="submit" className="button button-ink button-block" disabled={busy || waitLeft > 0}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
        <p className="auth-foot">Invite only. Ask the owner for a link.</p>
      </form>
    </AuthFrame>
  );
}
