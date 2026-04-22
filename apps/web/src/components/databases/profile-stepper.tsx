"use client";

import { ProfileStepRow } from "./profile-step-row";
import type { ProfileStep } from "@/hooks/useProfileRun";

export function ProfileStepper({ steps }: { steps: ProfileStep[] }) {
  return (
    <ol className="divide-y divide-border rounded-md border border-border">
      {steps.map((step) => (
        <div key={step.stage} className="px-3">
          <ProfileStepRow step={step} />
        </div>
      ))}
    </ol>
  );
}
