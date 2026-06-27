import Link from "next/link";

export function NewProjectButton() {
  return (
    <Link
      href="/projects/new"
      className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-accent-hover"
    >
      New project
    </Link>
  );
}
