# The Calm design: how to build it

The mockups in `design/mockups/` are the plan for every page of the site (approved Nov 16, 2026). This file is how to turn them into the real thing so it looks and moves the same way.

- **How it looks: the mockup wins.** Every size, color, radius, shadow and animation in a mockup file is exact. Read the file instead of eyeballing a screenshot.
- **How it behaves and moves: this file wins**, because a mockup can only show so much.
- The mockups are copies of the design canvas in claude.ai. When the canvas changes, the copies here change in the same commit as the code that follows them.

## Opening the mockups

- `npm run mockups` (in web/) serves them at http://localhost:4400. The index page lists every mockup with its options.
- Options go in the URL and stack: `Desk.dc.html?theme=dark&moment=all%20done`. Anything you leave out uses its default. Clicking works like the canvas's Play mode: start a to-do, open a popup, flip the theme.
- Each file is plain HTML with inline styles and a little script. `{{a.b}}` holes, `<sc-if>`, `<sc-for>` and `<dc-import>` are the canvas's template tags. `renderVals()` at the bottom has the sample data and what each click does.
- `support.js` is a small stand-in for the canvas runtime so they open in any browser. Nothing in web/ imports anything from design/.

## Checking your work against them

`npm run shots -- compare <Mockup> <route>` writes the mockup and the real page side by side, in light and dark, to `design/shots/compare/` (gitignored). Example: `npm run shots -- compare Desk /me`.

- The real page runs on a local Vite dev server. Every `/api` call is answered from `design/fixtures/<Mockup>.json` and the page's clock is frozen at the fixture's `now`, so both sides show the same day: same names, numbers and times.
- `--phone` makes the pair 390 px wide. `--mockup=RoomPhone` compares against a different mockup (the room has its own phone mockup).
- `npm run shots -- mockups Desk` screenshots one mockup in every option. That's handy for the moments: peace sign, all done, day page and so on.
- **A step isn't done until you've opened every compare image** and the layout, spacing, sizes, type, colors and radii match in both themes and at both widths. Differences that only come from the data are fine, but fix the fixture first if you can.
- Nothing here reaches the internet or the Pi. The fonts come from web/node_modules, the mockup pages get a header that blocks outside requests, and Chrome runs through playwright-core (no browser download).

### Fixtures

A fixture is one JSON file per mockup:

| Key | What it is |
| --- | --- |
| `now` | The page's clock, frozen, like `"2026-11-16T19:12:18-06:00"` |
| `timezone` | Like `"America/Chicago"` |
| `mockupOptions` | Options for the mockup side, like `{ "moment": "none" }` |
| `storage` | Optional localStorage entries to set before the page loads |
| `permissions` | Optional browser permissions to grant, like `["camera"]` for /track. Chrome's fake camera (a test pattern) stands in for a real one; leave it out and the camera is blocked |
| `stream` | The one snapshot `/api/stream` sends. The stream stays open, like the Pi's |
| `routes` | Replies by URL. A key can be `"POST /api/todos"`, `"/api/apps?range=today"` or `"/api/focus"`, and the first match wins. A reply that isn't a 200 is `{"$status": 429, "$headers": {"Retry-After": "28"}, "body": {...}}` (`$headers` optional). `{"$file": "models/<name>.onnx"}` answers with that file from the repo's `models/` (nothing else), so /track's worker really runs |

Anything not listed gets a 404, so the page shows its empty state. Fixtures follow the real API: when an API changes, its fixtures change in the same commit. `Desk.json` is the mockup's day (Monday Nov 16, 7:12 pm) in the API as it is after study room step 2 (signed in as the owner).

## Colors

Same token names as `web/src/styles/dashboard.css`. Color only ever means a state; everything else is ink and grays. Text on a colored button uses `var(--bg)` (Working, Nudge).

