"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_LINKS = [
  { href: "/projects", label: "Projects" },
  { href: "/channels", label: "Channels" },
];

export function TopNav() {
  const pathname = usePathname() ?? "";
  return (
    <header className="sticky top-0 z-40 border-b border-border bg-background/80 backdrop-blur">
      <nav className="mx-auto flex h-14 max-w-7xl items-center px-6">
        <Link
          href="/"
          className="flex items-center gap-2 text-foreground hover:text-accent transition-colors"
        >
          <span className="flex h-8 w-8 items-center justify-center rounded-md bg-accent text-sm font-bold text-white">
            aq
          </span>
          <span className="text-sm font-semibold tracking-tight">Aqua</span>
        </Link>

        <div className="ml-10 flex items-center gap-1">
          {NAV_LINKS.map((link) => {
            const active =
              pathname === link.href ||
              pathname.startsWith(link.href + "/");
            return (
              <Link
                key={link.href}
                href={link.href}
                className={
                  active
                    ? "rounded-md bg-surface-2 px-3 py-1.5 text-sm text-foreground"
                    : "rounded-md px-3 py-1.5 text-sm text-muted-strong hover:bg-surface-2 hover:text-foreground transition-colors"
                }
              >
                {link.label}
              </Link>
            );
          })}
          <span
            title="Coming soon"
            className="rounded-md px-3 py-1.5 text-sm text-muted/60 cursor-not-allowed"
          >
            Tools
          </span>
        </div>
      </nav>
    </header>
  );
}
