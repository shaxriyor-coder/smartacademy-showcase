"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import Logo from "./Logo";
import { ROLE_LABELS, hasTeacherAccess, isManager, type StaffRole } from "@/lib/roles";

// Who sees what: classrooms are teachers' own; admins get the centre-wide
// analytics instead (docs/DECISIONS.md #20). An admin with `canTeach` sees
// both sides (#30).
type Viewer = { role: StaffRole; canTeach: boolean };

const LINKS: { href: string; label: string; visible: (user: Viewer) => boolean }[] = [
  { href: "/", label: "Bosh sahifa", visible: () => true },
  { href: "/analytics", label: "Tahlil", visible: (u) => isManager(u.role) },
  { href: "/questions", label: "Savollar", visible: () => true },
  { href: "/tests", label: "Testlar", visible: () => true },
  { href: "/classrooms", label: "Guruhlarim", visible: hasTeacherAccess },
  { href: "/categories", label: "Kategoriyalar", visible: (u) => u.role === "SUPER_ADMIN" },
  { href: "/admins", label: "Xodimlar", visible: (u) => u.role === "SUPER_ADMIN" },
];

export default function HeaderClient({
  userName,
  role,
  canTeach = false,
  signOutAction,
}: {
  userName: string;
  role: StaffRole;
  canTeach?: boolean;
  signOutAction: () => void;
}) {
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);
  const links = LINKS.filter((l) => l.visible({ role, canTeach }));

  return (
    <header className="glass-bar sticky top-0 z-40 border-b">
      <div className="mx-auto flex max-w-6xl items-center gap-5 px-4 py-3 sm:px-6 lg:px-8">
        <Link href="/" className="shrink-0">
          <Logo subtitle="Boshqaruv paneli" />
        </Link>

        <nav className="ml-2 hidden gap-1 md:flex">
          {links.map((l) => {
            const active = l.href === "/" ? pathname === "/" : pathname.startsWith(l.href);
            return (
              <Link
                key={l.href}
                href={l.href}
                className={`rounded-full px-3.5 py-2 text-sm font-semibold transition ${
                  active
                    ? "border border-white/10 bg-white/[0.09] text-ivory"
                    : "text-muted hover:bg-white/[0.06] hover:text-ivory"
                }`}
              >
                {l.label}
              </Link>
            );
          })}
        </nav>

        <div className="ml-auto flex items-center gap-3">
          <Link href="/tests/new" className="btn-gold hidden sm:inline-flex">
            <PlusIcon /> Test tayyorlash
          </Link>
          <div className="hidden items-center gap-2 text-sm text-muted lg:flex">
            <div className="h-8 w-8 rounded-full bg-gradient-to-br from-glow to-indigo" />
            <div>
              <div className="leading-tight text-ivory">{userName}</div>
              <div className="text-xs leading-tight">
                {ROLE_LABELS[role]}
              </div>
            </div>
          </div>
          <form action={signOutAction} className="hidden md:block">
            <button type="submit" className="btn-ghost !px-3 !py-2 text-xs">
              Chiqish
            </button>
          </form>
          <button
            type="button"
            onClick={() => setMenuOpen((v) => !v)}
            aria-label="Menyu"
            className="flex h-10 w-10 items-center justify-center rounded-lg border border-white/15 bg-white/[0.06] text-ivory md:hidden"
          >
            <MenuIcon />
          </button>
        </div>
      </div>

      {menuOpen && (
        <div className="glass-bar border-t px-4 py-3 md:hidden">
          <nav className="flex flex-col gap-1">
            {links.map((l) => (
              <Link
                key={l.href}
                href={l.href}
                onClick={() => setMenuOpen(false)}
                className="rounded-lg px-3 py-2.5 text-sm font-semibold text-ivory hover:bg-white/[0.08]"
              >
                {l.label}
              </Link>
            ))}
            <Link
              href="/tests/new"
              onClick={() => setMenuOpen(false)}
              className="btn-gold mt-2"
            >
              <PlusIcon /> Test tayyorlash
            </Link>
            <form action={signOutAction} className="mt-1">
              <button type="submit" className="btn-ghost w-full">
                Chiqish ({userName})
              </button>
            </form>
          </nav>
        </div>
      )}
    </header>
  );
}

function PlusIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4">
      <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

function MenuIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5">
      <path
        d="M4 6h16M4 12h16M4 18h16"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}
