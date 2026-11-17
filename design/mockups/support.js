// dc-lite: a small stand-in for the design canvas's runtime, so the mockups in this folder open
// in a plain browser. Run `npm run mockups` in web/ (it serves this folder plus the Geist fonts
// from web/node_modules, so nothing loads from the internet), then open for example
//   http://localhost:4400/Desk.dc.html?theme=dark&moment=all%20done
// A mockup's options (the canvas "tweaks", listed in its data-props) come from the URL; anything
// left out uses its default. It covers what these files use: {{a.b}} holes, <sc-if value>,
// <sc-for list as>, <dc-import name>, on* handlers, and a Component class with renderVals()
// and setState(). Clicking around works like Play mode on the canvas.
(function () {
  "use strict";

  const HOLE = /\{\{\s*([^{}]+?)\s*\}\}/g;
  const WHOLE = /^\s*\{\{\s*([^{}]+?)\s*\}\}\s*$/;
  const FONTS = [
    ["Geist", "geist", "geist"],
    ["Geist Mono", "geist-mono", "geist-mono"],
  ];
  const SUBSETS = [
    ["latin", "U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD"],
    ["latin-ext", "U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7, U+02DD-02FF, U+0304, U+0308, U+0329, U+1D00-1DBF, U+1E00-1E9F, U+1EF2-1EFF, U+2020, U+20A0-20AB, U+20AD-20C0, U+2113, U+2C60-2C7F, U+A720-A7FF"],
  ];
  const loaded = new Map();
  const addedStyles = new Set();

  class DCLogic {
    constructor(props) {
      this.props = props || {};
      this.state = null;
      this.__render = null;
    }

    setState(partial) {
      const next = typeof partial === "function" ? partial(this.state || {}, this.props) : partial;
      this.state = Object.assign({}, this.state, next);
      if (this.__render) this.__render();
    }
  }

  function parseValue(raw) {
    let value = raw;
    if (raw === "true") value = true;
    else if (raw === "false") value = false;
    else if (raw !== "" && !Number.isNaN(Number(raw))) value = Number(raw);
    return value;
  }

  function lookup(expr, scope) {
    let value;
    if (expr === "true") value = true;
    else if (expr === "false") value = false;
    else if (expr === "null") value = null;
    else if (/^-?\d+(\.\d+)?$/.test(expr)) value = Number(expr);
    else if (/^(['"]).*\1$/.test(expr)) value = expr.slice(1, -1);
    else {
      const parts = expr.split(".");
      value = scope[parts[0]];
      for (let i = 1; i < parts.length && value != null; i += 1) value = value[parts[i]];
    }
    return value;
  }

  function fill(text, scope) {
    return text.replace(HOLE, (match, expr) => {
      const value = lookup(expr.trim(), scope);
      return value == null || value === false ? "" : String(value);
    });
  }

  function readExpr(el, name) {
    const raw = el.getAttribute(name) || "";
    const whole = WHOLE.exec(raw);
    return whole ? whole[1].trim() : raw.trim();
  }

  // One listener per event type that calls whatever handler the latest render gave the element,
  // so a re-render never leaves a click running an old closure.
  function setHandlers(el, handlers) {
    el.__dcHandlers = handlers;
    if (!el.__dcBound) el.__dcBound = new Set();
    Object.keys(handlers).forEach((type) => {
      if (!el.__dcBound.has(type)) {
        el.__dcBound.add(type);
        el.addEventListener(type, (event) => {
          const handler = el.__dcHandlers && el.__dcHandlers[type];
          if (typeof handler === "function") handler(event);
        });
      }
    });
  }

  function expandChildren(node, scope, out) {
    node.childNodes.forEach((child) => expand(child, scope, out));
  }

  function expandElement(node, scope) {
    const el = node.cloneNode(false);
    const handlers = {};
    Array.from(node.attributes).forEach((attr) => {
      const name = attr.name;
      const whole = WHOLE.exec(attr.value);
      if (name.startsWith("hint-")) {
        el.removeAttribute(name);
      } else if (/^on[a-z]+$/.test(name)) {
        el.removeAttribute(name);
        const handler = whole ? lookup(whole[1].trim(), scope) : null;
        if (typeof handler === "function") handlers[name.slice(2)] = handler;
      } else if (whole) {
        const value = lookup(whole[1].trim(), scope);
        if (value === true) el.setAttribute(name, name.startsWith("aria-") ? "true" : "");
        else if (value === false && name.startsWith("aria-")) el.setAttribute(name, "false");
        else if (value === false || value == null) el.removeAttribute(name);
        else el.setAttribute(name, String(value));
      } else if (attr.value.indexOf("{{") !== -1) {
        el.setAttribute(name, fill(attr.value, scope));
      }
    });
    setHandlers(el, handlers);
    const kids = [];
    expandChildren(node, scope, kids);
    kids.forEach((kid) => el.appendChild(kid));
    if (el.localName === "input") el.checked = el.hasAttribute("checked");
    return el;
  }

  function expand(node, scope, out) {
    if (node.nodeType === Node.TEXT_NODE) {
      out.push(document.createTextNode(fill(node.nodeValue, scope)));
    } else if (node.nodeType === Node.ELEMENT_NODE) {
      const tag = node.localName;
      if (tag === "sc-if") {
        if (lookup(readExpr(node, "value"), scope)) expandChildren(node, scope, out);
      } else if (tag === "sc-for") {
        const list = lookup(readExpr(node, "list"), scope);
        const name = node.getAttribute("as") || "item";
        (Array.isArray(list) ? list : []).forEach((item, index) => {
          const inner = Object.create(scope);
          inner[name] = item;
          inner[name + "Index"] = index;
          expandChildren(node, inner, out);
        });
      } else if (tag === "dc-import") {
        out.push(placeImport(node, scope));
      } else if (tag !== "helmet") {
        out.push(expandElement(node, scope));
      }
    }
  }

  function placeImport(node, scope) {
    const name = node.getAttribute("name");
    const props = {};
    Array.from(node.attributes).forEach((attr) => {
      if (attr.name !== "name" && !attr.name.startsWith("hint-")) {
        const key = attr.name.replace(/-([a-z])/g, (match, letter) => letter.toUpperCase());
        const whole = WHOLE.exec(attr.value);
        props[key] = whole ? lookup(whole[1].trim(), scope) : parseValue(attr.value);
      }
    });
    const slot = document.createElement("div");
    slot.setAttribute("data-dc-import", name);
    slot.__dcImport = { key: name + JSON.stringify(props) };
    loadParts(name + ".dc.html")
      .then((parts) => mount(slot, parts, props))
      .catch((error) => console.error("dc-lite: could not import " + name, error));
    return slot;
  }

  function morphChildren(parent, nextNodes) {
    const current = Array.from(parent.childNodes);
    nextNodes.forEach((next, index) => {
      const node = current[index];
      if (node) morphNode(parent, node, next);
      else parent.appendChild(next);
    });
    for (let i = nextNodes.length; i < current.length; i += 1) parent.removeChild(current[i]);
  }

  // Updates the page in place instead of rebuilding it, so entrance animations don't replay on
  // every click (only elements whose animation actually changes restart).
  function morphNode(parent, node, next) {
    const sameKind = node.nodeType === next.nodeType && node.nodeName === next.nodeName && node.namespaceURI === next.namespaceURI;
    if (next.__dcImport || node.__dcImport) {
      if (!(node.__dcImport && next.__dcImport && node.__dcImport.key === next.__dcImport.key)) parent.replaceChild(next, node);
    } else if (!sameKind) {
      parent.replaceChild(next, node);
    } else if (node.nodeType === Node.TEXT_NODE) {
      if (node.nodeValue !== next.nodeValue) node.nodeValue = next.nodeValue;
    } else {
      Array.from(node.attributes).forEach((attr) => {
        if (!next.hasAttribute(attr.name)) node.removeAttribute(attr.name);
      });
      Array.from(next.attributes).forEach((attr) => {
        if (node.getAttribute(attr.name) !== attr.value) node.setAttribute(attr.name, attr.value);
      });
      setHandlers(node, next.__dcHandlers || {});
      if (node.localName === "input") node.checked = next.hasAttribute("checked");
      morphChildren(node, Array.from(next.childNodes));
    }
  }

  function addStyle(css) {
    if (!addedStyles.has(css)) {
      addedStyles.add(css);
      const style = document.createElement("style");
      style.textContent = css;
      document.head.appendChild(style);
    }
  }

  function addFonts() {
    const faces = [];
    FONTS.forEach(([family, folder, file]) => {
      SUBSETS.forEach(([subset, range]) => {
        faces.push("@font-face{font-family:'" + family + "';font-style:normal;font-display:block;font-weight:100 900;" +
          "src:url('/__fonts/" + folder + "/" + file + "-" + subset + "-wght-normal.woff2') format('woff2-variations');unicode-range:" + range + "}");
      });
    });
    addStyle(faces.join("\n") + "\nx-dc{display:block}");
  }

  // The helmet's <style> goes into <head>; its Google Fonts <link> is dropped for the local copy.
  function addHelmet(helmet) {
    if (helmet) {
      helmet.querySelectorAll("style").forEach((style) => addStyle(style.textContent));
      helmet.querySelectorAll("link").forEach((link) => {
        const href = link.getAttribute("href") || "";
        if (!/fonts\.(googleapis|gstatic)\.com/.test(href) && !document.head.querySelector('link[href="' + href + '"]')) {
          document.head.appendChild(link.cloneNode(true));
        }
      });
    }
  }

  function readDefaults(script) {
    let spec = {};
    try {
      spec = JSON.parse(script.getAttribute("data-props") || "{}");
    } catch (error) {
      console.error("dc-lite: bad data-props", error);
    }
    const props = {};
    Object.keys(spec).forEach((key) => {
      if (key[0] !== "$" && spec[key] && "default" in spec[key]) props[key] = spec[key].default;
    });
    return props;
  }

  function readParts(doc) {
    const root = doc.querySelector("x-dc");
    const script = doc.querySelector("script[data-dc-script]");
    const parts = { root: root ? root.cloneNode(true) : null, script: script };
    parts.helmet = parts.root ? parts.root.querySelector("helmet") : null;
    return parts;
  }

  function loadParts(url) {
    if (!loaded.has(url)) {
      const parts = fetch(url)
        .then((response) => response.text())
        .then((html) => readParts(new DOMParser().parseFromString(html, "text/html")));
      loaded.set(url, parts);
    }
    return loaded.get(url);
  }

  function mount(target, parts, givenProps) {
    addHelmet(parts.helmet);
    const props = Object.assign(readDefaults(parts.script), givenProps);
    const Component = new Function("DCLogic", parts.script.textContent + "\nreturn Component;")(DCLogic);
    const instance = new Component(props);
    if (!instance.props) instance.props = props;
    const render = () => {
      let vals = {};
      try {
        vals = instance.renderVals() || {};
      } catch (error) {
        console.error("dc-lite: renderVals failed", error);
      }
      const scope = Object.assign(Object.create(null), vals);
      const out = [];
      parts.root.childNodes.forEach((child) => expand(child, scope, out));
      morphChildren(target, out);
    };
    instance.__render = render;
    render();
    return instance;
  }

  function start() {
    const page = readParts(document);
    const root = document.querySelector("x-dc");
    if (root && page.root && page.script) {
      const urlProps = {};
      new URLSearchParams(window.location.search).forEach((value, key) => {
        urlProps[key] = parseValue(value);
      });
      addFonts();
      root.replaceChildren();
      mount(root, page, urlProps);
    }
    const ready = document.fonts ? document.fonts.ready : Promise.resolve();
    ready.then(() => document.documentElement.setAttribute("data-dc-ready", "true"));
  }

  window.DCLogic = DCLogic;
  // Hide the raw template (holes and all) until the first render.
  document.documentElement.style.visibility = "hidden";
  const reveal = () => {
    document.documentElement.style.visibility = "";
  };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      start();
      reveal();
    });
  } else {
    start();
    reveal();
  }
})();
