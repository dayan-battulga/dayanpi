import { useState, type FormEvent } from "react";
import { Field } from "@/components/shared/Field";
import { FormNote, buildErrorNote, type Note } from "@/components/shared/FormNote";
import { NAME_MAX, PASSWORD_MAX, PASSWORD_MIN } from "@/lib/account";
import { request } from "@/lib/http";
import type { User } from "@/lib/types";

// Your name and password, saved with one button. Changing the password needs the current one, which asks for itself
// once you start typing a new one (the mockup's form, plus what the Pi checks).
export function ProfileSection({ user, onSaved }: { user: User; onSaved: (user: User) => void }) {
  const [name, setName] = useState(user.display_name);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [note, setNote] = useState<Note | null>(null);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    let result: Note = { text: "Saved.", error: false };
    if (next !== "" && next.length < PASSWORD_MIN) {
      result = { text: `The new password needs at least ${PASSWORD_MIN} characters.`, error: true };
    } else {
      if (name.trim() !== user.display_name) {
        const renamed = await request<{ user: User }>("PATCH", "/api/me", { display_name: name.trim() });
        if (renamed.body != null) {
          onSaved(renamed.body.user);
        } else {
          result = buildErrorNote(renamed.detail);
        }
      }
      if (!result.error && next !== "") {
        const changed = await request("POST", "/api/me/password", { current_password: current, new_password: next });
        if (changed.ok) {
          setCurrent("");
          setNext("");
          result = { text: "Saved. Everywhere else you were signed in is signed out now.", error: false };
        } else {
          result = buildErrorNote(changed.detail);
        }
      }
    }
    setNote(result);
  };

  return (
    <section aria-labelledby="settings-profile">
      <h2 id="settings-profile" className="settings-title">
        Profile
      </h2>
      <div className="profile-head">
        <span className="profile-avatar" aria-hidden="true">
          {user.display_name.charAt(0).toUpperCase()}
        </span>
        @{user.username} · {user.role}
      </div>
      <form onSubmit={save}>
        {/* For password managers, so they update the right login. */}
        <input type="text" name="username" autoComplete="username" value={user.username} readOnly hidden />
        <div className="settings-fields">
          <Field label="Name" autoComplete="nickname" maxLength={NAME_MAX} required value={name} onChange={(event) => setName(event.target.value)} />
          <Field
            label="New password"
            type="password"
            autoComplete="new-password"
            maxLength={PASSWORD_MAX}
            placeholder={`At least ${PASSWORD_MIN} characters`}
            value={next}
            onChange={(event) => setNext(event.target.value)}
          />
          {next !== "" && <Field label="Current password" type="password" autoComplete="current-password" required value={current} onChange={(event) => setCurrent(event.target.value)} />}
        </div>
        <FormNote note={note} />
        <button type="submit" className="button button-ink settings-action">
          Save
        </button>
      </form>
    </section>
  );
}
