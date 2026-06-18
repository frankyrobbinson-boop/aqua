type StatusBadgeProps = {
  label: string;
  active: boolean;
};

export function StatusBadge({ label, active }: StatusBadgeProps) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium ${
        active
          ? "border-success/30 bg-success/10 text-success"
          : "border-border bg-surface-2 text-muted"
      }`}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${
          active ? "bg-success" : "bg-muted"
        }`}
      />
      {label}
    </span>
  );
}
