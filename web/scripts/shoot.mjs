// Screenshots for making the real pages match the mockups in design/mockups.
//
//   npm run mockups                         serve the mockups at http://localhost:4400 (index.html lists them)
//   npm run shots -- mockups [Desk Room]    every mockup (or the named ones) in each of its options, light and
//                                           dark, into design/shots/mockups/
//   npm run shots -- compare Desk /me       the mockup next to the real page, light and dark, into
//                                           design/shots/compare/
//
// compare options:
//   --phone                  390 px wide instead of the mockup's own size
//   --mockup=RoomPhone       compare against a different mockup (the fixture still comes from the first name)
//   --fixture=Desk-away      use design/fixtures/Desk-away.json instead of Desk.json
//   --options="moment=day page&myState=away"   mockup options for this run, on top of the fixture's
//   --click="text=Start"     click something on the real page before the shot (Playwright selector, repeatable)
//   --press=Control+k        press keys on the real page before the shot (repeatable, after the clicks)
//   --label=palette          added to the file names, so different states don't overwrite each other
//
// Nothing here reaches the internet or the Pi: the fonts come from web/node_modules, the real page runs
// on a local Vite dev server, and every /api call is answered from design/fixtures/<Mockup>.json.
// It drives your installed Google Chrome through playwright-core, so there's no browser to download.
import { createReadStream, existsSync, mkdirSync, readFileSync, readdirSync, statSync } from "node:fs";
import http from "node:http";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const webDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoDir = path.resolve(webDir, "..");
const mockupDir = path.join(repoDir, "design", "mockups");
const fixtureDir = path.join(repoDir, "design", "fixtures");
const shotDir = path.join(repoDir, "design", "shots");
const fontDirs = {
  geist: path.join(webDir, "node_modules", "@fontsource-variable", "geist", "files"),
  "geist-mono": path.join(webDir, "node_modules", "@fontsource-variable", "geist-mono", "files"),
};
const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".woff2": "font/woff2",
};
const PHONE = { width: 390, height: 844 };
const SETTLE_MS = 900;

// Only files inside the mockup folder or the two font folders, never anything above them.
function findServedFile(urlPath) {
  const clean = decodeURIComponent(urlPath.split("?")[0]);
  const fontMatch = /^\/__fonts\/(geist|geist-mono)\/([\w.-]+\.woff2)$/.exec(clean);
  const base = fontMatch ? fontDirs[fontMatch[1]] : mockupDir;
  const relative = fontMatch ? fontMatch[2] : clean === "/" ? "index.html" : clean.slice(1);
  const file = path.resolve(base, relative);
  const inside = file.startsWith(base + path.sep) && existsSync(file) && statSync(file).isFile();
  return inside ? file : null;
}

// The canvas copies link Google Fonts; here the fonts come from web/node_modules instead, so that
// link is cut, and the policy header blocks anything else that would leave this machine.
const LOCAL_ONLY = "default-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob:";
const GOOGLE_FONTS_LINK = /<link[^>]*fonts\.(googleapis|gstatic)\.com[^>]*>/g;

function startMockupServer(port) {
  const server = http.createServer((request, response) => {
    const file = findServedFile(request.url ?? "/");
    const headers = { "content-type": TYPES[path.extname(file ?? "")] ?? "application/octet-stream", "cache-control": "no-store", "content-security-policy": LOCAL_ONLY };
    if (file === null) {
      response.writeHead(404).end("not found");
    } else if (file.endsWith(".html")) {
      response.writeHead(200, headers).end(readFileSync(file, "utf8").replace(GOOGLE_FONTS_LINK, ""));
    } else {
      response.writeHead(200, headers);
      createReadStream(file).pipe(response);
    }
  });
  const ready = new Promise((resolve) => server.listen(port, "127.0.0.1", () => resolve(server)));
  return ready;
}

function readServerUrl(server) {
  const address = server.address();
  const url = `http://127.0.0.1:${address.port}`;
  return url;
}

// Each enum option's values one at a time, plus both values of each boolean, always over the defaults.
function listVariants(name) {
  const html = readFileSync(path.join(mockupDir, `${name}.dc.html`), "utf8");
  const match = /data-props='([^']*)'/.exec(html);
  const spec = match ? JSON.parse(match[1]) : {};
  const preview = spec.$preview ?? { width: 1440, height: 900 };
  const variants = [{ label: "default", query: {} }];
  Object.entries(spec)
    .filter(([key]) => key !== "theme" && !key.startsWith("$"))
    .forEach(([key, option]) => {
      const values = option.editor === "boolean" ? [true, false] : (option.options ?? []);
      values.filter((value) => value !== option.default).forEach((value) => {
        variants.push({ label: `${key}-${String(value).replace(/\W+/g, "-")}`, query: { [key]: String(value) } });
      });
    });
  const themes = spec.theme ? spec.theme.options : [null];
  const shot = { preview, variants, themes };
  return shot;
}

