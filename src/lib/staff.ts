// What the staff page shows about a person. The counts tell the super admin
// what someone still owns before their role changes or they're removed.
export const STAFF_SELECT = {
  id: true,
  name: true,
  email: true,
  role: true,
  canTeach: true,
  telegramChatId: true,
  createdAt: true,
  _count: {
    select: {
      classrooms: { where: { archived: false } },
      tests: true,
      questions: true,
    },
  },
} as const;
