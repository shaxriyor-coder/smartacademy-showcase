import { auth, signOut } from "@/auth";
import HeaderClient from "./HeaderClient";
import StudentHeaderClient from "./StudentHeaderClient";

export default async function NavBar() {
  const session = await auth();
  if (!session?.user) return null;

  const isStudent = session.user.kind === "student";

  async function signOutAction() {
    "use server";
    await signOut({ redirectTo: isStudent ? "/login/student" : "/login" });
  }

  if (isStudent) {
    return (
      <StudentHeaderClient
        userName={session.user.name ?? ""}
        signOutAction={signOutAction}
      />
    );
  }

  return (
    <HeaderClient
      userName={session.user.name ?? ""}
      role={session.user.role ?? "TEACHER"}
      canTeach={session.user.canTeach ?? false}
      signOutAction={signOutAction}
    />
  );
}
