declare module "mammoth" {
  export type ConvertResult = {
    value: string;
    messages: { type: string; message: string }[];
  };

  export function convertToHtml(
    input: { buffer: Buffer } | { path: string },
    options?: Record<string, unknown>,
  ): Promise<ConvertResult>;
}
