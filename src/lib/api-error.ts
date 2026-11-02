import { NextResponse } from "next/server";
import { Prisma } from "@prisma/client";
import { HttpError } from "./http-error";

// Every API route calls this from a catch block instead of letting Prisma/IO
// exceptions propagate uncaught — an unhandled unique-constraint violation
// (duplicate subject/theme/admin-email name, etc.) would otherwise surface
// as a bare 500 with no JSON body, breaking every frontend's `res.json()`
// call with a confusing parse error instead of showing a real message.
export function handleApiError(err: unknown): NextResponse {
  if (err instanceof HttpError) {
    if (err.status >= 500) console.error(err);
    return NextResponse.json({ error: err.message }, { status: err.status });
  }

  if (err instanceof Prisma.PrismaClientKnownRequestError && err.code === "P2002") {
    const target = err.meta?.target;
    const field = Array.isArray(target) ? target.join(", ") : "qiymat";
    return NextResponse.json(
      { error: `Bu ${field} band — boshqa qiymat kiriting` },
      { status: 409 },
    );
  }

  console.error(err);
  return NextResponse.json({ error: "Kutilmagan xatolik yuz berdi" }, { status: 500 });
}
