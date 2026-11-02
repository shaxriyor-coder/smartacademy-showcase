"use client";

import Logo from "./Logo";

// Deliberately minimal — a student/parent account has one home
// (/classroom-home) with results reachable from it, so there's no nav yet.
// Grows once online test-taking (a later phase) exists.
export default function StudentHeaderClient({
  userName,
  signOutAction,
}: {
  userName: string;
  signOutAction: () => void;
}) {
  return (
    <header className="glass-bar sticky top-0 z-40 border-b">
      <div className="mx-auto flex max-w-6xl items-center gap-5 px-4 py-3 sm:px-6 lg:px-8">
        <Logo subtitle="O'quvchi" />
        <div className="ml-auto flex items-center gap-3">
          <span className="hidden text-sm text-muted sm:inline">{userName}</span>
          <form action={signOutAction}>
            <button type="submit" className="btn-ghost !px-3 !py-2 text-xs">
              Chiqish
            </button>
          </form>
        </div>
      </div>
    </header>
  );
}
