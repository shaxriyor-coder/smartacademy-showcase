# Demo walkthrough

This guide describes a demo using fictional accounts and records. Create
disposable test users and a separate Telegram bot; never use production student
data, a production bot token, or real exam scans in a public demo.

## Before you start

- Start PostgreSQL and configure the local `.env` files.
- Apply migrations and seed a development administrator.
- Start the web platform and, if demonstrating paper tests, the checker.
- For Telegram Mini App flows, use a test bot and an HTTPS development tunnel.
- Use fictional student names, classrooms, results, and images.

## Suggested walkthrough

1. Sign in as a teacher and create a small question set.
2. Build an assessment and assign it to a demo classroom.
3. Show the student view and complete a sample online test.
4. Review the fictional result and topic-level progress.
5. If the checker is configured, generate a sample answer sheet and scan a
   synthetic test page.
6. Show the Telegram Mini App using a separate test account.

## Clean up

Use the end-to-end cleanup script to remove records created by the project's
test scripts. Review its preview before running it with `--apply`. Remove any
temporary test bot, database, tunnel, and local uploads when finished.
