import { useEffect, useState, type FormEvent } from "react";
import { CopyField } from "@/components/settings/CopyField";
import { SettingsPanel } from "@/components/settings/SettingsPanel";
import { Field } from "@/components/shared/Field";
import { FormNote, buildErrorNote, type Note } from "@/components/shared/FormNote";
import { Button } from "@/components/ui/button";
import { NAME_MAX } from "@/lib/account";
import { formatDate } from "@/lib/format";
import { fetchJson, request } from "@/lib/http";
import type { ApiToken } from "@/lib/types";

// The Mac helper's logins: one per Mac, shown once when made, revocable any time.
export function TokensPanel() {
  const [tokens, setTokens] = useState<ApiToken[] | null>(null);
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
    <SettingsPanel title="Mac helper tokens" detail="The Mac helper signs in with one of these instead of your password. A token only works for the Mac's reports.">
      {secret != null && (
        <div className="flex flex-col gap-2 rounded-2xl border border-border bg-secondary p-4">
          <span className="text-sm font-medium">Your new token</span>
          <CopyField label="New token" value={secret} />
          <span className="muted small">Copy it now: you won't see it again. Put it in the Mac's Keychain in place of the password (mac_helper/README.md says how).</span>
        </div>
      )}
      <form className="flex flex-col gap-3 sm:flex-row sm:items-end" onSubmit={makeToken}>
        <div className="flex-1">
          <Field label="Token name" placeholder="MacBook" autoComplete="off" maxLength={NAME_MAX} required value={name} onChange={(event) => setName(event.target.value)} />
        </div>
        <Button type="submit" variant="outline" className="h-11 rounded-full border-input bg-transparent px-5 font-semibold">
          Make a token
        </Button>
      </form>
      <FormNote note={note} />
      {tokens == null ? (
        <span className="muted text-sm">Loading…</span>
      ) : tokens.length === 0 ? (
        <span className="muted text-sm">No tokens yet.</span>
      ) : (
        <ul aria-label="Tokens" className="flex flex-col">
          {tokens.map((token) => (
            <li key={token.id} className="flex min-h-14 flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b border-border py-2 last:border-b-0">
              <div className="flex min-w-0 flex-col">
                <span className="truncate text-sm font-medium">{token.name}</span>
                <span className="mono muted small">
                  made {formatDate(token.created_at)} · {token.last_used_at == null ? "never used" : `last used ${formatDate(token.last_used_at)}`}
                </span>
              </div>
              <button type="button" className="button button-ghost button-small" aria-label={`Revoke ${token.name}`} onClick={() => revokeToken(token)}>
                Revoke
              </button>
            </li>
          ))}
        </ul>
      )}
    </SettingsPanel>
  );
}
