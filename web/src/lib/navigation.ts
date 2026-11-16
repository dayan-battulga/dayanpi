// Every full page load (after signing in or out, or on a 401) goes through here: jsdom can't navigate, so tests mock this module.
export function loadPage(url: string): void {
  window.location.assign(url);
}
