import { request } from "@/lib/http";
import { loadPage } from "@/lib/navigation";

// The Pi checks all of these again; the page only says them up front.
export const ROOM_SIZE = 4;
export const PASSWORD_MIN = 10;
export const PASSWORD_MAX = 256;
export const NAME_MAX = 40;
export const USERNAME_MAX = 32;

export async function signOut(): Promise<void> {
  await request("POST", "/api/logout");
  loadPage("/login");
}
