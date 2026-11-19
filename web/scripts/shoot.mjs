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
//   --width=1200             this wide instead (BottomBar only shows below 1280 px), the mockup's own height
//   --mockup=RoomPhone       compare against a different mockup (the fixture still comes from the first name)
//   --fixture=Desk-away      use design/fixtures/Desk-away.json instead of Desk.json
//   --options="moment=day page&myState=away"   mockup options for this run, on top of the fixture's
//   --fill="#name=Riley"     type into a field before the clicks (selector=text, split at the last =, repeatable)
//   --click="text=Start"     click something on the real page before the shot (Playwright selector, repeatable)
//   --hover=".seat-hide"     hover something on the real page last, right before the shot (Playwright selector)
//   --press=Control+k        press keys on the real page before the shot (repeatable, after the clicks)
//   --wait=4000              wait this many ms more before the shot (the camera's models take a few seconds to load)
//   --label=palette          added to the file names, so different states don't overwrite each other
//   --reduced-motion         both sides with the system's reduced motion on ("reduced" in the file names)
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
  ".jpg": "image/jpeg",
  ".woff2": "font/woff2",
};
// The only folders a fixture's {"$file": ...} may answer from: the tracker's models and the seats' sample pictures.
const FILE_FOLDERS = [path.join(repoDir, "models"), path.join(repoDir, "design", "fixtures", "pictures")];
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
// globally installed playwright (Claude Code cloud sessions come with one). Chrome's fake camera (a test pattern)
// stands in for /track's; a fixture's "permissions" decides whether the page may have it.
const CHROME_ARGS = ["--use-fake-device-for-media-stream"];

async function openBrowser() {
  const launchers = [
    async () => (await import("playwright-core")).chromium.launch({ channel: process.env.SHOTS_CHANNEL ?? "chrome", args: CHROME_ARGS }),
    async () => (await import("playwright-core")).chromium.launch({ args: CHROME_ARGS }),
    async () => createRequire(import.meta.url)("playwright").chromium.launch({ args: CHROME_ARGS }),
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

async function shootMockup(browser, baseUrl, name, query, size, file, reducedMotion = "no-preference") {
  const page = await browser.newPage({ viewport: size, reducedMotion });
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
          // "streamEnds": the Pi goes quiet after one snapshot, and the browser waits ten minutes to retry, so the page
          // stays on Reconnecting for the shot.
          response.write(`${fixture.streamEnds ? "retry: 600000\n" : ""}data: ${JSON.stringify(fixture.stream ?? {})}\n\n`);
          if (fixture.streamEnds) response.end();
        } else if (pathOnly.startsWith("/api/") || pathOnly.startsWith("/video")) {
          const routes = fixture.routes ?? {};
          const body = routes[`${request.method} ${url}`] ?? routes[url] ?? routes[`${request.method} ${pathOnly}`] ?? routes[pathOnly];
          // A reply that isn't a 200 is {"$status": 429, "$headers": {"Retry-After": "28"}, "body": {...}},
          // {"$file": "models/x.onnx"} is that file from the repo's models/ (the tracker's models) or design/fixtures/pictures/
          // (the seats' made-up pictures), nothing else, and {"$hang": true} never answers (a camera stuck on Starting…).
          const status = body?.$status ?? 200;
          const file = body?.$file === undefined ? null : path.resolve(repoDir, body.$file);
          if (body === undefined) {
            response.writeHead(404, { "content-type": "application/json" }).end("{}");
          } else if (body.$hang === true) {
            request.on("close", () => response.destroy());
          } else if (file !== null) {
            const allowed = FILE_FOLDERS.some((folder) => file.startsWith(folder + path.sep)) && existsSync(file);
            if (allowed) {
              response.writeHead(200, { "content-type": TYPES[path.extname(file)] ?? "application/octet-stream" });
              createReadStream(file).pipe(response);
            } else {
              response.writeHead(404).end();
            }
          } else {
            response.writeHead(status, { "content-type": "application/json", ...body?.$headers }).end(JSON.stringify(body?.$status === undefined ? body : body.body));
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
    reducedMotion: actions.reducedMotion ? "reduce" : "no-preference",
  });
  if (fixture.permissions) {
    await context.grantPermissions(fixture.permissions);
  }
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
  for (const fill of actions.fills) {
    const split = fill.lastIndexOf("=");
    await page.fill(fill.slice(0, split), fill.slice(split + 1));
  }
  for (const selector of actions.clicks) {
    await page.click(selector);
    await page.waitForTimeout(SETTLE_MS);
  }
  for (const keys of actions.presses) {
    await page.keyboard.press(keys);
    await page.waitForTimeout(SETTLE_MS);
  }
  await page.waitForTimeout(Number(actions.wait ?? 0));
  // A click scrolls its target into view even when it's already showing, and fixed things (dialogs) follow the scroll.
  await page.evaluate(() => window.scrollTo(0, 0));
  if (actions.hover) await page.hover(actions.hover);
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
  const size = options.phone ? PHONE : { width: Number(options.width ?? preview.width), height: preview.height };
  const sizeLabel = options.phone ? "phone" : options.width ? `w${options.width}` : "desktop";
  const mockupOptions = { ...(fixture.mockupOptions ?? {}), ...Object.fromEntries(new URLSearchParams(options.options ?? "")) };
  const usedThemes = themes.filter((value) => value !== null).length > 0 ? themes : ["light"];
  for (const theme of usedThemes) {
    const stem = path.join(outDir, [name, options.label, sizeLabel, options.reducedMotion ? "reduced" : null, theme].filter(Boolean).join("-"));
    await shootMockup(browser, readServerUrl(mockupServer), mockupName, { ...mockupOptions, theme }, size, `${stem}-mockup.png`, options.reducedMotion ? "reduce" : "no-preference");
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
      width: readFlag(flags, "width"),
      fixture: readFlag(flags, "fixture"),
      options: readFlag(flags, "options"),
      label: readFlag(flags, "label"),
      fills: readFlags(flags, "fill"),
      clicks: readFlags(flags, "click"),
      presses: readFlags(flags, "press"),
      hover: readFlag(flags, "hover"),
      wait: readFlag(flags, "wait"),
      reducedMotion: flags.includes("--reduced-motion"),
    });
  } else {
    console.log("usage: shoot.mjs serve | mockups [Name ...] | compare <Mockup> <route> [--phone] [--width=px] [--mockup=Name] [--fixture=Name] [--options=a=b&c=d] [--fill=selector=text] [--click=selector] [--press=keys] [--hover=selector] [--wait=ms] [--label=name] [--reduced-motion]");
    process.exitCode = 1;
  }
}

await main();
