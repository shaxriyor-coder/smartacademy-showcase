import { auth } from "@/auth";
import { LogoMark } from "./Logo";

export default async function Footer() {
  const session = await auth();
  if (!session?.user) return null;

  return (
    <footer className="glass-bar border-t">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-4 text-xs text-muted sm:px-6 lg:px-8">
        <div className="flex items-center gap-2">
          <LogoMark size="sm" />
          <span>SmartAcademy Platform</span>
        </div>
        <div className="flex gap-5">
          <span>Yordam</span>
          <span>Sozlamalar</span>
        </div>
        <div>© {new Date().getFullYear()} SmartAcademy</div>
      </div>
    </footer>
  );
}
