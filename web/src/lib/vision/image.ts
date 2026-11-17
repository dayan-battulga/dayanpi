// What the Pi's vision code gets from OpenCV, for the browser: a picture as 3 bytes a pixel, row by row, and the
// handful of cv2 calls the pipeline makes on it. The Pi's pictures are BGR and the browser's RGB; the Pi swaps
// to RGB when it makes each model's input, so the browser's are already what the models want.

export interface Picture {
  width: number;
  height: number;
  data: Uint8ClampedArray;
}

// cv2's 2x3 affine matrices, as rows.
export type Affine = number[][];

const CHANNELS = 3;

// Python's round(): halves go to the even neighbour, where Math.round always goes up. It's an int there, so never -0.
export function roundHalfEven(value: number): number {
  const floor = Math.floor(value);
  const rounded = (value - floor === 0.5 ? floor + (floor % 2 === 0 ? 0 : 1) : Math.round(value)) + 0;
  return rounded;
}

export function readRgba(rgba: Uint8ClampedArray, width: number, height: number): Picture {
  const data = new Uint8ClampedArray(width * height * CHANNELS);
  for (let pixel = 0; pixel < width * height; pixel++) {
    data[pixel * 3] = rgba[pixel * 4];
    data[pixel * 3 + 1] = rgba[pixel * 4 + 1];
    data[pixel * 3 + 2] = rgba[pixel * 4 + 2];
  }
  const picture = { width, height, data };
  return picture;
}

interface Tap {
  low: number;
  high: number;
  weight: number;
}

// cv2.INTER_LINEAR's sample points: pixel centers line up, and the edges repeat.
function findTaps(source: number, target: number): Tap[] {
  const scale = source / target;
  const taps = Array.from({ length: target }, (_, index) => {
    const position = Math.fround((index + 0.5) * scale - 0.5);
    const floor = Math.floor(position);
    const low = Math.min(Math.max(floor, 0), source - 1);
    const weight = floor < 0 || floor >= source - 1 ? 0 : position - floor;
    return { low, high: Math.min(low + 1, source - 1), weight };
  });
  return taps;
}

// cv2.resize(picture, (width, height)), bilinear. OpenCV does it in fixed point, so a pixel can come out one level off.
export function resizePicture(picture: Picture, width: number, height: number): Picture {
  const columns = findTaps(picture.width, width);
  const rows = findTaps(picture.height, height);
  const source = picture.data;
  const data = new Uint8ClampedArray(width * height * CHANNELS);
  const stride = picture.width * CHANNELS;
  for (let y = 0; y < height; y++) {
    const row = rows[y];
    const top = row.low * stride;
    const bottom = row.high * stride;
    for (let x = 0; x < width; x++) {
      const column = columns[x];
      const left = column.low * CHANNELS;
      const right = column.high * CHANNELS;
      const out = (y * width + x) * CHANNELS;
      for (let channel = 0; channel < CHANNELS; channel++) {
        const upper = source[top + left + channel] * (1 - column.weight) + source[top + right + channel] * column.weight;
        const lower = source[bottom + left + channel] * (1 - column.weight) + source[bottom + right + channel] * column.weight;
        data[out + channel] = upper * (1 - row.weight) + lower * row.weight;
      }
    }
  }
  const resized = { width, height, data };
  return resized;
}

export interface Padding {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

// cv2.copyMakeBorder(..., cv2.BORDER_CONSTANT, value=(value, value, value)).
export function padPicture(picture: Picture, padding: Padding, value: number): Picture {
  const width = picture.width + padding.left + padding.right;
  const height = picture.height + padding.top + padding.bottom;
  const data = new Uint8ClampedArray(width * height * CHANNELS).fill(value);
  const rowBytes = picture.width * CHANNELS;
  for (let y = 0; y < picture.height; y++) {
    const from = y * rowBytes;
    data.set(picture.data.subarray(from, from + rowBytes), ((y + padding.top) * width + padding.left) * CHANNELS);
  }
  const padded = { width, height, data };
  return padded;
}

// picture[y1:y2, x1:x2], with whole-pixel bounds already inside the picture.
export function cropPicture(picture: Picture, x1: number, y1: number, x2: number, y2: number): Picture {
  const width = x2 - x1;
  const height = y2 - y1;
  const data = new Uint8ClampedArray(width * height * CHANNELS);
  for (let y = 0; y < height; y++) {
    const from = ((y + y1) * picture.width + x1) * CHANNELS;
    data.set(picture.data.subarray(from, from + width * CHANNELS), y * width * CHANNELS);
  }
  const cropped = { width, height, data };
  return cropped;
}

// cv2.getRotationMatrix2D: turns by angle degrees (counterclockwise on screen) and scales, around a center. It takes
// the center as a Point2f, so the center goes through float32 first.
export function findRotation(centerX: number, centerY: number, angle: number, scale: number): Affine {
  const radians = angle * (Math.PI / 180);
  const alpha = Math.cos(radians) * scale;
  const beta = Math.sin(radians) * scale;
  const x = Math.fround(centerX);
  const y = Math.fround(centerY);
  const rotation = [
    [alpha, beta, (1 - alpha) * x - beta * y],
    [-beta, alpha, beta * x + (1 - alpha) * y],
  ];
  return rotation;
}

// cv2.invertAffineTransform.
export function invertAffine(matrix: Affine): Affine {
  const [[a, b, c], [d, e, f]] = matrix;
  const determinant = a * e - b * d;
  const inverse = determinant !== 0 ? 1 / determinant : 0;
  const a11 = e * inverse;
  const a22 = a * inverse;
  const a12 = -b * inverse;
  const a21 = -d * inverse;
  const inverted = [
    [a11, a12, -a11 * c - a12 * f],
    [a21, a22, -a21 * c - a22 * f],
  ];
  return inverted;
}

// cv2.warpAffine(picture, warp, (size, size)): bilinear, black outside the picture.
export function warpPicture(picture: Picture, warp: Affine, size: number): Picture {
  const [[a, b, c], [d, e, f]] = invertAffine(warp);
  const source = picture.data;
  const data = new Uint8ClampedArray(size * size * CHANNELS);
  const read = (x: number, y: number, channel: number) =>
    x >= 0 && y >= 0 && x < picture.width && y < picture.height ? source[(y * picture.width + x) * CHANNELS + channel] : 0;
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const sourceX = a * x + b * y + c;
      const sourceY = d * x + e * y + f;
      const left = Math.floor(sourceX);
      const top = Math.floor(sourceY);
      const across = sourceX - left;
      const down = sourceY - top;
      const out = (y * size + x) * CHANNELS;
      for (let channel = 0; channel < CHANNELS; channel++) {
        const upper = read(left, top, channel) * (1 - across) + read(left + 1, top, channel) * across;
        const lower = read(left, top + 1, channel) * (1 - across) + read(left + 1, top + 1, channel) * across;
        data[out + channel] = upper * (1 - down) + lower * down;
      }
    }
  }
  const warped = { width: size, height: size, data };
  return warped;
}
