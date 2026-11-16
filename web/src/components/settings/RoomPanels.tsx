import { useEffect, useState } from "react";
import { CopyField } from "@/components/settings/CopyField";
import { SettingsPanel } from "@/components/settings/SettingsPanel";
import { FormNote, buildErrorNote, type Note } from "@/components/shared/FormNote";
import { Button } from "@/components/ui/button";
import { ROOM_SIZE } from "@/lib/account";
import { formatDate } from "@/lib/format";
import { fetchJson, request } from "@/lib/http";
import type { Account, Invite, RecordId } from "@/lib/types";

const ROW_CLASS = "flex min-h-14 flex-wrap items-center justify-between gap-x-3 gap-y-2 border-b border-border py-2 last:border-b-0";

// The owner's two cards: invites (one link per person, once, for 7 days) and who has an account.
export function RoomPanels() {
  const [invites, setInvites] = useState<Invite[] | null>(null);
  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [link, setLink] = useState<string | null>(null);
  const [inviteNote, setInviteNote] = useState<Note | null>(null);
  const [accountNote, setAccountNote] = useState<Note | null>(null);
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
    setInviteNote(null);
    const reply = await request<{ invite: Invite; code: string }>("POST", "/api/invites");
    const made = reply.body;
    if (made != null) {
      setInvites((list) => [...(list ?? []), made.invite]);
      setLink(`${window.location.origin}/join/${made.code}`);
    } else {
      setInviteNote(buildErrorNote(reply.detail));
    }
  };
  const revokeInvite = async (id: RecordId) => {
    setInviteNote(null);
    const reply = await request("DELETE", `/api/invites/${encodeURIComponent(id)}`);
    if (reply.ok) {
      setInvites((list) => (list ?? []).filter((invite) => invite.id !== id));
    } else {
      setInviteNote(buildErrorNote(reply.detail));
    }
  };
  const removeAccount = async (id: RecordId) => {
    setAccountNote(null);
    const reply = await request("DELETE", `/api/accounts/${encodeURIComponent(id)}`);
    if (reply.ok) {
      setAccounts((list) => (list ?? []).filter((account) => account.id !== id));
      setConfirming(null);
    } else {
      setAccountNote(buildErrorNote(reply.detail));
    }
  };

  const makeButton = (
    <Button type="button" disabled={full} onClick={makeInvite} className="h-11 rounded-full px-5 font-semibold">
      Make an invite
    </Button>
  );
  return (
    <>
      <SettingsPanel title="Invites" detail={full ? `The room is full: ${ROOM_SIZE} of ${ROOM_SIZE} accounts. Remove someone to invite another.` : "Each link makes one account, once, within 7 days."} action={makeButton}>
        {link != null && (
          <div className="flex flex-col gap-2 rounded-2xl border border-border bg-secondary p-4">
            <span className="text-sm font-medium">Invite link</span>
            <CopyField label="Invite link" value={link} />
            <span className="muted small">Send it to one person. You won't see this link again.</span>
          </div>
        )}
        <FormNote note={inviteNote} />
        {invites == null ? (
          <span className="muted text-sm">Loading…</span>
        ) : invites.length === 0 ? (
          <span className="muted text-sm">No open invites.</span>
        ) : (
          <ul aria-label="Open invites" className="flex flex-col">
            {invites.map((invite) => (
              <li key={invite.id} className={ROW_CLASS}>
                <div className="flex flex-col">
                  <span className="text-sm font-medium">Made {formatDate(invite.created_at)}</span>
                  <span className="mono muted small">expires {formatDate(invite.expires_at)}</span>
                </div>
                <button type="button" className="button button-ghost button-small" aria-label={`Revoke the invite made ${formatDate(invite.created_at)}`} onClick={() => revokeInvite(invite.id)}>
                  Revoke
                </button>
              </li>
            ))}
          </ul>
        )}
      </SettingsPanel>

      <SettingsPanel title="Accounts" detail={accounts == null ? undefined : `${accounts.length} of ${ROOM_SIZE}`}>
        <FormNote note={accountNote} />
        {accounts == null ? (
          <span className="muted text-sm">Loading…</span>
        ) : (
          <ul aria-label="Accounts" className="flex flex-col">
            {accounts.map((account) => (
              <li key={account.id} className={ROW_CLASS}>
                <div className="flex min-w-0 flex-col">
                  <span className="truncate text-sm font-medium">{account.display_name}</span>
                  <span className="mono muted small">
                    @{account.username} · {account.role} · since {formatDate(account.created_at)}
                  </span>
                </div>
                {/* Each step unmounts the focused button, so autoFocus hands focus to the next one instead of the page body. */}
                {account.role === "member" && confirming !== account.id && (
                  <button
                    type="button"
                    className="button button-ghost button-small"
                    aria-label={`Remove ${account.display_name}`}
                    autoFocus={cancelled === account.id}
                    onClick={() => setConfirming(account.id)}
                  >
                    Remove
                  </button>
                )}
                {account.role === "member" && confirming === account.id && (
                  <div className="flex flex-wrap items-center gap-2" role="group" aria-label={`Remove ${account.display_name}?`}>
                    <span id={`remove-warning-${account.id}`} className="text-sm">
                      Their sign-ins and tokens stop working.
                    </span>
                    <Button type="button" variant="destructive" aria-describedby={`remove-warning-${account.id}`} onClick={() => removeAccount(account.id)} className="h-11 rounded-full px-5 font-semibold">
                      Yes, remove
                    </Button>
                    <button
                      type="button"
                      className="button button-ghost button-small"
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
        )}
      </SettingsPanel>
    </>
  );
}
