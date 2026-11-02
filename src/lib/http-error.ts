// An error whose message is written for the person using the page (Uzbek, and
// says what to do). handleApiError (src/lib/api-error.ts) returns it as-is
// with its status instead of the generic 500.
export class HttpError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}
