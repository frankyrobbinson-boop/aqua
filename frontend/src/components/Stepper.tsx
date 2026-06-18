export type Step = 1 | 2 | 3 | 4;

export const STEPS = ["Script", "Voiceover", "Visuals", "Render"] as const;

type StepperProps = {
  current: Step;
  /** Which steps are completed (show check, green). */
  completed?: Set<Step>;
  /** If set, the stepper becomes clickable. */
  onSelect?: (step: Step) => void;
  /** Steps that should be disabled (greyed, not clickable). */
  disabled?: Set<Step>;
};

export function Stepper({
  current,
  completed,
  onSelect,
  disabled,
}: StepperProps) {
  return (
    <div className="mb-8 flex items-center justify-center gap-2">
      {STEPS.map((label, i) => {
        const num = (i + 1) as Step;
        // Only mark a step as done if the caller explicitly says so — never
        // infer "all earlier steps are done" from current position.
        const isDone = completed?.has(num) ?? false;
        const isActive = num === current;
        const isDisabled = disabled?.has(num) ?? false;
        const isClickable = !!onSelect && !isDisabled;

        // Active wins over completed visually — bright outline, no fill,
        // numeric label so the user knows which tab they're on.
        const circle = (
          <div
            className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold transition-colors ${
              isActive
                ? "border border-foreground text-foreground"
                : isDone
                  ? "bg-accent text-white"
                  : isDisabled
                    ? "bg-surface-2 text-muted opacity-50"
                    : "bg-surface-2 text-muted"
            }`}
          >
            {isActive ? num : isDone ? "✓" : num}
          </div>
        );

        // Label is bright only for the active tab. The inline-grid stack with
        // an invisible bold ghost reserves the bold-weight width on every tab,
        // so widths don't shift when the active tab changes. Inline styles are
        // used here because Turbopack has been flaking on Tailwind utility
        // class rebuilds in this project.
        const labelColor = isActive
          ? "var(--foreground)"
          : "var(--muted)";
        const labelEl = (
          <span style={{ display: "inline-grid", fontSize: "0.75rem", lineHeight: "1rem" }}>
            <span
              style={{
                gridColumn: 1,
                gridRow: 1,
                fontWeight: isActive ? 500 : 400,
                color: labelColor,
                opacity: isDisabled ? 0.5 : 1,
              }}
            >
              {label}
            </span>
            <span
              aria-hidden="true"
              style={{
                gridColumn: 1,
                gridRow: 1,
                fontWeight: 500,
                visibility: "hidden",
                pointerEvents: "none",
              }}
            >
              {label}
            </span>
          </span>
        );

        const inner = (
          <>
            {circle}
            {labelEl}
          </>
        );

        return (
          <div key={label} className="flex items-center gap-2">
            {isClickable ? (
              <button
                type="button"
                onClick={() => onSelect(num)}
                className="flex items-center gap-2 rounded-md px-1 py-0.5 outline-none hover:opacity-80 focus-visible:ring-2 focus-visible:ring-accent"
              >
                {inner}
              </button>
            ) : (
              <div className="flex items-center gap-2 px-1 py-0.5">{inner}</div>
            )}
            {i < STEPS.length - 1 && <div className="h-px w-8 bg-border" />}
          </div>
        );
      })}
    </div>
  );
}
