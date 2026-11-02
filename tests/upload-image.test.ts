import { test } from "node:test";
import assert from "node:assert/strict";
import { imageExtension } from "../src/lib/upload-image";

test("accepts supported image signatures and derives the filename extension", () => {
  assert.equal(
    imageExtension("image/png", Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])),
    ".png",
  );
  assert.equal(imageExtension("image/jpeg", Buffer.from([0xff, 0xd8, 0xff])), ".jpg");
  assert.equal(imageExtension("image/webp", Buffer.from("RIFF0000WEBP")), ".webp");
  assert.equal(imageExtension("image/gif", Buffer.from("GIF89a")), ".gif");
});

test("rejects mismatched, unsupported, or incomplete image data", () => {
  assert.equal(imageExtension("image/png", Buffer.from("<svg></svg>")), null);
  assert.equal(imageExtension("image/svg+xml", Buffer.from("<svg></svg>")), null);
  assert.equal(imageExtension("image/webp", Buffer.from("RIFF")), null);
});
