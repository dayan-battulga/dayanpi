import { readFileSync } from "node:fs";
import { expect, it } from "vitest";
import { findTabIcon } from "@/hooks/useTabIcon";
import type { LampColor } from "@/lib/types";

// The lamp colors in dashboard.css, checked the way people see them: readable, never mistaken for on the phone or away,
// and the tab icons drawn in the same shades.

const LAMPS: LampColor[] = ["teal", "green", "sky", "yellow", "pink", "white"];
// From the disk: Vitest hands CSS imports over empty, even with ?raw. It runs in web/.
const css = readFileSync("src/styles/dashboard.css", "utf8");
const ICONS = import.meta.glob<string>("../../public/assets/icon-*.svg", { query: "?raw", import: "default", eager: true });

// One theme's tokens, with var(--x) looked up in the same block. The dark block is also .icon-palette's.
function readTheme(theme: "light" | "dark"): Record<string, string> {
  const start = css.indexOf(theme === "light" ? ':root[data-theme="light"] {' : ".icon-palette {");
  const block = css.slice(start, css.indexOf("}", start));
  const raw = Object.fromEntries(Array.from(block.matchAll(/--([\w-]+):\s*([^;]+);/g), (match) => [match[1], match[2].trim()]));
  const tokens = Object.fromEntries(Object.entries(raw).map(([name, value]) => [name, value.startsWith("var(--") ? raw[value.slice(6, -1)] : value]));
  return tokens;
}

function readRgb(hex: string): number[] {
  const rgb = [1, 3, 5].map((at) => parseInt(hex.slice(at, at + 2), 16) / 255);
  return rgb;
}

function measureLuminance(hex: string): number {
  const [r, g, b] = readRgb(hex).map((value) => (value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function measureContrast(first: string, second: string): number {
  const [light, dark] = [measureLuminance(first), measureLuminance(second)].sort((a, b) => b - a);
  return (light + 0.05) / (dark + 0.05);
}

// HSL hue in degrees and saturation 0-1.
function readHue(hex: string): { hue: number; saturation: number } {
  const [r, g, b] = readRgb(hex);
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const spread = max - min;
  const lightness = (max + min) / 2;
  const raw = spread === 0 ? 0 : max === r ? ((g - b) / spread) % 6 : max === g ? (b - r) / spread + 2 : (r - g) / spread + 4;
  return { hue: (raw * 60 + 360) % 360, saturation: spread === 0 ? 0 : spread / (1 - Math.abs(2 * lightness - 1)) };
}

function measureHueGap(first: string, second: string): number {
  const gap = Math.abs(readHue(first).hue - readHue(second).hue) % 360;
  return Math.min(gap, 360 - gap);
}

it.each(["light", "dark"] as const)("keeps every lamp color readable on the %s theme's background and cards (3:1)", (theme) => {
  const tokens = readTheme(theme);
  for (const lamp of LAMPS) {
    const color = tokens[`lamp-${lamp}`];
    expect(color, lamp).toMatch(/^#[0-9a-f]{6}$/);
    expect(measureContrast(color, tokens.bg), `${lamp} on --bg`).toBeGreaterThanOrEqual(3);
    expect(measureContrast(color, tokens.surface), `${lamp} on --surface`).toBeGreaterThanOrEqual(3);
  }
});

it.each(["light", "dark"] as const)("never puts a lamp color near on the phone's orange or away's violet on the %s theme", (theme) => {
  const tokens = readTheme(theme);
  for (const lamp of LAMPS.filter((name) => name !== "white")) {
    expect(readHue(tokens[`lamp-${lamp}`]).saturation, lamp).toBeGreaterThan(0.25);
    expect(measureHueGap(tokens[`lamp-${lamp}`], tokens.phone), `${lamp} vs phone`).toBeGreaterThanOrEqual(30);
    expect(measureHueGap(tokens[`lamp-${lamp}`], tokens.away), `${lamp} vs away`).toBeGreaterThanOrEqual(30);
  }
  expect(readHue(tokens["lamp-white"]).saturation).toBeLessThan(0.1); // plain, no hue at all
});

it("makes white plain ink on the light theme", () => {
  expect(measureLuminance(readTheme("light")["lamp-white"])).toBeLessThan(0.02);
});

it("leaves on the phone and away the same for everyone: only focused reads the picked color", () => {
  expect([readTheme("light").phone, readTheme("light").away, readTheme("dark").phone, readTheme("dark").away]).toEqual(["#c2410c", "#6d5bd0", "#ff8a4c", "#a99bff"]);
  const lampRule = (state: string) => css.match(new RegExp(`\\[data-state="${state}"\\] \\{\\s*--lamp: ([^;]+);`))?.[1];
  expect([lampRule("working"), lampRule("phone"), lampRule("away")]).toEqual(["var(--focus-lamp, var(--work))", "var(--phone)", "var(--away)"]);
  expect(Array.from(css.matchAll(/\[data-lamp="(\w+)"\] \{\s*--focus-lamp: var\(--lamp-(\w+)\);\s*\}/g), (match) => match[1] === match[2] && match[1])).toEqual(LAMPS);
});

it("has a focused tab icon for each lamp color, drawn in its dark shade, and the other states' icons in theirs", () => {
  const dark = readTheme("dark");
  const lampOf = (path: string) => ICONS[`../../public${path}`]?.match(/<circle cx="14.6" cy="20.6" r="5.9" fill="(#[0-9a-f]{6})"\/>/)?.[1];
  for (const lamp of LAMPS) {
    const icon = findTabIcon("working", lamp);
    expect(icon).toBe(`/assets/icon-working-${lamp}.svg`);
    expect(lampOf(icon), lamp).toBe(dark[`lamp-${lamp}`]);
  }
  expect([lampOf(findTabIcon("phone", "pink")), lampOf(findTabIcon("away", "pink")), lampOf(findTabIcon(null, "pink"))]).toEqual([dark.phone, dark.away, dark.muted]);
});
