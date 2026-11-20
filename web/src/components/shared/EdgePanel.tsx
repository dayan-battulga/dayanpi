import { PanelRightClose, PanelRightOpen } from "lucide-react";
import type { ReactNode } from "react";

interface EdgePanelProps {
  title: string;
  titleId: string;
  stripLabel: string; // the folded strip's name
  foldLabel: string;
  openLabel: string;
  className?: string; // this panel's own width and padding, on top of .rail's
  collapsed: boolean;
  onCollapse: (collapsed: boolean) => void;
  strip: ReactNode; // what the 76 px strip shows under its open button
  children: ReactNode; // the open panel, under its title and fold button
}

// A panel pinned to the window's right edge at full height, in the frame's .rail-slot: its title and fold button on the
// top bar's row, and folded, a 76 px strip. The room sidebar on Desk, Pi and Settings, and the Room's notepad.
export function EdgePanel({ title, titleId, stripLabel, foldLabel, openLabel, className = "", collapsed, onCollapse, strip, children }: EdgePanelProps) {
  const panel = collapsed ? (
    <aside className={`rail rail-collapsed ${className}`} aria-label={stripLabel}>
      <button type="button" className="rail-toggle" aria-label={openLabel} onClick={() => onCollapse(false)}>
        <PanelRightOpen size={18} strokeWidth={1.8} aria-hidden="true" />
      </button>
      {strip}
    </aside>
  ) : (
    <aside className={`rail ${className}`} aria-labelledby={titleId}>
      <div className="rail-head">
        <h2 id={titleId} className="rail-title">
          {title}
        </h2>
        <button type="button" className="rail-toggle" aria-label={foldLabel} onClick={() => onCollapse(true)}>
          <PanelRightClose size={18} strokeWidth={1.8} aria-hidden="true" />
        </button>
      </div>
      {children}
    </aside>
  );
  return panel;
}