| Token | Light | Dark | Used for |
| --- | --- | --- | --- |
| `--bg` | `#f6f6f4` | `#0a0a0c` | the page |
| `--surface` | `#ffffff` | `#131316` | cards, dialogs, the active tab |
| `--sunken` | `#efefec` | `#1a1a1e` (was `#0d0d10`) | the tab pill, tracks, inputs |
| `--line` | `rgb(17 17 19 / 8%)` | `rgb(255 255 255 / 7%)` | hairlines |
| `--line-strong` | `rgb(17 17 19 / 18%)` (was 16%) | `rgb(255 255 255 / 16%)` (was 15%) | outlines: Start buttons, empty seats. The mockups call it `--line2` |
| `--ink` | `#111113` | `#ededef` | text, primary buttons |
| `--ink-2` | `#3a3a40` | `#c4c4ca` | app bars, done dots. The mockups call it `--ink2` |
| `--muted` | `#696970` | `#8e8e96` | secondary text |
| `--work` | `#0e6e63` | `#34d3b9` | focused |
| `--phone` | `#c2410c` | `#ff8a4c` | on the phone |
| `--away` | `#6d5bd0` | `#a99bff` | away |
| `--hot` | `#be123c` | `#ff5c7a` | YouTube, alarms |
| `--warm` | `#8f5a06` (was `#a16207`) | `#f5b83d` | warnings |
| `--scrim` (new) | `rgb(17 17 19 / 24%)` | `rgb(0 0 0 / 50%)` | behind dialogs |
| `--glass` (new) | `rgb(255 255 255 / 78%)` | `rgb(24 24 28 / 76%)` | frosted floating things (toasts, the peace-sign pill, the bottom bar, the dock), always with a backdrop blur |

## Type

- Geist for everything, and Geist Mono for numbers that tick (timers, durations, clock times). Both are already self-hosted from @fontsource-variable. The mockups' `'Geist'` and `'Geist Mono'` are our `--font-ui` and `--font-mono`.
- Numbers use tabular figures (`font-variant-numeric: tabular-nums`) so they don't jiggle.
- Sizes (the mockups have the exact values for everything else):
  - The state word ("Focused"): `clamp(56px, 8vw, 112px)`, weight 600, letter-spacing -0.055em, line-height 0.92.
  - The big timer: Geist Mono `clamp(40px, 5.6vw, 76px)`, weight 500, letter-spacing -0.045em, in the state color.
  - The wordmark: 20px, weight 600, letter-spacing -0.04em.
  - Section titles 15px/600, body 15px, secondary text 13px muted, tiny labels 12px muted.
- The old small uppercase mono labels ("ON THE MAC", "CALENDAR") are gone.

## Shape and space

- Content is 1180 px wide with 32 px sides, 16 px on a phone.
- Radii:
  - pills: 999 px
  - cards: 24 px
  - seats and their-desk cards: 28 px
  - dialogs: 26–28 px
  - to-do rows: 16 px
  - thumbnails: 12–14 px
- Every button and link is at least 44×44 px.
- Shadows are almost gone:
  - Dialogs: `0 40px 100px -30px rgb(0 0 0 / 60%)`.
  - The active tab: `0 1px 2px rgb(0 0 0 / 8%)`.
- Frosted glass only on things that float over the page: toasts, the peace-sign pill, the bottom bar and the phone dock (`--glass` with `backdrop-filter: blur(16–18px)`). The ⌘K palette and the dialogs are solid `--surface` cards over the scrim.
  - Scrims blur 3–4 px, and name labels over video blur 8 px.
  - The top bar is not glass.
- Login and Join have a soft, still glow at the top (`radial-gradient(900px 420px at 50% -12%, …)`). No shaders, no grain.

## Motion

The rules:
- Motion means something: a state changed, you did something, or someone did something to you.
- Loops are slow, and only on things that show a state (lamps, live dots).
- While you're focused, other people's changes animate once and never loop.
- With reduced motion nothing moves (fades at most), and numbers just change.

"ease" everywhere below is `cubic-bezier(0.16, 1, 0.3, 1)`, the existing `--ease`.

### The catalog

These come straight from the mockups. The CSS ones go in dashboard.css once and get reused.

