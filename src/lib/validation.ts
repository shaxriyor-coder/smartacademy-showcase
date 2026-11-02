import { z } from "zod";
import { STAFF_ROLES } from "./roles";

export const subjectCreateSchema = z.object({
  name: z.string().min(1, "Fan nomi majburiy"),
});

export const themeCreateSchema = z.object({
  subjectId: z.string().min(1),
  name: z.string().min(1, "Mavzu nomi majburiy"),
});

export const subThemeCreateSchema = z.object({
  themeId: z.string().min(1),
  name: z.string().min(1, "Ichki mavzu nomi majburiy"),
});

export const difficultyLevelCreateSchema = z.object({
  subjectId: z.string().min(1),
  name: z.string().min(1, "Daraja nomi majburiy"),
  order: z.number().int().min(0).default(0),
});

export const skillCreateSchema = z.object({
  name: z.string().min(1, "Mahorat nomi majburiy"),
});

// `canTeach` — admin/super admin o'qituvchi ishini ham qiladi (roles.ts #30).
export const teacherAccessSchema = z.object({ canTeach: z.boolean() });

export const questionCreateSchema = z.object({
  subjectId: z.string().min(1, "Fan tanlanishi shart"),
  text: z.string().min(1, "Savol matni majburiy"),
  // stored as a relative path (e.g. "/uploads/xxx.png"), not an absolute URL
  imageUrl: z.string().min(1).optional().nullable(),
  correctAnswer: z.string().min(1, "To'g'ri javob majburiy"),
  // 3 yoki 4 ta — savol 4 yoki 5 variantli bo'ladi (src/lib/answer-key.ts).
  wrongAnswers: z
    .array(z.string().min(1, "Barcha noto'g'ri javoblar to'ldirilishi shart"))
    .min(3, "Kamida 3 ta noto'g'ri javob kiritilishi shart")
    .max(4, "Ko'pi bilan 4 ta noto'g'ri javob kiritiladi"),
  themeIds: z.array(z.string()).min(1, "Kamida bitta mavzu tanlanishi kerak"),
  subThemeIds: z.array(z.string()).optional().default([]),
  difficultyId: z.string().min(1, "Qiyinlik darajasi tanlanishi shart"),
  focus: z.enum(["ABITURIENT", "PMT"]),
  skillIds: z.array(z.string()).optional().default([]),
});

export const questionUpdateSchema = questionCreateSchema.partial();

export const testCreateSchema = z
  .object({
    title: z.string().min(1, "Test nomi majburiy"),
    subjectId: z.string().min(1),
    questionIds: z.array(z.string()).min(1, "Kamida bitta savol tanlanishi kerak"),
    isOlympiad: z.boolean().default(false),
    olympiadName: z.string().optional().nullable(),
    // Olimpiada botda yaratiladi va shu yerda faqat tanlanadi — nomi ham
    // botdan olinadi (docs/DECISIONS.md #31).
    smartbotOlympiadId: z.number().int().positive().optional().nullable(),
  })
  .refine((data) => !data.isOlympiad || !!data.smartbotOlympiadId, {
    message: "Olimpiadani ro'yxatdan tanlang",
    path: ["smartbotOlympiadId"],
  });

export const adminCreateSchema = z.object({
  name: z.string().min(1, "Ism majburiy"),
  email: z.string().email("Email noto'g'ri"),
  password: z.string().min(6, "Parol kamida 6 belgidan iborat bo'lishi kerak"),
  role: z.enum(STAFF_ROLES),
  telegramChatId: z
    .string()
    .regex(/^\d+$/, "Telegram ID faqat raqamlardan iborat bo'lishi kerak")
    .optional()
    .nullable(),
});