function buildQuery(values) {
  const params = new URLSearchParams(Object.entries(values).filter(([, value]) => value !== null));
  const query = params.toString();
  return query === "" ? "" : `?${query}`;
}

// Your installed Chrome first (the Mac), then playwright-core's own Chromium if one is there, then a
// globally installed playwright (Claude Code cloud sessions come with one).
async function openBrowser() {
  const launchers = [
    async () => (await import("playwright-core")).chromium.launch({ channel: process.env.SHOTS_CHANNEL ?? "chrome" }),
    async () => (await import("playwright-core")).chromium.launch(),
    async () => createRequire(import.meta.url)("playwright").chromium.launch(),
  ];
  const problems = [];
  let browser = null;
  for (const launch of launchers) {
    if (browser === null) {
      try {
        browser = await launch();
      } catch (error) {
        problems.push(String(error.message).split("\n")[0]);
      }
    }
  }
  if (browser === null) throw new Error(`Couldn't start a browser for screenshots. Install Google Chrome, or set SHOTS_CHANNEL. Tried: ${problems.join(" | ")}`);
  return browser;
}

async function shootMockup(browser, baseUrl, name, query, size, file) {
  const page = await browser.newPage({ viewport: size, reducedMotion: "no-preference" });
  await page.goto(`${baseUrl}/${name}.dc.html${buildQuery(query)}`);
  await page.waitForSelector("html[data-dc-ready]");
  await page.waitForTimeout(SETTLE_MS);
  await page.screenshot({ path: file, fullPage: true, animations: "disabled" });
  await page.close();
}

async function shootMockups(names) {
  const server = await startMockupServer(0);
  const baseUrl = readServerUrl(server);
  const browser = await openBrowser();
  const chosen = names.length > 0 ? names : readdirSync(mockupDir).filter((file) => file.endsWith(".dc.html")).map((file) => file.replace(".dc.html", ""));
  const outDir = path.join(shotDir, "mockups");
  mkdirSync(outDir, { recursive: true });
  for (const name of chosen) {
    const { preview, variants, themes } = listVariants(name);
    for (const theme of themes) {
      for (const variant of variants) {
        const file = path.join(outDir, `${name}-${variant.label}${theme ? `-${theme}` : ""}.png`);
        await shootMockup(browser, baseUrl, name, { ...variant.query, theme }, { width: preview.width, height: preview.height }, file);
        console.log(path.relative(repoDir, file));
      }
    }
  }
  await browser.close();
  server.close();
}

function readFixture(name) {
  const file = path.join(fixtureDir, `${name}.json`);
  const fixture = existsSync(file) ? JSON.parse(readFileSync(file, "utf8")) : { routes: {} };
  if (!existsSync(file)) console.warn(`No design/fixtures/${name}.json yet: every /api call gets a 404, so the page shows its empty states.`);
  return fixture;
}

// Answers /api and /video from the fixture before Vite's proxy ever sees them, and keeps the
// stream open the way the Pi does, so the page never thinks it lost the connection.
function serveFixtures(fixture) {
  const plugin = {
    name: "design-fixtures",
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const url = request.url ?? "/";
        const pathOnly = url.split("?")[0];
        if (pathOnly === "/api/stream") {
          response.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache", connection: "keep-alive" });
          response.write(`data: ${JSON.stringify(fixture.stream ?? {})}\n\n`);
        } else if (pathOnly.startsWith("/api/") || pathOnly.startsWith("/video")) {
          const routes = fixture.routes ?? {};
          const body = routes[`${request.method} ${url}`] ?? routes[url] ?? routes[`${request.method} ${pathOnly}`] ?? routes[pathOnly];
          if (body === undefined) {
            response.writeHead(404, { "content-type": "application/json" }).end("{}");
          } else {
            response.writeHead(200, { "content-type": "application/json" }).end(JSON.stringify(body));
          }
        } else {
          next();
        }
      });
    },
  };
  return plugin;
}

async function startApp(fixture) {
  const { createServer } = await import("vite");
  const server = await createServer({
    root: webDir,
    configFile: path.join(webDir, "vite.config.ts"),
    plugins: [serveFixtures(fixture)],
    server: { port: 0, strictPort: false, host: "127.0.0.1" },
    logLevel: "error",
  });
  await server.listen();
  return server;
}

