import { ChevronDown, LogOut, Settings, UserRound } from "lucide-react";
import { DropdownMenu } from "radix-ui";
import { Link } from "react-router";
import { signOut } from "@/lib/account";
import type { User } from "@/lib/types";

const ITEM_CLASS = "flex min-h-10 cursor-pointer items-center gap-2.5 rounded-xl px-3 text-sm outline-none select-none data-[highlighted]:bg-accent";

// Who's signed in, and the way to Settings and out.
export function AccountMenu({ user }: { user: User }) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger className="mono inline-flex min-h-11 max-w-40 cursor-pointer items-center gap-2 rounded-full border border-border bg-card px-3.5 text-xs text-[var(--ink-2)] data-[state=open]:bg-secondary sm:max-w-56">
        <UserRound size={15} strokeWidth={1.8} aria-hidden="true" />
        <span className="truncate">{user.display_name}</span>
        <ChevronDown size={14} strokeWidth={1.8} aria-hidden="true" />
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="end" sideOffset={8} className="z-50 min-w-48 rounded-2xl border border-border bg-card p-1.5 text-foreground shadow-lg">
          <DropdownMenu.Label className="mono px-3 py-2 text-xs text-muted-foreground">@{user.username}</DropdownMenu.Label>
          <DropdownMenu.Item asChild className={ITEM_CLASS}>
            <Link to="/settings">
              <Settings size={16} strokeWidth={1.8} aria-hidden="true" />
              Settings
            </Link>
          </DropdownMenu.Item>
          <DropdownMenu.Item className={ITEM_CLASS} onSelect={() => signOut()}>
            <LogOut size={16} strokeWidth={1.8} aria-hidden="true" />
            Sign out
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
