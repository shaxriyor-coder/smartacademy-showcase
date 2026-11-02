"use client";

import { useState } from "react";
import QuestionForm from "./QuestionForm";
import WordImportWizard from "./WordImportWizard";

type SubTheme = { id: string; name: string };
type Theme = { id: string; name: string; subThemes: SubTheme[] };
type DifficultyLevel = { id: string; name: string; order: number };
type Subject = {
  id: string;
  name: string;
  themes: Theme[];
  difficultyLevels: DifficultyLevel[];
};
type Skill = { id: string; name: string };

export default function NewQuestionModeSwitch({
  subjects,
  skills,
}: {
  subjects: Subject[];
  skills: Skill[];
}) {
  const [mode, setMode] = useState<"manual" | "word">("manual");

  return (
    <div>
      <div className="mb-6 flex gap-2">
        <button
          type="button"
          onClick={() => setMode("manual")}
          className={`pill ${mode === "manual" ? "is-active" : ""}`}
        >
          Qo&apos;lda kiritish
        </button>
        <button
          type="button"
          onClick={() => setMode("word")}
          className={`pill ${mode === "word" ? "is-active" : ""}`}
        >
          Word yoki rasmdan
        </button>
      </div>

      {mode === "manual" ? (
        <QuestionForm subjects={subjects} skills={skills} />
      ) : (
        <WordImportWizard subjects={subjects} skills={skills} />
      )}
    </div>
  );
}
