import pg from "pg";

// Staff roles live in smartbot — the Telegram bot this platform opens from as
// a Mini App (docs/DECISIONS.md #23). Read-only: superadmins come from the same
// SUPERADMIN_IDS list the bot uses, everyone else from its `admins` table
// (smartbot/utils/roles.py). The platform never writes to that database.

export type BotRole = "superadmin" | "admin" | "teacher" | "smm_manager" | "reception";

type Env = Record<string, string | undefined>;

export function parseIds(value: string | undefined): Set<string> {
  return new Set(
    (value ?? "")
      .split(",")
      .map((x) => x.trim())
      .filter((x) => /^\d+$/.test(x)),
  );
}

// SMARTBOT_DATABASE_URL as smartbot's own .env writes it (the SQLAlchemy
// "+asyncpg" driver suffix is dropped), or SMARTBOT_DB_NAME: a database on the
// platform's own Postgres server, with the platform's credentials.
export function smartbotDatabaseUrl(env: Env = process.env): string | null {
  if (env.SMARTBOT_DATABASE_URL) {
    return env.SMARTBOT_DATABASE_URL.replace(/^postgresql\+asyncpg:/, "postgresql:");
  }
  if (env.SMARTBOT_DB_NAME && env.DATABASE_URL) {
    const url = new URL(env.DATABASE_URL);
    url.pathname = `/${env.SMARTBOT_DB_NAME}`;
    url.search = "";
    return url.toString();
  }
  return null;
}

const pools = new Map<string, pg.Pool>();

function pool(url: string) {
  let p = pools.get(url);
  if (!p) {
    p = new pg.Pool({
      connectionString: url,
      max: 2,
      idleTimeoutMillis: 30_000,
      // Kutish MUDDATLARI shart: bu baza boshqa xizmatniki (smartbot).
      // U yopiq port yoki firewall ortida qolsa, ulanish xato BERMAY
      // osilib turadi — sozlamasiz `pg` cheksiz kutadi va u bilan birga
      // Telegram orqali kirish ham "Kirilmoqda..." da qotib qolardi.
      // Xato bo'lsa chaqiruvchi eski rolga qaytadi (telegram-signin.ts).
      connectionTimeoutMillis: 5_000,
      query_timeout: 5_000,
      statement_timeout: 5_000,
      // Belt and braces on top of a read-only database user.
      options: "-c default_transaction_read_only=on",
    });
    pools.set(url, p);
  }
  return p;
}

// The person's staff role in the bot, or null if they're an ordinary user.
// Throws when the bot's database is configured but can't be read.
export async function smartbotRole(telegramId: string, env: Env = process.env): Promise<BotRole | null> {
  if (parseIds(env.SMARTBOT_SUPERADMIN_IDS).has(telegramId)) return "superadmin";
  const url = smartbotDatabaseUrl(env);
  if (!url || !/^\d+$/.test(telegramId)) return null;
  const { rows } = await pool(url).query<{ role: string }>("SELECT role FROM admins WHERE id = $1", [telegramId]);
  return (rows[0]?.role as BotRole | undefined) ?? null;
}

export type SmartbotOlympiad = {
  id: number;
  name: string;
  code: string | null;
  examDate: string | null; // YYYY-MM-DD
  isActive: boolean;
};

// Botda yaratilgan olimpiadalar. Platformada test "olimpiada uchun" deb
// belgilanganda aynan shu ro'yxatdan tanlanadi (docs/DECISIONS.md #31) —
// nomini qo'lda yozish yo'q, shunda ikkala tomonda bir xil nom turadi.
// null — smartbot bazasi umuman sozlanmagan.
export async function smartbotOlympiads(env: Env = process.env): Promise<SmartbotOlympiad[] | null> {
  const url = smartbotDatabaseUrl(env);
  if (!url) return null;
  const { rows } = await pool(url).query<{
    id: number;
    name: string;
    code: string | null;
    exam_date: Date | null;
    is_active: boolean;
  }>(
    `SELECT id, name, code, exam_date, is_active FROM olympiads
      ORDER BY is_active DESC, exam_date DESC NULLS LAST, id DESC`,
  );
  return rows.map((r) => ({
    id: r.id,
    name: r.name,
    code: r.code,
    // pg `date` ustunini mahalliy vaqtdagi Date qilib beradi — sanani
    // siljitmaslik uchun ISO emas, kun/oy/yilni o'zidan yig'amiz.
    examDate: r.exam_date
      ? `${r.exam_date.getFullYear()}-${String(r.exam_date.getMonth() + 1).padStart(2, "0")}-${String(r.exam_date.getDate()).padStart(2, "0")}`
      : null,
    isActive: r.is_active,
  }));
}

