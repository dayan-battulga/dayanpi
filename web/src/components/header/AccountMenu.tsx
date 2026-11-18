import { LogOut, Settings } from "lucide-react";
import { DropdownMenu } from "radix-ui";
import { Link, useMatch } from "react-router";
import { signOut } from "@/lib/account";
import type { User } from "@/lib/types";

// Who's signed in, as a round initial (ringed on Settings), and the way to Settings and out.
export function AccountMenu({ user }: { user: User }) {
  const onSettings = useMatch("/settings") != null;
  const initial = Array.from(user.display_name.trim())[0]?.toUpperCase() ?? "?";
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger className="account-button" aria-label={`Account: ${user.display_name}`} aria-current={onSettings ? "page" : undefined}>
        <span aria-hidden="true">{initial}</span>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="end" sideOffset={8} className="account-menu">
          <DropdownMenu.Label className="account-menu-label mono">@{user.username}</DropdownMenu.Label>
          <DropdownMenu.Item asChild className="account-menu-item">
            <Link to="/settings">
              <Settings size={16} strokeWidth={1.8} aria-hidden="true" />
              Settings
            </Link>
          </DropdownMenu.Item>
          <DropdownMenu.Item className="account-menu-item" onSelect={() => signOut()}>
            <LogOut size={16} strokeWidth={1.8} aria-hidden="true" />
            Sign out
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
