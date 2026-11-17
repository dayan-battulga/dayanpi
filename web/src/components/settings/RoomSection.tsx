import { useEffect, useState } from "react";
import { CopyField } from "@/components/settings/CopyField";
import { FormNote, buildErrorNote, type Note } from "@/components/shared/FormNote";
import { ROOM_SIZE } from "@/lib/account";
import { formatShortDate } from "@/lib/format";
import { fetchJson, request } from "@/lib/http";
import type { Account, Invite, RecordId } from "@/lib/types";

const DAY_S = 86400;

function describeDaysLeft(expiresAt: number): string {
  const days = Math.max(0, Math.ceil((expiresAt - Date.now() / 1000) / DAY_S));
  const text = `${days} ${days === 1 ? "day" : "days"} left`;
  return text;
}

interface FreshInvite {
  link: string;
  invite: Invite;
}

// The owner's room: invite links (one person each, once, within a week; the link shows only right after it's made)
// and who has a seat, with a two-step remove.
export function RoomSection() {
  const [invites, setInvites] = useState<Invite[] | null>(null);
  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [fresh, setFresh] = useState<FreshInvite | null>(null);
  const [note, setNote] = useState<Note | null>(null);
  const [confirming, setConfirming] = useState<RecordId | null>(null);
  const [cancelled, setCancelled] = useState<RecordId | null>(null);
  const full = accounts != null && accounts.length >= ROOM_SIZE;

  useEffect(() => {
    let current = true;
    fetchJson<{ invites: Invite[] }>("/api/invites").then((reply) => current && setInvites(reply?.invites ?? []));
    fetchJson<{ accounts: Account[] }>("/api/accounts").then((reply) => current && setAccounts(reply?.accounts ?? []));
    return () => {
      current = false;
    };
  }, []);

  const makeInvite = async () => {
    setNote(null);
    const reply = await request<{ invite: Invite; code: string }>("POST", "/api/invites");
    const made = reply.body;
    if (made != null) {
      setInvites((list) => [...(list ?? []), made.invite]);
      setFresh({ link: `${window.location.origin}/join/${made.code}`, invite: made.invite });
    } else {
      setNote(buildErrorNote(reply.detail));
    }
  };
  const revokeInvite = async (id: RecordId) => {
    setNote(null);
    const reply = await request("DELETE", `/api/invites/${encodeURIComponent(id)}`);
    if (reply.ok) {
      setInvites((list) => (list ?? []).filter((invite) => invite.id !== id));
      setFresh((shown) => (shown?.invite.id === id ? null : shown));
    } else {
      setNote(buildErrorNote(reply.detail));
    }
  };
  const removeAccount = async (id: RecordId) => {
    setNote(null);
    const reply = await request("DELETE", `/api/accounts/${encodeURIComponent(id)}`);
    if (reply.ok) {
      setAccounts((list) => (list ?? []).filter((account) => account.id !== id));
      setConfirming(null);
    } else {
      setNote(buildErrorNote(reply.detail));
    }
  };

  return (
    <section aria-labelledby="settings-room">
      <div className="settings-head">
        <h2 id="settings-room" className="settings-title">
          Room and invites
        </h2>
        {accounts != null && <span className="setting-meta">{`${accounts.length} of ${ROOM_SIZE} seats`}</span>}
      </div>
      {fresh != null && <CopyField label="Invite link" value={fresh.link} meta={`works once · ${describeDaysLeft(fresh.invite.expires_at)}`} />}
      <button type="button" className="button button-ink settings-action" disabled={full} onClick={makeInvite}>
        New invite
      </button>
      {full && <p className="settings-hint">The room is full. Remove someone to invite another.</p>}
      <FormNote note={note} />
      {invites != null && invites.length > 0 && (
        <ul className="settings-rows" aria-label="Open invites">
          {invites.map((invite) => (
            <li key={invite.id} className="setting-row">
              <span>
                Invite <span className="setting-meta">· made {formatShortDate(invite.created_at)} · {describeDaysLeft(invite.expires_at)}</span>
              </span>
              <button type="button" className="button button-line button-small" aria-label={`Revoke the invite made ${formatShortDate(invite.created_at)}`} onClick={() => revokeInvite(invite.id)}>
                Revoke
              </button>
            </li>
          ))}
        </ul>
      )}
      <ul className="people" aria-label="Accounts">
        {(accounts ?? []).map((account) => (
          <li key={account.id} className="person-row">
            <span className="person-avatar" aria-hidden="true">
              {account.display_name.charAt(0).toUpperCase()}
            </span>
            <span className="person-name">
              {account.display_name} <span className="setting-meta">· {account.role === "owner" ? "owner" : `joined ${formatShortDate(account.created_at)}`}</span>
            </span>
            {/* Each step unmounts the focused button, so autoFocus hands focus to the next one instead of the page body. */}
            {account.role === "member" && confirming !== account.id && (
              <button
                type="button"
                className="button button-line button-small"
                aria-label={`Remove ${account.display_name}`}
                autoFocus={cancelled === account.id}
                onClick={() => setConfirming(account.id)}
              >
                Remove
              </button>
            )}
            {account.role === "member" && confirming === account.id && (
              <div className="row-buttons" role="group" aria-label={`Remove ${account.display_name}?`}>
                <span id={`remove-warning-${account.id}`} className="setting-meta">
                  Their sign-ins and tokens stop working.
                </span>
                <button type="button" className="button button-hot button-small" aria-describedby={`remove-warning-${account.id}`} onClick={() => removeAccount(account.id)}>
                  Yes, remove
                </button>
                <button
                  type="button"
                  className="button button-line button-small"
                  aria-describedby={`remove-warning-${account.id}`}
                  autoFocus
                  onClick={() => {
                    setConfirming(null);
                    setCancelled(account.id);
                  }}
                >
                  Cancel
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
