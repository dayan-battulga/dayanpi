import { useState } from "react";
import { useLocation } from "react-router";
import { useFrame } from "@/components/frame/Frame";
import { CameraSection } from "@/components/settings/CameraSection";
import { MacHelperSection } from "@/components/settings/MacHelperSection";
import { ProfileSection } from "@/components/settings/ProfileSection";
import { RoomSection } from "@/components/settings/RoomSection";
import { SharingSection } from "@/components/settings/SharingSection";
import { VoiceSection } from "@/components/settings/VoiceSection";
import { signOut } from "@/lib/account";

// The mockup's sections, in its order.
const SECTIONS = [
  { id: "profile", name: "Profile", ownerOnly: false },
  { id: "sharing", name: "Sharing", ownerOnly: false },
  { id: "camera", name: "Camera", ownerOnly: false },
  { id: "voice", name: "Voice and bedtime", ownerOnly: false },
  { id: "mac", name: "Mac helper", ownerOnly: false },
  { id: "room", name: "Room and invites", ownerOnly: true },
] as const;

type SectionId = (typeof SECTIONS)[number]["id"];

// At /settings, inside the frame (Settings.dc.html): the section list on the left (a row of pills on a phone) and the
// picked section on the right, rising in each time you pick one. A link can ask for a section (the room's Invite).
export function SettingsPage() {
  const { user, setUser, macTracking, snapshot, now, receivedAt } = useFrame();
  const asked = (useLocation().state as { section?: SectionId } | null)?.section;
  const [section, setSection] = useState<SectionId>(asked ?? "profile");
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
            {section === "sharing" && <SharingSection focus={snapshot?.focus} room={snapshot?.room} username={user.username} now={now} receivedAt={receivedAt} />}
            {section === "camera" && <CameraSection focus={snapshot?.focus} owner={owner} now={now} onOpenSharing={() => setSection("sharing")} />}
            {section === "voice" && <VoiceSection focus={snapshot?.focus} owner={owner} now={now} />}
            {section === "mac" && <MacHelperSection macTracking={macTracking} />}
            {section === "room" && owner && <RoomSection />}
          </div>
        </div>
      )}
    </div>
  );
}