async function shootApp(browser, appUrl, route, fixture, size, theme, actions, file) {
  const context = await browser.newContext({
    viewport: size,
    colorScheme: theme,
    timezoneId: fixture.timezone ?? "America/Chicago",
    reducedMotion: "no-preference",
  });
  if (fixture.storage) {
    await context.addInitScript((entries) => {
      Object.entries(entries).forEach(([key, value]) => window.localStorage.setItem(key, value));
    }, fixture.storage);
  }
  const page = await context.newPage();
  if (fixture.now) await page.clock.setFixedTime(new Date(fixture.now));
  await page.goto(`${appUrl.replace(/\/$/, "")}${route}`);
  await page.waitForLoadState("load");
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(SETTLE_MS);
  for (const selector of actions.clicks) {
    await page.click(selector);
    await page.waitForTimeout(SETTLE_MS);
  }
  for (const keys of actions.presses) {
    await page.keyboard.press(keys);
    await page.waitForTimeout(SETTLE_MS);
  }
  await page.screenshot({ path: file, fullPage: true, animations: "disabled" });
  await context.close();
}

// Lays the two screenshots side by side on one image, labeled, by screenshotting a tiny page.
async function placeSideBySide(browser, left, right, file) {
  const toData = (png) => `data:image/png;base64,${readFileSync(png).toString("base64")}`;
  const html = `<!doctype html><body style="margin:0;background:#888;font:600 14px system-ui;display:flex;gap:16px;padding:16px;align-items:flex-start">
    <figure style="margin:0"><figcaption style="padding:0 0 8px">mockup</figcaption><img src="${toData(left)}" style="display:block"></figure>
    <figure style="margin:0"><figcaption style="padding:0 0 8px">real page</figcaption><img src="${toData(right)}" style="display:block"></figure></body>`;
  const page = await browser.newPage({ viewport: { width: 800, height: 600 } });
  await page.setContent(html);
  await page.screenshot({ path: file, fullPage: true });
  await page.close();
}

async function compare(name, route, options) {
  const fixtureName = options.fixture ?? name;
  const fixture = readFixture(fixtureName);
  const mockupName = options.mockup ?? name;
  const { preview, themes } = listVariants(mockupName);
  const mockupServer = await startMockupServer(0);
  const appServer = await startApp(fixture);
  const browser = await openBrowser();
  const outDir = path.join(shotDir, "compare");
  mkdirSync(outDir, { recursive: true });
  const size = options.phone ? PHONE : { width: preview.width, height: preview.height };
  const sizeLabel = options.phone ? "phone" : "desktop";
  const mockupOptions = { ...(fixture.mockupOptions ?? {}), ...Object.fromEntries(new URLSearchParams(options.options ?? "")) };
  const usedThemes = themes.filter((value) => value !== null).length > 0 ? themes : ["light"];
  for (const theme of usedThemes) {
    const stem = path.join(outDir, [name, options.label, sizeLabel, theme].filter(Boolean).join("-"));
    await shootMockup(browser, readServerUrl(mockupServer), mockupName, { ...mockupOptions, theme }, size, `${stem}-mockup.png`);
    await shootApp(browser, appServer.resolvedUrls.local[0], route, fixture, size, theme, options, `${stem}-page.png`);
    await placeSideBySide(browser, `${stem}-mockup.png`, `${stem}-page.png`, `${stem}.png`);
    console.log(path.relative(repoDir, `${stem}.png`));
  }
  await browser.close();
  await appServer.close();
  mockupServer.close();
}

function readFlag(flags, name) {
  const flag = flags.find((arg) => arg.startsWith(`--${name}=`));
  const value = flag === undefined ? undefined : flag.slice(name.length + 3);
  return value;
}

function readFlags(flags, name) {
  const values = flags.filter((arg) => arg.startsWith(`--${name}=`)).map((arg) => arg.slice(name.length + 3));
  return values;
}

async function main() {
  const [mode, ...rest] = process.argv.slice(2);
  const flags = rest.filter((arg) => arg.startsWith("--"));
  const args = rest.filter((arg) => !arg.startsWith("--"));
  if (mode === "serve") {
    const server = await startMockupServer(Number(process.env.MOCKUP_PORT ?? 4400));
    console.log(`Mockups at ${readServerUrl(server).replace("127.0.0.1", "localhost")} (Ctrl+C to stop)`);
  } else if (mode === "mockups") {
    await shootMockups(args);
  } else if (mode === "compare" && args.length >= 2) {
    await compare(args[0], args[1], {
      phone: flags.includes("--phone"),
      mockup: readFlag(flags, "mockup"),
      fixture: readFlag(flags, "fixture"),
      options: readFlag(flags, "options"),
      label: readFlag(flags, "label"),
      clicks: readFlags(flags, "click"),
      presses: readFlags(flags, "press"),
    });
  } else {
    console.log("usage: shoot.mjs serve | mockups [Name ...] | compare <Mockup> <route> [--phone] [--mockup=Name] [--fixture=Name] [--options=a=b&c=d] [--click=selector] [--press=keys] [--label=name]");
    process.exitCode = 1;
  }
}

await main();
