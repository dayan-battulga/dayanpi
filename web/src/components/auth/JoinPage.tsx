import { useState, type FormEvent } from "react";
import { useParams } from "react-router";
import { AuthFrame } from "@/components/auth/AuthFrame";
import { Field } from "@/components/shared/Field";
import { FormNote, buildErrorNote, type Note } from "@/components/shared/FormNote";
import { Button } from "@/components/ui/button";
import { NAME_MAX, PASSWORD_MAX, PASSWORD_MIN, USERNAME_MAX } from "@/lib/account";
import { request } from "@/lib/http";
import { loadPage } from "@/lib/navigation";

// The code stays in the page's address; the join call sends it in the body, so it never lands in a log.
export function JoinPage() {
  const { code = "" } = useParams();
  const [displayName, setDisplayName] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [note, setNote] = useState<Note | null>(null);
  const [busy, setBusy] = useState(false);

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
      } else {
        setNote(buildErrorNote(reply.detail));
        setBusy(false);
      }
    }
  };

  return (
    <AuthFrame title="Join the room" intro="Someone sent you an invite. Pick a name and a password; the link works once.">
      <form className="flex flex-col gap-4" onSubmit={join}>
        <Field
          label="Display name"
          name="display_name"
          autoComplete="nickname"
          maxLength={NAME_MAX}
          required
          hint="What the others see."
          value={displayName}
          onChange={(event) => setDisplayName(event.target.value)}
        />
        <Field
          label="Username"
          name="username"
          autoComplete="username"
          autoCapitalize="none"
          spellCheck={false}
          maxLength={USERNAME_MAX}
          required
          hint="For signing in: lowercase letters, numbers, dots, dashes and underscores."
          value={username}
          onChange={(event) => setUsername(event.target.value)}
        />
        <Field
          label="Password"
          name="password"
          type="password"
          autoComplete="new-password"
          maxLength={PASSWORD_MAX}
          required
          hint={`At least ${PASSWORD_MIN} characters.`}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        <FormNote note={note} />
        <Button type="submit" disabled={busy} className="mt-2 h-11 rounded-full font-semibold">
          {busy ? "Joining…" : "Join"}
        </Button>
      </form>
    </AuthFrame>
  );
}
