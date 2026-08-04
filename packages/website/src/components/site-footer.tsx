import Link from "next/link";
import { Logo } from "@/components/logo";
import { siteNavigation } from "@/components/site-navigation";

export function SiteFooter() {
  return (
    <footer className="space-y-8 pt-16 border-t border-border/20 text-xs text-muted-foreground/60">
      <div className="flex flex-wrap items-center justify-between gap-6">
        <div className="inline-flex items-center gap-2">
          <Logo className="w-4 h-4 text-muted-foreground/50" />
          <span>Public Intelligence — Open Infrastructure Initiative</span>
        </div>
        <nav aria-label="Footer navigation" className="flex flex-wrap gap-x-6 gap-y-2">
          {siteNavigation.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="hover:text-[#D9F99D] transition-colors duration-150"
              target={link.external ? "_blank" : undefined}
              rel={link.external ? "noreferrer" : undefined}
            >
              {link.label}
            </Link>
          ))}
        </nav>
      </div>
      <div className="flex items-center justify-between text-[10px] border-t border-border/10 pt-6 font-mono opacity-80">
        <p>© {new Date().getFullYear()} Public Intelligence. Released under the MIT License.</p>
        <p>VER_0.1.0 // FOUNDATIONAL_RELEASE</p>
      </div>
    </footer>
  );
}
