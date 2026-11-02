import { notFound, redirect } from "next/navigation";
import { signIn } from "@/auth";
import { signTelegramPayloadForDev } from "@/lib/telegram-auth";
import Logo from "@/components/Logo";

function isNextRedirectError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "digest" in error &&
    typeof (error as { digest: unknown }).digest === "string" &&
    (error as { digest: string }).digest.startsWith("NEXT_REDIRECT")
  );
}

async function devLoginAction(formData: FormData) {
  "use server";
  if (process.env.NODE_ENV === "production") notFound();

  const id = (formData.get("telegramId") as string)?.trim();
  const firstName = (formData.get("firstName") as string)?.trim();
  if (!id || !firstName) redirect("/login/student/dev?error=1");

  // Wraps BOTH the payload signing (fails fast if TELEGRAM_BOT_TOKEN isn't
  // set — a likely first-run state for anyone setting up the project) and
  // the sign-in call itself, so any failure here shows the friendly message
  // below instead of a raw 500. Next's own redirect() throw (on success, or
  // from the redirect() calls in this function) must still propagate.
  try {
    const signed = signTelegramPayloadForDev({ id, first_name: firstName });
    await signIn("telegram-student", { ...signed, redirectTo: "/classroom-home" });
  } catch (error) {
    if (isNextRedirectError(error)) throw error;
    redirect("/login/student/dev?error=1");
  }
}

// Dev-only stand-in for the real Telegram Login Widget (src/app/login/student/page.tsx),
// which needs a public HTTPS domain registered with the bot and so cannot be
// exercised on localhost. Signs a payload with the same HMAC the real widget
// uses (src/lib/telegram-auth.ts) and feeds it through the exact same
// NextAuth provider — nothing about the Student/Classroom code path is
// bypassed, only the widget UI itself.
export default async function StudentDevLoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  if (process.env.NODE_ENV === "production") notFound();
  const { error } = await searchParams;

  return (
    <div className="flex min-h-[80vh] items-center justify-center">
      <form
        action={devLoginAction}
        className="glass-panel w-full max-w-sm p-7 shadow-2xl shadow-black/30"
      >
        <div className="mb-7 flex justify-center">
          <Logo subtitle="Dev login (faqat lokal)" />
        </div>

        <p className="mb-5 rounded-lg border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-xs text-amber-300">
          Bu sahifa faqat ishlab chiqish (development) muhitida ishlaydi — production&apos;da
          404 qaytaradi. Haqiqiy Telegram Login Widget uchun{" "}
          <a href="/login/student" className="underline">
            /login/student
          </a>
          ga qarang.
        </p>

        {error === "1" && (
          <p className="mb-4 rounded-lg border border-red-400/30 bg-red-400/10 px-3 py-2 text-sm text-red-300">
            Kirishda xatolik. Odatda sabab: <code>TELEGRAM_BOT_TOKEN</code> .env&apos;da
            sozlanmagan, yoki `.env`ni o&apos;zgartirgandan keyin server qayta ishga
            tushirilmagan. Terminaldagi xato xabarida aniqrog&apos;i ko&apos;rinadi.
          </p>
        )}

        <label className="mb-4 block">
          <span className="label-field">Telegram ID (raqam)</span>
          <input
            name="telegramId"
            required
            pattern="\d+"
            inputMode="numeric"
            placeholder="123456789"
            className="input-field"
          />
        </label>
        <label className="mb-6 block">
          <span className="label-field">Ism</span>
          <input name="firstName" required placeholder="Ali" className="input-field" />
        </label>

        <button type="submit" className="btn-gold w-full">
          Student sifatida kirish
        </button>
      </form>
    </div>
  );
}
