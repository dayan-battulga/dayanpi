export interface Note {
  text: string;
  error: boolean;
}

// What a form's last try said. The Pi's details are lowercase sentences, so CSS capitalizes the first letter.
export function FormNote({ note }: { note: Note | null }) {
  return note == null ? null : (
    <p role={note.error ? "alert" : "status"} className={`text-sm first-letter:uppercase ${note.error ? "text-destructive" : "text-muted-foreground"}`}>
      {note.text}
    </p>
  );
}

// A failed reply's detail, or a plain line when nothing answered (offline, or the Pi restarting).
export function buildErrorNote(detail: string | null): Note {
  const note = { text: detail ?? "Couldn't reach the Pi. Try again in a moment.", error: true };
  return note;
}
