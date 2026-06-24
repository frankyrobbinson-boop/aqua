/**
 * Compact 4-step wizard indicator for the visuals flow.
 *
 * Decoupled from the project-level `Stepper` because the visuals wizard is its
 * own sub-flow with different step labels (Script → Audio → Configure pacing →
 * Render) and the per-step state model is simpler: each step is one of
 * `completed | active | pending`. The project Stepper supports clicks/disabled
 * navigation, this one is read-only.
 */
export type WizardStepStatus = "completed" | "active" | "pending";

export type WizardStep = {
  label: string;
  status: WizardStepStatus;
};

export function StepIndicator({ steps }: { steps: WizardStep[] }) {
  return (
    <div className="flex items-center justify-center gap-2">
      {steps.map((step, i) => {
        const isActive = step.status === "active";
        const isDone = step.status === "completed";
        return (
          <div key={step.label} className="flex items-center gap-2">
            <div
              className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold ${
                isActive
                  ? "border border-foreground text-foreground"
                  : isDone
                    ? "bg-accent text-white"
                    : "bg-surface-2 text-muted"
              }`}
            >
              {isDone ? "✓" : i + 1}
            </div>
            <span
              className={`text-xs ${
                isActive
                  ? "font-medium text-foreground"
                  : isDone
                    ? "text-muted-strong"
                    : "text-muted"
              }`}
            >
              {step.label}
            </span>
            {i < steps.length - 1 && (
              <div className="ml-2 h-px w-8 bg-border" />
            )}
          </div>
        );
      })}
    </div>
  );
}
