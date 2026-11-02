import type { ReactNode } from "react";
import AnalyticsTabs from "@/components/analytics/AnalyticsTabs";

// Centre-wide analytics for admins. Each page checks the role itself
// (managerPageSession): a layout isn't re-run on client navigation.
export default function AnalyticsLayout({ children }: { children: ReactNode }) {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-2xl font-bold">Markaz tahlili</h1>
        <p className="mt-1 max-w-prose text-sm text-muted">
          Barcha guruhlar jamlanmasi. Guruh ichidagi topshiriq va javob tafsilotlari o&apos;qituvchilarda
          qoladi.
        </p>
      </div>
      <AnalyticsTabs />
      {children}
    </div>
  );
}
