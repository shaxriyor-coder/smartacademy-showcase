export function imageExtension(contentType: string, data: Buffer): string | null {
  switch (contentType) {
    case "image/png":
      return data.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))
        ? ".png"
        : null;
    case "image/jpeg":
      return data.length >= 3 && data[0] === 0xff && data[1] === 0xd8 && data[2] === 0xff
        ? ".jpg"
        : null;
    case "image/webp":
      return data.length >= 12 &&
        data.toString("ascii", 0, 4) === "RIFF" &&
        data.toString("ascii", 8, 12) === "WEBP"
        ? ".webp"
        : null;
    case "image/gif":
      return data.subarray(0, 6).toString("ascii") === "GIF87a" ||
        data.subarray(0, 6).toString("ascii") === "GIF89a"
        ? ".gif"
        : null;
    default:
      return null;
  }
}
