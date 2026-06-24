/**
 * Shared label + hint + body wrapper for channel form fields.
 *
 * Factored out of ChannelEditPanel in Phase 3c so the create-channel wizard
 * (which reuses VisualsSection and needs the same look for its identity-step
 * fields) doesn't have to duplicate the layout.
 */
export function Row({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <label className="text-sm font-medium text-foreground">{label}</label>
        {hint && <span className="text-xs text-muted">{hint}</span>}
      </div>
      {children}
    </div>
  );
}
