import MixBar from "./MixBar";
import { STATUS } from "./colors";

// Every answered question: correct → blank → wrong (validated neighbours).
// "Several circles marked" counts as wrong and is named in a note instead of
// taking its own segment — it would need the orange "serious" step, which sits
// too close to warning yellow.
export default function AnswerMix({
  correct,
  wrong,
  blank,
  multi,
}: {
  correct: number;
  wrong: number;
  blank: number;
  multi: number;
  total?: number;
}) {
  return (
    <MixBar
      segments={[
        { key: "correct", label: "To'g'ri", icon: "✓", color: STATUS.good, value: correct },
        { key: "blank", label: "Javobsiz", icon: "○", color: STATUS.warning, value: blank },
        { key: "wrong", label: "Noto'g'ri", icon: "✗", color: STATUS.critical, value: wrong + multi },
      ]}
      note={multi > 0 ? `Noto'g'rilardan ${multi} tasida bir nechta doira bo'yalgan.` : undefined}
    />
  );
}
