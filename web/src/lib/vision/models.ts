// The models the browser runs, from the Pi's /api/models/ (signed in). Cache Storage keeps them, so the next visit
// doesn't download them again; the Pi gives a changed model a new name, so a kept copy is never stale.

export const MODEL_NAMES = {
  objects: "yolo26n_480x640.onnx",
  palm: "palm_detection_mediapipe_2023feb.onnx",
  hand: "handpose_estimation_mediapipe_2023feb.onnx",
};

const MODEL_CACHE = "dayanpi-models";

// A failed download throws with the Pi's status as its cause, so the page can send a 401 to the sign-in.
export async function loadModel(name: string): Promise<ArrayBuffer> {
  const url = `/api/models/${name}`;
  const cache = await caches.open(MODEL_CACHE);
  let response = await cache.match(url);
  if (response === undefined) {
    response = await fetch(url);
    if (!response.ok) {
      throw new Error(`${name}: the Pi answered ${response.status}`, { cause: response.status });
    }
    await cache.put(url, response.clone());
  }
  const model = await response.arrayBuffer();
  return model;
}
