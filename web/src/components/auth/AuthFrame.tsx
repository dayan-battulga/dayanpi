import type { ReactNode } from "react";
import { ThemeToggle } from "@/components/shared/ThemeToggle";

interface AuthFrameProps {
  title: string;
  intro: string;
  children: ReactNode;
}

// The sign-in and join pages: the dashboard's top bar and one centered card.
export function AuthFrame({ title, intro, children }: AuthFrameProps) {
  return (
    <div className="shell flex min-h-svh flex-col">
      <header className="topbar">
        <div className="brand">
          <span className="wordmark">dayanpi</span>
          <span className="label">study room</span>
        </div>
        <ThemeToggle />
      </header>
      <main className="flex flex-1 items-start justify-center pt-[6vh]">
        <section className="card rise flex w-full max-w-sm flex-col gap-6 p-6 sm:p-8" aria-labelledby="auth-title">
          <div className="flex flex-col gap-1.5">
            <h1 id="auth-title" className="text-2xl font-semibold tracking-tight">
              {title}
            </h1>
            <p className="muted text-sm">{intro}</p>
          </div>
          {children}
        </section>
      </main>
    </div>
  );
}
