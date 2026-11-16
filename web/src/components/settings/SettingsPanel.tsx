import type { ReactNode } from "react";

interface SettingsPanelProps {
  title: string;
  detail?: string;
  action?: ReactNode;
  children: ReactNode;
}

// One card on the settings page: a label heading like the dashboard's cards, a gray line, an optional button on the right.
export function SettingsPanel({ title, detail, action, children }: SettingsPanelProps) {
  return (
    <section className="card rise flex flex-col gap-4 p-5 sm:p-6" aria-label={title}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h2 className="label">{title}</h2>
          {detail != null && <span className="muted text-sm">{detail}</span>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}
