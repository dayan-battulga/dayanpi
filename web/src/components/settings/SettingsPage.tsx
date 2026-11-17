import { useState } from "react";
import { useFrame } from "@/components/frame/Frame";
import { MacHelperSection } from "@/components/settings/MacHelperSection";
import { ProfileSection } from "@/components/settings/ProfileSection";
import { RoomSection } from "@/components/settings/RoomSection";
import { signOut } from "@/lib/account";

// The sections that work today. Share with the room, Camera, and Voice and bedtime come with the study room.
const SECTIONS = [
  { id: "profile", name: "Profile", ownerOnly: false },
  { id: "mac", name: "Mac helper", ownerOnly: false },
  { id: "room", name: "Room and invites", ownerOnly: true },
] as const;

type SectionId = (typeof SECTIONS)[number]["id"];

// At /settings, inside the frame (Settings.dc.html): the section list on the left (a row of pills on a phone) and the
// picked section on the right, rising in each time you pick one.
export function SettingsPage() {
  const { user, setUser, macTracking } = useFrame();
  const [section, setSection] = useState<SectionId>("profile");
  const owner = user?.role === "owner";
  const sections = SECTIONS.filter((entry) => owner || !entry.ownerOnly);

  return (
    <div className="settings-page">
      <h1 className="page-title rise">Settings</h1>
      {user != null && (
        <div className="settings-body">
          <nav className="settings-nav rise" aria-label="Settings sections">
            <ul className="settings-nav-list">
              {sections.map((entry) => (
                <li key={entry.id}>
                  <button type="button" className="settings-nav-item" aria-current={entry.id === section ? "page" : undefined} onClick={() => setSection(entry.id)}>
                    {entry.name}
                  </button>
                </li>
              ))}
            </ul>
            <button type="button" className="settings-signout" onClick={() => signOut()}>
              Sign out
            </button>
          </nav>
          <div key={section} className="settings-section rise">
            {section === "profile" && <ProfileSection user={user} onSaved={setUser} />}
            {section === "mac" && <MacHelperSection owner={owner} macTracking={macTracking} />}
            {section === "room" && owner && <RoomSection />}
          </div>
        </div>
      )}
    </div>
  );
}
