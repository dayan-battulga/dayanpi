import { expect } from "vitest";

// The expected value with every number swapped for expect.closeTo, for toEqual: the Python side's numbers, give or
// take float rounding.
export function near(expected: unknown, digits = 6): unknown {
  let matcher: unknown = expected;
  if (typeof expected === "number") {
    matcher = expect.closeTo(expected, digits);
  } else if (Array.isArray(expected)) {
    matcher = expected.map((item) => near(item, digits));
  } else if (expected !== null && typeof expected === "object") {
    matcher = Object.fromEntries(Object.entries(expected).map(([key, value]) => [key, near(value, digits)]));
  }
  return matcher;
}

// The biggest gap between two pixel arrays.
export function findLargestDifference(actual: ArrayLike<number>, expected: ArrayLike<number>): number {
  let largest = actual.length === expected.length ? 0 : Infinity;
  for (let index = 0; index < Math.min(actual.length, expected.length); index++) {
    largest = Math.max(largest, Math.abs(actual[index] - expected[index]));
  }
  return largest;
}