export const adminUpdateSchema = z.object({
  name: z.string().min(1).optional(),
  email: z.string().email().optional(),
  password: z.string().min(6).optional(),
  role: z.enum(STAFF_ROLES).optional(),
  // Admin/SuperAdmin o'qituvchi ishini ham qiladi (roles.ts, DECISIONS.md #30).
  canTeach: z.boolean().optional(),
  telegramChatId: z
    .string()
    .regex(/^\d+$/, "Telegram ID faqat raqamlardan iborat bo'lishi kerak")
    .optional()
    .nullable(),
});

// --- Classroom (1-bosqich, yangi) ---------------------------------------

export const classroomCreateSchema = z.object({
  name: z.string().min(1, "Guruh nomi majburiy"),
  subjectId: z.string().min(1).optional().nullable(),
});

export const classroomUpdateSchema = z.object({
  name: z.string().min(1).optional(),
  subjectId: z.string().min(1).optional().nullable(),
  archived: z.boolean().optional(),
});

const studentFields = {
  firstName: z.string().trim().min(1, "Ism majburiy").max(100),
  lastName: z.string().trim().max(100).optional().nullable(),
  // "YYYY-MM-DD", as <input type="date"> sends it
  birthDate: z
    .string()
    .regex(/^\d{4}-\d{2}-\d{2}$/, "Tug'ilgan sana noto'g'ri")
    .optional()
    .nullable(),
  grade: z.string().trim().max(20).optional().nullable(),
};

export const studentCreateSchema = z.object(studentFields);
export const studentUpdateSchema = z.object(studentFields).partial();

export const MAX_BULK_STUDENTS = 200;

// A teacher adds students to a classroom one of three ways: type one in, paste
// the class register, or add a student who already exists (another
// classroom) by their link code — so a child's progress stays on ONE record.
export const classroomMemberAddSchema = z.discriminatedUnion("mode", [
  z.object({ mode: z.literal("new"), student: studentCreateSchema }),
  z.object({
    mode: z.literal("bulk"),
    // One student per line, "Familiya Ism" — the order a class register uses.
    lines: z.string().min(1, "Ro'yxat bo'sh"),
    grade: z.string().trim().max(20).optional().nullable(),
  }),
  z.object({ mode: z.literal("code"), linkCode: z.string().min(1, "Kod majburiy") }),
]);

export const linkCodeSchema = z.object({
  linkCode: z.string().min(1, "Kod majburiy"),
});

const isoInstant = z.iso.datetime({ offset: true });
const revealPolicy = z.enum(["IMMEDIATELY", "AFTER_CLOSE", "NEVER"]);

const onlineSettingsFields = {
  opensAt: isoInstant.nullable().optional(),
  closesAt: isoInstant.nullable().optional(),
  timeLimitMinutes: z.number().int().min(1).max(600).nullable().optional(),
  revealAnswers: revealPolicy.optional(),
};

export const assignmentCreateSchema = z
  .object({
    testId: z.string().min(1, "Test tanlanishi shart"),
    title: z.string().trim().max(150).optional(),
    mode: z.enum(["OFFLINE", "ONLINE"]).default("OFFLINE"),
    shuffle: z.boolean().optional(),
    ...onlineSettingsFields,
  })
  .refine((d) => d.mode !== "ONLINE" || d.revealAnswers !== "AFTER_CLOSE" || !!d.closesAt, {
    message: "«Test yopilgandan keyin» uchun yopilish vaqtini kiriting",
    path: ["closesAt"],
  })
  .refine((d) => !d.opensAt || !d.closesAt || new Date(d.opensAt) < new Date(d.closesAt), {
    message: "Yopilish vaqti ochilish vaqtidan keyin bo'lishi kerak",
    path: ["closesAt"],
  });

// Partial update of an ONLINE assignment; the cross-field rules are checked
// against the merged values in the route.
export const assignmentSettingsSchema = z.object(onlineSettingsFields);

const choice = z.enum(["", "A", "B", "C", "D", "E"]);

export const attemptAnswerSchema = z.object({
  index: z.number().int().min(0),
  choice,
});

export const attemptSubmitSchema = z.object({
  answers: z.record(z.string().regex(/^\d+$/), choice).optional(),
});
