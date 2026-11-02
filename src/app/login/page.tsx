import { AuthError } from "next-auth";
import { redirect } from "next/navigation";
import { cookies } from "next/headers";
import { signIn } from "@/auth";
import { verifyPassword } from "@/lib/credentials";
import { createAndSendOtp } from "@/lib/otp";
import { isLocked, recordFailure, recordSuccess } from "@/lib/login-throttle";
import Logo from "@/components/Logo";

async function loginAction(formData: FormData) {
  "use server";
  const email = formData.get("email") as string;
  const password = formData.get("password") as string;

  if (isLocked(email)) redirect("/login?error=locked");

  const user = await verifyPassword(email, password);
  if (!user) {
    recordFailure(email);
    redirect("/login?error=1");
  }
  recordSuccess(email);

  if (user.telegramChatId) {
    let pendingId: string;
    try {
      pendingId = await createAndSendOtp(user.id, user.telegramChatId);
    } catch {
      redirect("/login?error=telegram");
    }
    const cookieStore = await cookies();
    cookieStore.set("pending_login", pendingId, {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      path: "/",
      maxAge: 5 * 60,
    });
    redirect("/login/verify");
  }

  try {
    await signIn("credentials", { email, password, redirectTo: "/" });
  } catch (error) {
    if (error instanceof AuthError) {
      redirect("/login?error=1");
    }
    throw error;
  }
}

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const { error } = await searchParams;

  return (
    <div className="flex min-h-[80vh] items-center justify-center">
      <form action={loginAction} className="glass-panel w-full max-w-sm p-7 shadow-2xl shadow-black/30">
        <div className="mb-7 flex justify-center">
          <Logo subtitle="Boshqaruv paneli" />
        </div>

        {error === "locked" && (
          <p className="mb-4 rounded-lg border border-red-400/30 bg-red-400/10 px-3 py-2 text-sm text-red-300">
            Juda ko&apos;p noto&apos;g&apos;ri urinish. 15 daqiqadan keyin qayta urinib
            ko&apos;ring.
          </p>
        )}
        {error === "telegram" && (
          <p className="mb-4 rounded-lg border border-red-400/30 bg-red-400/10 px-3 py-2 text-sm text-red-300">
            Telegram kodi yuborilmadi. Administratorga murojaat qiling.
          </p>
        )}
        {error === "1" && (
          <p className="mb-4 rounded-lg border border-red-400/30 bg-red-400/10 px-3 py-2 text-sm text-red-300">
            Email yoki parol noto&apos;g&apos;ri
          </p>
        )}

        <label className="mb-4 block">
          <span className="label-field">Email</span>
          <input type="email" name="email" required className="input-field" />
        </label>

        <label className="mb-6 block">
          <span className="label-field">Parol</span>
          <input type="password" name="password" required className="input-field" />
        </label>

        <button type="submit" className="btn-gold w-full">
          Kirish
        </button>

        <a
          href="/login/student"
          className="mt-4 block text-center text-xs text-muted hover:text-ivory hover:underline"
        >
          Telegram orqali kirish (xodim, o&apos;quvchi, ota-ona) →
        </a>
      </form>
    </div>
  );
}
