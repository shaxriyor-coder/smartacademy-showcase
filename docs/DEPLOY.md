# Self-hosting overview

This repository includes example configuration under `deploy/`; it does not
include production credentials or a preconfigured public service. Adapt the
examples to your own infrastructure and review every value before deployment.

## Production checklist

1. Use a supported Linux host with PostgreSQL, Node.js, Python, Tesseract, and
   the system libraries listed in [checker/README.md](../checker/README.md).
2. Create dedicated database users with least-privilege access. Keep PostgreSQL
   private; do not expose its port publicly.
3. Create local `.env` files from the example files. Generate unique
   `AUTH_SECRET`, `CHECKER_TOKEN`, and QR signing secrets. Never copy secrets
   from examples, logs, screenshots, or another environment.
4. Restrict the checker to localhost or a private network and configure the
   same strong token in the checker and platform environments.
5. Put a maintained HTTPS reverse proxy in front of the web application.
   Configure request-size and timeout limits for uploads and scans.
6. Apply Prisma migrations, build the application, and run services under a
   dedicated non-root operating-system account.
7. Configure Telegram only with a bot and domain that you control. Do not run
   two polling processes with the same Telegram bot token.
8. Configure encrypted, access-controlled database backups and test restores.
   Define a retention policy for student identities, scans, and test results.
9. Monitor service health and errors without logging credentials or student
   records. Keep operating-system and application dependencies updated.

The files in `deploy/` are starting points, not a complete security review.
Do not use a public deployment for real student data until authentication,
authorization, privacy, backup, and incident-response requirements have been
reviewed for your deployment.