export type SmartbotChildOlympiad = {
  name: string;
  examDate: string | null; // YYYY-MM-DD
  grade: number | null; // yozilish paytidagi sinf
  score: number | null;
  place: number | null;
};

export type SmartbotChild = {
  id: number;
  firstName: string;
  lastName: string;
  birthDate: string; // YYYY-MM-DD
  school: string | null;
  grade: number; // joriy sinf — kiritilgan sinfdan hisoblanadi
  olympiads: SmartbotChildOlympiad[];
};

export const MAX_GRADE = 11;

// 1-sentabrdan yangi o'quv yili (smartbot/utils/utility.py bilan bir xil).
export function academicYearStart(today: Date = new Date()): number {
  return today.getMonth() >= 8 ? today.getFullYear() : today.getFullYear() - 1;
}

// Ota-ona sinfni botda bir marta kiritadi; joriy sinf har 1-sentabrda oshadi.
// Hisob ikkala tomonda bir xil bo'lishi SHART — aks holda bola bir joyda
// 6-sinf, boshqasida 5-sinf bo'lib ko'rinardi (docs/DECISIONS.md #33).
export function currentGrade(grade: number, gradeYear: number, today: Date = new Date()): number {
  const passed = Math.max(0, academicYearStart(today) - gradeYear);
  return Math.min(MAX_GRADE, grade + passed);
}

function isoDate(value: Date): string {
  // pg `date` ustunini mahalliy vaqtdagi Date qilib beradi — sanani
  // siljitmaslik uchun kun/oy/yilni o'zidan yig'amiz.
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}

// Botdagi "👨‍👩‍👧 Farzandlarim" ro'yxati va ularning olimpiadalari — Mini App
// ochilganda shu ko'rinadi (docs/DECISIONS.md #33). FAQAT O'QISH: farzand
// botda qo'shiladi va tahrirlanadi, platforma bu jadvallarga yozmaydi.
// null — smartbot bazasi umuman sozlanmagan.
export async function smartbotChildren(
  telegramId: string,
  env: Env = process.env,
): Promise<SmartbotChild[] | null> {
  const url = smartbotDatabaseUrl(env);
  if (!url || !/^\d+$/.test(telegramId)) return null;
  const db = pool(url);

  const { rows } = await db.query<{
    id: number;
    first_name: string;
    last_name: string;
    birth_date: Date;
    school: string | null;
    grade: number;
    grade_year: number;
  }>(
    `SELECT id, first_name, last_name, birth_date, school, grade, grade_year
       FROM children
      WHERE user_id = $1::bigint AND archived_at IS NULL
      ORDER BY created_at, id`,
    [telegramId],
  );
  if (rows.length === 0) return [];

  const results = await db.query<{
    child_id: number;
    name: string;
    exam_date: Date | null;
    grade: number | null;
    score: string | number | null;
    place: number | null;
  }>(
    `SELECT r.child_id, o.name, o.exam_date, r.grade, r.score, r.place
       FROM olympiad_results r
       JOIN olympiads o ON o.id = r.olympiad_id
      WHERE r.child_id = ANY($1::int[])
      ORDER BY o.exam_date DESC NULLS LAST, o.id DESC`,
    [rows.map((r) => r.id)],
  );

  const byChild = new Map<number, SmartbotChildOlympiad[]>();
  for (const r of results.rows) {
    const list = byChild.get(r.child_id) ?? [];
    list.push({
      name: r.name,
      examDate: r.exam_date ? isoDate(r.exam_date) : null,
      grade: r.grade,
      score: r.score == null ? null : Number(r.score),
      place: r.place,
    });
    byChild.set(r.child_id, list);
  }

  return rows.map((r) => ({
    id: r.id,
    firstName: r.first_name,
    lastName: r.last_name,
    birthDate: isoDate(r.birth_date),
    school: r.school,
    grade: currentGrade(r.grade, r.grade_year),
    olympiads: byChild.get(r.id) ?? [],
  }));
}

// Scripts call this so an idle pool doesn't keep the process alive.
export async function closeSmartbotPools() {
  await Promise.all([...pools.values()].map((p) => p.end()));
  pools.clear();
}
