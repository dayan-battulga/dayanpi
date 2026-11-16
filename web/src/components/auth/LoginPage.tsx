import { useState, type FormEvent } from "react";
import { useSearchParams } from "react-router";
import { AuthFrame } from "@/components/auth/AuthFrame";
import { Field } from "@/components/shared/Field";
import { FormNote, buildErrorNote, type Note } from "@/components/shared/FormNote";
import { Button } from "@/components/ui/button";
import { readSafeNext, request } from "@/lib/http";
import { loadPage } from "@/lib/navigation";

export function LoginPage() {
  const [params] = useSearchParams();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [note, setNote] = useState<Note | null>(null);
  const [busy, setBusy] = useState(false);

  const signIn = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setNote(null);
    const reply = await request("POST", "/api/login", { username, password });
    if (reply.ok) {
      loadPage(readSafeNext(params.get("next")));
    } else {
      setNote(buildErrorNote(reply.detail));
      setBusy(false);
    }
  };

  return (
    <AuthFrame title="Sign in" intro="The desk, the focus timer and the to-dos.">
      <form className="flex flex-col gap-4" onSubmit={signIn}>
        <Field
          label="Username"
          name="username"
          autoComplete="username"
          autoCapitalize="none"
          spellCheck={false}
          required
          value={username}
          onChange={(event) => setUsername(event.target.value)}
        />
        <Field
          label="Password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        <FormNote note={note} />
        <Button type="submit" disabled={busy} className="mt-2 h-11 rounded-full font-semibold">
          {busy ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </AuthFrame>
  );
}
