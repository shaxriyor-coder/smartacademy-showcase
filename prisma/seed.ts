import "dotenv/config";
import { PrismaPg } from "@prisma/adapter-pg";
import { PrismaClient } from "@prisma/client";
import bcrypt from "bcryptjs";

const adapter = new PrismaPg({ connectionString: process.env.DATABASE_URL });
const prisma = new PrismaClient({ adapter });

async function main() {
  const email = process.env.SEED_SUPERADMIN_EMAIL ?? "admin@example.com";
  const password = process.env.SEED_SUPERADMIN_PASSWORD;
  const name = process.env.SEED_SUPERADMIN_NAME ?? "Super Admin";

  if (!password) {
    throw new Error("SEED_SUPERADMIN_PASSWORD .env da sozlanishi kerak");
  }

  const existing = await prisma.user.findUnique({ where: { email } });
  if (existing) {
    console.log(`SuperAdmin allaqachon mavjud: ${email}`);
    return;
  }

  const passwordHash = await bcrypt.hash(password, 10);
  await prisma.user.create({
    data: { name, email, passwordHash, role: "SUPER_ADMIN" },
  });

  console.log(`SuperAdmin yaratildi: ${email}`);
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
