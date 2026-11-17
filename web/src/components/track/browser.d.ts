// The Chrome-only pieces the camera test uses that TypeScript's DOM types don't have yet. Each may be missing at
// run time, so each is optional.

declare var MediaStreamTrackProcessor: (new (init: { track: MediaStreamTrack }) => { readonly readable: ReadableStream<VideoFrame> }) | undefined;

interface Window {
  documentPictureInPicture?: { requestWindow(options?: { width?: number; height?: number }): Promise<Window> };
}

interface Performance {
  // Needs a cross-origin isolated page; counts the page and its workers, not the GPU.
  measureUserAgentSpecificMemory?(): Promise<{ bytes: number }>;
}

interface Navigator {
  deviceMemory?: number;
  getBattery?(): Promise<{ charging: boolean }>;
}
