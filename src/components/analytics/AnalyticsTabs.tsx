"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/analytics", label: "O'quvchilar" },
  { href: "/analytics/teachers", label: "O'qituvchilar" },
  { href: "/analytics/questions", label: "Savollar bazasi" },
];

export default function AnalyticsTabs() {
  const pathname = usePathname();
  return (
    <nav className="flex flex-wrap gap-2" aria-label="Tahlil bo'limlari">
      {TABS.map((t) => {
        const active = pathname === t.href;
        return (
          <Link
            key={t.href}
            href={t.href}
            aria-current={active ? "page" : undefined}
            className={`pill ${active ? "is-active" : ""}`}
          >
            {t.label}
          </Link>
        );
      })}
    </nav>
  );
}
