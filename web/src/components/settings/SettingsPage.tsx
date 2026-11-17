import { LogOut } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useFrame } from "@/components/frame/Frame";
import { RoomPanels } from "@/components/settings/RoomPanels";
import { SettingsPanel } from "@/components/settings/SettingsPanel";
import { TokensPanel } from "@/components/settings/TokensPanel";
import { Field } from "@/components/shared/Field";
import { FormNote, buildErrorNote, type Note } from "@/components/shared/FormNote";
import { Button } from "@/components/ui/button";
import { NAME_MAX, PASSWORD_MAX, PASSWORD_MIN, signOut } from "@/lib/account";
import { request } from "@/lib/http";
import type { User } from "@/lib/types";

const SAVE_CLASS = "h-11 self-start rounded-full px-5 font-semibold";

function ProfilePanel({ user, onSaved }: { user: User; onSaved: (user: User) => void }) {
  const [name, setName] = useState(user.display_name);
  const [note, setNote] = useState<Note | null>(null);
  const saveName = async (event: FormEvent) => {
    event.preventDefault();
    const reply = await request<{ user: User }>("PATCH", "/api/me", { display_name: name.trim() });
    const saved = reply.body?.user;
    if (saved != null) {
      onSaved(saved);
      setNote({ text: "Saved.", error: false });
    } else {
      setNote(buildErrorNote(reply.detail));
    }
  };
  const signOutButton = (
    <button type="button" className="button button-ghost button-small" onClick={() => signOut()}>
      <LogOut size={16} strokeWidth={1.8} aria-hidden="true" />
      Sign out
    </button>
  );
  return (
    <SettingsPanel title="You" detail={`Signed in as @${user.username}${user.role === "owner" ? " · owner" : ""}`} action={signOutButton}>
      <form className="flex flex-col gap-4" onSubmit={saveName}>
        <Field label="Display name" autoComplete="nickname" maxLength={NAME_MAX} required value={name} onChange={(event) => setName(event.target.value)} />
        <FormNote note={note} />
        <Button type="submit" className={SAVE_CLASS}>
          Save name
        </Button>
      </form>
    </SettingsPanel>
  );
}

function PasswordPanel({ username }: { username: string }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [note, setNote] = useState<Note | null>(null);
  const changePassword = async (event: FormEvent) => {
    event.preventDefault();
    if (next.length < PASSWORD_MIN) {
      setNote({ text: `The new password needs at least ${PASSWORD_MIN} characters.`, error: true });
    } else {
      const reply = await request("POST", "/api/me/password", { current_password: current, new_password: next });
      if (reply.ok) {
        setCurrent("");
        setNext("");
        setNote({ text: "Password changed. Everywhere else you were signed in is signed out now.", error: false });
      } else {
        setNote(buildErrorNote(reply.detail));
      }
    }
  };
  return (
    <SettingsPanel title="Password">
      <form className="flex flex-col gap-4" onSubmit={changePassword}>
        {/* For password managers, so they update the right login. */}
        <input type="text" name="username" autoComplete="username" value={username} readOnly hidden />
        <Field label="Current password" type="password" autoComplete="current-password" required value={current} onChange={(event) => setCurrent(event.target.value)} />
        <Field
          label="New password"
          type="password"
          autoComplete="new-password"
          maxLength={PASSWORD_MAX}
          required
          hint={`At least ${PASSWORD_MIN} characters.`}
          value={next}
          onChange={(event) => setNext(event.target.value)}
        />
        <FormNote note={note} />
        <Button type="submit" className={SAVE_CLASS}>
          Change password
        </Button>
      </form>
    </SettingsPanel>
  );
}

// At /settings, inside the frame: the top bar's account button and the dock lead here and back.
export function SettingsPage() {
  const { user, setUser } = useFrame();
  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4">
      <h1 className="sr-only">Settings</h1>
      {user == null ? (
        <span className="muted text-sm">Loading…</span>
      ) : (
        <>
          <ProfilePanel user={user} onSaved={setUser} />
          <PasswordPanel username={user.username} />
          <TokensPanel />
          {user.role === "owner" && <RoomPanels />}
        </>
      )}
    </div>
  );
}
