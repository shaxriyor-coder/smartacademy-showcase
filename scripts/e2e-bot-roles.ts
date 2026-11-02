// End-to-end check of Telegram sign-in roles (docs/DECISIONS.md #23):
// - without smartbot's database, the staff page's Telegram IDs decide;
// - SMARTBOT_SUPERADMIN_IDS gives a password-less super admin account, once;
// - with the database, its admins table decides — bot staff get their panel,
//   everyone else the family cabinet;
// - if the database can't be reached, the last known role is kept.
// smartbot's database is only read. Platform rows it creates are deleted, and
// bot admins who already have a platform account are skipped, not touched.
//
//   npx tsx scripts/e2e-bot-roles.ts     # SMARTBOT_DB_NAME defaults to smartbot_db
import "dotenv/config";
import pg from "pg";
import { prisma } from "../src/lib/prisma";
import { staffRoleFromBot } from "../src/lib/roles";
import { closeSmartbotPools, smartbotDatabaseUrl } from "../src/lib/smartbot";
import { telegramSignIn } from "../src/lib/telegram-signin";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(`ASSERT: ${message}`);
}

const saved = {
  SMARTBOT_DATABASE_URL: process.env.SMARTBOT_DATABASE_URL,
  SMARTBOT_DB_NAME: process.env.SMARTBOT_DB_NAME,
  SMARTBOT_SUPERADMIN_IDS: process.env.SMARTBOT_SUPERADMIN_IDS,
};
function setEnv(values: Partial<typeof saved>) {
  for (const key of Object.keys(saved) as (keyof typeof saved)[]) {
    if (values[key] === undefined) delete process.env[key];
    else process.env[key] = values[key];
  }
}

async function main() {
  const tail = String(Date.now()).slice(-9);
  const [teacherChat, familyChat, superChat] = [`7${tail}`, `8${tail}`, `9${tail}`];
  const createdUsers: string[] = [];
  const createdAccounts: string[] = [];

  try {
    // 1. No bot database: a Telegram ID on the staff page makes a teacher.
    setEnv({});
    const teacher = await prisma.user.create({
      data: { name: "E2E Telegram o'qituvchi", role: "TEACHER", telegramChatId: teacherChat },
    });
    createdUsers.push(teacher.id);
    let session = await telegramSignIn({ id: teacherChat, first_name: "Test" });
    assert(session.kind === "admin" && session.role === "TEACHER" && session.id === teacher.id, "bazasiz: Telegram ID bo'yicha o'qituvchi");
    session = await telegramSignIn({ id: familyChat, first_name: "Ota" });
    createdAccounts.push(familyChat);
    assert(session.kind === "student", "bazasiz: boshqa odam — oila kabineti");

    // 2. A super admin from the bot's list: a password-less account, reused.
    setEnv({ SMARTBOT_SUPERADMIN_IDS: superChat });
    const first = await telegramSignIn({ id: superChat, first_name: "Bosh", last_name: "Admin" });
    assert(first.kind === "admin" && first.role === "SUPER_ADMIN", "superadmin paneli");
    createdUsers.push(first.id);
    const again = await telegramSignIn({ id: superChat, first_name: "Bosh" });
    assert(again.id === first.id, "ikkinchi kirishda o'sha akkaunt");
    const row = await prisma.user.findUniqueOrThrow({ where: { id: first.id } });
    assert(row.name === "Bosh Admin" && row.email === null && row.passwordHash === null, "parolsiz xodim, ismi Telegram'dan");

    // 3. With the bot's database: its admins decide.
    const withDb = {
      SMARTBOT_DATABASE_URL: saved.SMARTBOT_DATABASE_URL,
      SMARTBOT_DB_NAME: saved.SMARTBOT_DATABASE_URL ? undefined : saved.SMARTBOT_DB_NAME || "smartbot_db",
    };
    setEnv(withDb);
    const client = new pg.Client({ connectionString: smartbotDatabaseUrl()!, options: "-c default_transaction_read_only=on" });
    await client.connect();
    const admins = (await client.query<{ id: string; role: string }>("SELECT id::text AS id, role FROM admins")).rows;
    await client.end();
    let checked = 0;
    for (const a of admins) {
      if (await prisma.user.findUnique({ where: { telegramChatId: a.id } })) continue; // a real account: leave it alone
      const s = await telegramSignIn({ id: a.id, first_name: "E2E" });
      const expected = staffRoleFromBot(a.role);
      if (s.kind === "admin") createdUsers.push(s.id);
      else createdAccounts.push(a.id);
      assert(expected ? s.kind === "admin" && s.role === expected : s.kind === "student", `bot roli "${a.role}" to'g'ri panelni ochadi`);
      checked += 1;
    }
    // The staff-page teacher isn't staff in the bot: the bot wins.
    session = await telegramSignIn({ id: teacherChat, first_name: "Test" });
    createdAccounts.push(teacherChat);
    assert(session.kind === "student", "botda xodim bo'lmagan odam — kabinet");

    // 4. Bot database down: the super admin keeps the last known role.
    setEnv({ SMARTBOT_DATABASE_URL: "postgresql://nobody:nothing@127.0.0.1:1/none" });
    const offline = await telegramSignIn({ id: superChat, first_name: "Bosh" });
    assert(offline.kind === "admin" && offline.role === "SUPER_ADMIN", "baza ishlamasa oxirgi ma'lum rol");

    console.log(`NATIJA: HAMMASI TO'G'RI (botdagi ${checked} ta xodim roli tekshirildi)`);
  } finally {
    setEnv(saved);
    await prisma.user.deleteMany({ where: { id: { in: createdUsers } } });
    await prisma.telegramAccount.deleteMany({ where: { id: { in: createdAccounts } } });
    await closeSmartbotPools();
  }
}

main()
  .catch((err) => {
    console.error(err);
    process.exitCode = 1;
  })
  .finally(() => prisma.$disconnect());
