# Architecture notes

- **One web platform:** the Next.js application is the source of truth for
  question-bank, classroom, assignment, and platform assessment data.
- **PostgreSQL with Prisma:** schema changes are versioned as migrations and
  applied explicitly during setup and deployment.
- **Separate checker service:** Python handles PDF and image processing;
  assessment ownership, scoring, and persistence stay in the platform.
- **Private service boundary:** the checker listens on a local/private
  interface and requires a shared token on non-health endpoints.
- **Telegram as an integration:** the bot supports existing workflows and
  opens the student cabinet as a Mini App. Telegram-signed data is verified
  server-side before creating a session.
- **Role-scoped access:** staff and family accounts use distinct session kinds;
  classroom ownership is checked by the API.
- **Paper and online delivery:** both modes use the same assignment and
  results model so progress can be reviewed together.

These notes summarize the current design. Confirm behavior against the code
and deployment configuration before making infrastructure or data-model
changes.
