// The Chrome-only pieces the camera test and the tracker use that TypeScript's DOM types don't have yet. Each may be missing at
// run time, so each is optional.

// A camera's track reads as VideoFrames, a microphone's (the room's talk) as AudioData.
declare var MediaStreamTrackProcessor: (new <Frame = VideoFrame>(init: { track: MediaStreamTrack }) => { readonly readable: ReadableStream<Frame> }) | undefined;

interface Window {
  documentPictureInPicture?: { requestWindow(options?: { width?: number; height?: number }): Promise<Window> };
}

interface Performance {
  // Needs a cross-origin isolated page; counts the page and its workers, not the GPU.
  measureUserAgentSpecificMemory?(): Promise<{ bytes: number }>;
}

interface BatteryManager extends EventTarget {
  readonly charging: boolean;
  readonly level: number; // 0 to 1
  onlevelchange: (() => void) | null;
  onchargingchange: (() => void) | null;
}

interface Navigator {
  deviceMemory?: number;
  getBattery?(): Promise<BatteryManager>;
}
