import "@testing-library/jest-dom/vitest";

// jsdom has neither, and the page uses both.
window.matchMedia = (query: string) =>
  ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }) as MediaQueryList;
Element.prototype.animate = function () {
  return {} as Animation;
};
// Radix's checkbox measures itself with it.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
};
