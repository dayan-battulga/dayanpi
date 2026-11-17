import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";
import { AuthFrame } from "@/components/auth/AuthFrame";
import { Field } from "@/components/shared/Field";
import { FormNote, buildErrorNote, type Note } from "@/components/shared/FormNote";
import { NAME_MAX, PASSWORD_MAX, PASSWORD_MIN, ROOM_SIZE, USERNAME_MAX } from "@/lib/account";
import { request } from "@/lib/http";
import { loadPage } from "@/lib/navigation";

// What the join call's answer means for the invite: used up or past its week (404), or every seat taken (403).
const GONE = {
  404: { title: "This invite expired", text: "Invites work once and last a week. Ask the owner for a new one." },
  403: { title: "The room is full", text: `All ${ROOM_SIZE} seats are taken. Ask the owner to open one up.` },
} as const;

// The code stays in the page's address; the join call sends it in the body, so it never lands in a log.
export function JoinPage() {
  const { code = "" } = useParams();
  const [displayName, setDisplayName] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [note, setNote] = useState<Note | null>(null);
  const [gone, setGone] = useState<keyof typeof GONE | null>(null);
  const [busy, setBusy] = useState(false);
  const initial = displayName.trim().charAt(0).toUpperCase() || "?";

  const join = async (event: FormEvent) => {
    event.preventDefault();
    setNote(null);
    if (password.length < PASSWORD_MIN) {
      setNote({ text: `The password needs at least ${PASSWORD_MIN} characters.`, error: true });
    } else {
      setBusy(true);
      const reply = await request("POST", "/api/join", { code, display_name: displayName, username, password });
      if (reply.ok) {
        loadPage("/");
      } else if (reply.status === 404 || reply.status === 403) {
        setGone(reply.status);
      } else {
        setNote(buildErrorNote(reply.detail));
        setBusy(false);
      }
    }
  };

  return (
    <AuthFrame wide>
      {gone != null ? (
        <div className="auth-gone">
          <h1 className="auth-title">{GONE[gone].title}</h1>
          <p className="auth-intro">{GONE[gone].text}</p>
          <Link to="/login" className="button button-line button-block">
            Back to sign in
          </Link>
        </div>
      ) : (
        <form onSubmit={join}>
          <h1 className="auth-title">You’re invited</h1>
          <p className="auth-intro">Pick a name. It’s what the room sees.</p>
          <div className="join-seat">
            <span className="join-seat-avatar" aria-hidden="true">
              {initial}
            </span>
            Your seat
          </div>
          <div className="auth-fields">
            <Field label="Name" name="display_name" autoComplete="nickname" maxLength={NAME_MAX} required value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
            <Field
              label="Username"
              name="username"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              maxLength={USERNAME_MAX}
              required
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
            <Field
              label="Password"
              name="password"
              type="password"
              autoComplete="new-password"
              maxLength={PASSWORD_MAX}
              placeholder={`At least ${PASSWORD_MIN} characters`}
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </div>
          <FormNote note={note} />
          <button type="submit" className="button button-ink button-block" disabled={busy}>
            {busy ? "Joining…" : "Join the room"}
          </button>
        </form>
      )}
    </AuthFrame>
  );
}
