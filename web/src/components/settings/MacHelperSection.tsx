import { useEffect, useState, type FormEvent } from "react";
import { CopyField } from "@/components/settings/CopyField";
import { Field } from "@/components/shared/Field";
import { FormNote, buildErrorNote, type Note } from "@/components/shared/FormNote";
import { Switch } from "@/components/ui/switch";
import type { MacTracking } from "@/hooks/useMacTracking";
import { NAME_MAX } from "@/lib/account";
import { formatShortDate } from "@/lib/format";
import { fetchJson, request } from "@/lib/http";
import type { ApiToken } from "@/lib/types";

// The Mac helper: the same tracking switch as the Mac line and ⌘K (your own desk's), and the helper's logins. A
// token reports to your own desk only, is shown once when made, and can be revoked any time.
export function MacHelperSection({ macTracking }: { macTracking: MacTracking }) {
  const [tokens, setTokens] = useState<ApiToken[] | null>(null);
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  const [secret, setSecret] = useState<string | null>(null);
  const [note, setNote] = useState<Note | null>(null);

  useEffect(() => {
    let current = true;
    fetchJson<{ tokens: ApiToken[] }>("/api/tokens").then((reply) => {
      if (current) {
        setTokens(reply?.tokens ?? []);
      }
    });
    return () => {
      current = false;
    };
  }, []);

  const makeToken = async (event: FormEvent) => {
    event.preventDefault();
    setNote(null);
    const reply = await request<{ token: ApiToken; secret: string }>("POST", "/api/tokens", { name: name.trim() });
    const made = reply.body;
    if (made != null) {
      setTokens((list) => [...(list ?? []), made.token]);
      setSecret(made.secret);
      setName("");
      setNaming(false);
    } else {
      setNote(buildErrorNote(reply.detail));
    }
  };
  const revokeToken = async (token: ApiToken) => {
    setNote(null);
    const reply = await request("DELETE", `/api/tokens/${encodeURIComponent(token.id)}`);
    if (reply.ok) {
      setTokens((list) => (list ?? []).filter((entry) => entry.id !== token.id));
    } else {
      setNote(buildErrorNote(reply.detail));
    }
  };

  return (
    <section aria-labelledby="settings-mac">
      <h2 id="settings-mac" className="settings-title">
        Mac helper
      </h2>
      <div className="settings-rows">
        <div className="setting-row">
          Track apps and sites
          <Switch label="Track apps and sites" checked={macTracking.tracking} onCheckedChange={(enabled) => macTracking.flipTracking(enabled)} />
        </div>
        <ul aria-label="Tokens">
          {(tokens ?? []).map((token) => (
            <li key={token.id} className="setting-row is-tall">
              <span>
                {token.name}{" "}
                <span className="setting-meta">
                  · made {formatShortDate(token.created_at)} · {token.last_used_at == null ? "never used" : `last used ${formatShortDate(token.last_used_at)}`}
                </span>
              </span>
              <button type="button" className="button button-line button-small" aria-label={`Revoke ${token.name}`} onClick={() => revokeToken(token)}>
                Revoke
              </button>
            </li>
          ))}
        </ul>
      </div>
      {secret != null && <CopyField label="New token" value={secret} meta="shown once" />}
      {naming ? (
        <form className="token-form" onSubmit={makeToken}>
          <Field label="Token name" placeholder="MacBook" autoComplete="off" maxLength={NAME_MAX} required autoFocus value={name} onChange={(event) => setName(event.target.value)} />
          <div className="row-buttons">
            <button type="submit" className="button button-ink">
              Make it
            </button>
            <button type="button" className="button button-line" onClick={() => setNaming(false)}>
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <button type="button" className="button button-ink settings-action" onClick={() => setNaming(true)}>
          New token
        </button>
      )}
      <FormNote note={note} />
      <p className="settings-hint">You see a token once. Paste it into the helper.</p>
    </section>
  );
}
