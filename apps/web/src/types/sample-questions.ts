export type CategoryName =
  | "Descriptive"
  | "Comparative"
  | "Temporal"
  | "Segmentation"
  | "Correlation";

export type SampleQuestionsStatus = "ok" | "fallback" | "pending" | "failed";

export interface SampleQuestionCategory {
  name: CategoryName;
  questions: string[]; // length 3
}

export interface SampleQuestions {
  status: SampleQuestionsStatus;
  generated_at: string | null;
  model: string | null;
  categories: SampleQuestionCategory[]; // length 3
  few_shot_db_ids: string[];
  error: string | null;
}
