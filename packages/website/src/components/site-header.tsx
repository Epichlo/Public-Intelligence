"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Logo } from "@/components/logo";
import { siteNavigation } from "@/components/site-navigation";

export function SiteHeader() {
  const pathname = usePathname();

  return (
    <header className="border-b border-border/40">
      <div className="mx-auto flex min-h-16 w-full max-w-6xl flex-col gap-4 px-6 py-4 sm:px-8 lg:flex-row lg:items-center lg:justify-between">
        <Link href="/" className="inline-flex items-center text-sm font-medium text-foreground">
          <Logo className="w-5 h-5 text-foreground" showText={true} />
        </Link>
        <nav
          aria-label="Primary navigation"
          className="flex flex-wrap gap-x-6 gap-y-2 text-sm text-muted-foreground"
        >
          {siteNavigation.map((item) => {
            const isActive = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`transition-colors duration-150 ${
                  isActive ? "text-[#D9F99D]" : "hover:text-[#D9F99D]"
                }`}
                target={item.external ? "_blank" : undefined}
                rel={item.external ? "noreferrer" : undefined}
                aria-current={isActive ? "page" : undefined}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
