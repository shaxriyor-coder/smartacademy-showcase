import { AuthError } from "next-auth";
import { redirect } from "next/navigation";
import { cookies } from "next/headers";
import { signIn } from "@/auth";
import Logo from "@/components/Logo";

async function verifyAction(formData: FormData) {
  "use server";
  const cookieStore = await cookies();
  const pendingId = cookieStore.get("pending_login")?.value;
  if (!pendingId) redirect("/login");

  const code = formData.get("code") as string;

  try {
    await signIn("credentials", { otpPendingId: pendingId, otpCode: code, redirectTo: "/" });
  } catch (error) {
    if (error instanceof AuthError) {
      redirect("/login/verify?error=1");
    }
    throw error;
  }
}

export default async function VerifyOtpPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const { error } = await searchParams;
  const cookieStore = await cookies();
  if (!cookieStore.get("pending_login")?.value) redirect("/login");

  return (
    <div className="flex min-h-[80vh] items-center justify-center">
      <form
        action={verifyAction}
        className="glass-panel w-full max-w-sm p-7 shadow-2xl shadow-black/30"
      >
        <div className="mb-7 flex justify-center">
          <Logo subtitle="Boshqaruv paneli" />
        </div>

        <p className="mb-5 text-center text-sm text-muted">
          Telegramga yuborilgan 6 xonali kodni kiriting
        </p>

        {error === "1" && (
          <p className="mb-4 rounded-lg border border-red-400/30 bg-red-400/10 px-3 py-2 text-sm text-red-300">
            Kod noto&apos;g&apos;ri yoki muddati o&apos;tgan
          </p>
        )}

        <label className="mb-6 block">
          <span className="label-field">Tasdiqlash kodi</span>
          <input
            type="text"
            name="code"
            inputMode="numeric"
            pattern="\d{6}"
            maxLength={6}
            required
            autoFocus
            className="input-field text-center text-lg tracking-[0.4em]"
          />
        </label>

        <button type="submit" className="btn-gold w-full">
          Tasdiqlash
        </button>

        <a
          href="/login"
          className="mt-4 block text-center text-xs text-muted hover:text-ivory hover:underline"
        >
          ← Ortga qaytish
        </a>
      </form>
    </div>
  );
}