| Name | What it's for | Exact motion | Built with | Copy it from |
| --- | --- | --- | --- | --- |
| rise | page and card entrances | from opacity 0, `translateY(10px)`, `blur(4px)`; 0.5–0.7 s ease, staggered | one CSS keyframe with `--rise-y` and `--rise-blur`: 12 px over 0.8 s on Login and Join, 8 px / 3 px over 0.45 s on Settings and Pi | Desk, Room |
| lamp | the glow around seats and big avatars, in the person's state color (`--lamp`) | box-shadow breathing; 6 s focused, 2.4 s on the phone, none when away or offline | CSS | Room (seats), RoomPhone (the smaller one) |
| breathe | live status dots | a ring growing to 6–8 px and fading, 2.4 s | CSS | Room, Login, Track, Sign |
| shine | the live end of the timeline | `translateX(-100%)` to `100%`, 2.6 s ease, looping | CSS (already in dashboard.css) | Desk |
| blink | the dot in "Working" | opacity 0.35 at the middle, 1.6 s | CSS | Desk |
| bar | sound bars in the peace-sign pill | `scaleY` 0.3 ↔ 1, 0.9 s, delays 0, -0.15, -0.3, -0.6 s | CSS | Desk, Room |
| ripple | nudge rings leaving a seat | scale 0.7 → 2.6, opacity 0.55 → 0, 1.8 s ease, a second ring 0.6 s later; two rounds, then stop | CSS | Room |
| shake | wrong password | `translateX` 0, -7, 6, -4, 2, 0 px over 0.5 s, replayed on every miss | CSS | Login |
| fall | confetti when the last to-do is done | each piece `translateY(-20px → 170px)` and `rotate(0 → 320deg)` with its own duration and delay; one burst | CSS, plus the piece generator in Desk's `renderVals` | Desk (moment "all done") |
| pop, fade | every dialog (the quick peek, the day page, ⌘K) and its scrim | dialog from opacity 0, `translateY(16px) scale(0.97)`, 0.5 s ease; scrim fades in over 0.3 s; leaving is the reverse in 0.2 s. A couple of mockups use rise for their dialogs; use pop for all of them so they feel the same | Motion (`AnimatePresence`) | PersonPanel |
| slide | the sidebar opening | from opacity 0, `translateX(16px)`, 0.45 s ease | Motion | SideRail |
| glow | the desk sign's lamp | opacity 0.7 ↔ 1, 8 s | CSS | Sign |

### Motion the mockups can't show

- **To-dos.** Start on a row makes it the current one (tinted row, Working pill), and the old current one goes back to Start. The pill says Working while you're focused and Paused otherwise. Rows never jump: checking one slides it down into Done and unchecking slides it back (Motion `layout` plus `AnimatePresence`, the "layout" spring). A new to-do rises in at the bottom.
- **Numbers.** Every number that changes rolls to its new value with NumberFlow: the timer, the totals, the counts and the Pi stats. The timer is two NumberFlows in a `NumberFlowGroup`, and the tens digit of the seconds only goes up to 5.
- **The state word.** When it changes (Focused → On your phone), the old word blurs out and the new one blurs in. That's the existing "swap" motion, 0.7 s.
- **Tabs.** The active pill (`--surface`) slides to the tab you picked (Motion `layoutId`, the "toggle" spring). Apps' Today/Week has no pill: it's two quiet text buttons, and the picked one turns ink.
- **Page changes.** React's `<ViewTransition>`: a cross-fade with a small rise, 0.3 s.
- **Theme.** The colors cross-fade (the existing `theme-fade`, 0.6 s), and the sun/moon icon swaps with a quarter turn and a fade.
- **Presses.** Buttons and seats squish to 0.97 while you press them (the "press" spring).
- **Switches.** The thumb slides with the "toggle" spring. Flipping a sharing switch updates the preview right away, and that piece fades in or out there.
- **Their desk.** When someone stops sharing a piece, it fades out and the rest slide into the space (Motion `layout`, the "layout" spring). Same when they start sharing again.
- **Toasts (Sonner).** Frosted pills at the bottom right, 32 px in (on a phone: centered, above the dock), like the "Nudged Sam" toast in Room's nudge moment. They rise in (0.6 s) and stay 4 s. Never more than one at a time.
- **⌘K (cmdk).** A solid card (radius 22 px, max 560 px wide) over the scrim, like Room's command palette moment. It pops in like every dialog. Typing filters, ↑/↓ move a highlight that slides (the "toggle" spring), Enter runs the command, Esc closes.
- **Peace sign.** The pill rises in just under the top bar, centered (rise, 0.7 s), like Desk's peace sign moment. It shows the sound bars and the message while the voice speaks, then fades away.
- **Nudge.** The button squishes and two ripple rings leave the seat. The other person gets a toast and hears it on their speaker.
- **Reconnecting.** When the stream drops, a small "Reconnecting" chip in `--warm` shows next to the wordmark, and the live parts dim to 55% until it's back (Room, moment "reconnecting").

