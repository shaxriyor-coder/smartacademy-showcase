"use client";

import { useRouter } from "next/navigation";
import { apiErrorMessage } from "@/lib/fetch-error";
import { useDialog } from "@/components/DialogProvider";

export default function ArchiveAssignmentButton({
  assignmentId,
  classroomId,
}: {
  assignmentId: string;
  classroomId: string;
}) {
  const router = useRouter();
  const dialog = useDialog();

  async function archive() {
    if (!(await dialog.confirm("Topshiriq arxivlansinmi? Ro'yxatlardan yo'qoladi, natijalar bazada qoladi."))) return;
    const res = await fetch(`/api/assignments/${assignmentId}`, { method: "DELETE" });
    if (!res.ok) {
      await dialog.alert(apiErrorMessage(await res.json().catch(() => null)));
      return;
    }
    router.push(`/classrooms/${classroomId}`);
  }

  return (
    <button type="button" onClick={archive} className="btn-danger-ghost">
      Topshiriqni arxivlash
    </button>
  );
}
