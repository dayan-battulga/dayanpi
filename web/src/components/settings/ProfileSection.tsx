import { useId, useState, type FormEvent } from "react";
import { Field } from "@/components/shared/Field";
import { FormNote, buildErrorNote, type Note } from "@/components/shared/FormNote";
import { NAME_MAX, PASSWORD_MAX, PASSWORD_MIN } from "@/lib/account";
import { formatCompactMinutes } from "@/lib/calendar";
import { request } from "@/lib/http";
import type { User } from "@/lib/types";

// Off, or 1h to 12h in half hours (focus/days.py's GOAL_* limits).
const GOALS = Array.from({ length: 23 }, (_, index) => 60 + index * 30);

interface ProfileSectionProps {
  user: User;
  goalMinutes: number | null | undefined; // your desk's daily goal, from the stream (undefined until it comes)
  onSaved: (user: User) => void;
}

// Your name, daily focus goal and password, saved with one button. Changing the password needs the current one, which
// asks for itself once you start typing a new one (the mockup's form, plus what the Pi checks).
export function ProfileSection({ user, goalMinutes, onSaved }: ProfileSectionProps) {
  const goalId = useId();
  const [name, setName] = useState(user.display_name);
  // Only what you picked here gets saved, so a stream that hadn't come yet never saves "Off" over your goal.
  const [goal, setGoal] = useState<number | null | undefined>(undefined);
  const shownGoal = goal === undefined ? (goalMinutes ?? null) : goal;
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
      if (!result.error && goal !== undefined && goal !== goalMinutes) {
        const picked = await request("POST", "/api/goal", { minutes: goal });
        if (!picked.ok) {
          result = buildErrorNote(picked.detail);
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
          <div>
            <label htmlFor={goalId} className="field-label">
              Daily focus goal
            </label>
            <select id={goalId} className="field-input" value={shownGoal ?? ""} onChange={(event) => setGoal(event.target.value === "" ? null : Number(event.target.value))}>
              <option value="">Off</option>
              {GOALS.map((minutes) => (
                <option key={minutes} value={minutes}>
                  {formatCompactMinutes(minutes)}
                </option>
              ))}
            </select>
          </div>
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