### Springs and timings

These live in `web/src/lib/motion.ts`, next to `replayAnimation`:

| Name | Setting | For |
| --- | --- | --- |
| press | spring, `visualDuration` 0.2, `bounce` 0.3 | buttons, seats |
| toggle | spring, `visualDuration` 0.3, `bounce` 0.2 | switches, the tab pill, the palette highlight |
| layout | spring, `visualDuration` 0.45, `bounce` 0.1 | to-do rows, their-desk pieces, seats moving |
| enter | 0.5 s, ease | dialogs, the pill, panels |
| exit | 0.2 s, ease-in | anything leaving |

### Reduced motion

- `<MotionConfig reducedMotion="user">` goes at the root.
- The CSS loops stop with `@media (prefers-reduced-motion: reduce) { * { animation: none !important; } }`. Every mockup has that.
- NumberFlow respects the setting on its own.
- With reduced motion there are no loops, slides or confetti. Dialogs and toasts just fade in.

## Libraries

| Library | For | Notes |
| --- | --- | --- |
| `motion` | layout moves, things leaving, springs, presses | import from `"motion/react"` |
| `@number-flow/react` | rolling numbers | |
| `sonner` | toasts | wrap it in `components/ui/` with our tokens; no next-themes |
| `cmdk` | the ⌘K palette | inside our own Radix Dialog; don't `npx shadcn add` it (see the shadcn trap in CLAUDE.md) |
| React's `<ViewTransition>` | page changes | built into React 19.3 |
| `radix-ui` (have it) | Dialog, Switch, Tooltip, Popover | the accessible parts, restyled |
| `lucide-react` (have it) | icons | stroke 1.8, like the mockups |

The small moments (lamps, ripple, confetti, sound bars) are copied from the mockups instead of coming from component kits. Each one is a few lines of CSS, and this way they match exactly. Nothing loads from a CDN (tests/test_app.py checks that).

## What goes where

| Mockup | Route | Who | Built in |
| --- | --- | --- | --- |
| Desk | `/me` | everyone | R3–R6 |
| Pi | `/pi` | the owner, from Tailscale | R7 |
| Login, Join | `/login`, `/join/:code` | anyone | R8 (the pages come from study room step 2) |
| Settings | `/settings` | everyone | R8, plus more sections in study room steps 4–7 |
| Track | `/track` | friends | study room step 4 |
| Room, RoomPhone | `/` | everyone | study room step 6. Until then `/` goes to `/me` |
| SeatsInfo | the seats in the Room | everyone | study room step 6. For the seats, SeatsInfo wins over Room |
| SideRail, BottomBar | on Desk, Pi and Settings | everyone | study room step 6 |
| PersonPanel | the popup when you tap a seat | everyone | study room step 6 |
| TheirDesk, TheirDeskLess | `/people/:username` | everyone | study room step 6 |
| Sign | `/sign` | optional | R9, if wanted |

- **The seats.** Every seat shows today's total (a chip at the top left), the current to-do and app under the name, and a thin bar along the bottom with how many of their to-dos are done, in their state color. A bell shows on the seat of someone who's been on their phone for 5+ minutes. RoomPhone has the same details, sized down. Each detail only shows if that person shares it: today's total needs focus time, the to-do needs to-dos, the app needs apps.
- **The Mac line.** The Desk's stats row has what's in front on your Mac on its right (Desk, option `mac`):
  - "On the Mac · VS Code"
  - "On the Mac · youtube.com in Chrome"
  - "Mac tracking paused"
  - "The Mac isn't reporting"

  Next to it is a small Pause or Resume text button, only for whoever owns that desk.

- **Widths.**
  - Under 640 px is a phone: one column, and the room uses RoomPhone's layout with the dock.
  - From 640 to 1279 px, "who's here" is the bottom bar.
  - From 1280 px up, it's the sidebar.
- **From today's dashboard:**
  - The camera card, its readings and the Pi stats move to `/pi`.
  - The "On the Mac" card becomes the Mac line on the Desk's stats row (above). The tracking switch lives in three places: the line's Pause/Resume, Settings → Mac helper, and a ⌘K command.
  - The "Today" list of state changes isn't in the Calm design, because the timeline shows the same thing.
