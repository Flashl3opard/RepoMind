import Link from "next/link";

import { ThemeToggle } from "@/components/theme-toggle";

const LINKS = [
  { href: "/", label: "Repos" },
  { href: "/playground", label: "Playground" },
  { href: "/benchmark", label: "Benchmark" },
];

export function NavBar() {
  return (
    <header className="border-b">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
        <nav className="flex items-center gap-4">
          <Link href="/" className="font-semibold">
            RepoMind
          </Link>
          <div className="text-muted-foreground flex items-center gap-3 text-sm">
            {LINKS.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className="hover:text-foreground transition-colors"
              >
                {link.label}
              </Link>
            ))}
          </div>
        </nav>
        <ThemeToggle />
      </div>
    </header>
  );
}
