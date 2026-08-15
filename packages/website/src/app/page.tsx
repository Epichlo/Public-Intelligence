import Link from "next/link";
import { Hero } from "@/components/landing/hero";
import { Tenets } from "@/components/landing/tenets";
import { UnredactedTruth } from "@/components/landing/unredacted-truth";
import { EndpointConsole } from "@/components/landing/endpoint-console";

const COLOPHON_LINKS = [
  { label: "Architecture", href: "/architecture" },
  { label: "System status", href: "/status" },
  { label: "Source", href: "https://github.com/Epichlo/Public-Intelligence" },
];

export default function Home() {
  return (
    <main className="bg-iron font-sans">
      <Hero />
      <Tenets />
      <UnredactedTruth />
      <EndpointConsole />

      {/* Colophon */}
      <section className="border-t hairline bg-iron text-lead">
        <div className="mx-auto grid max-w-6xl gap-10 px-6 py-20 md:grid-cols-[1.2fr_0.8fr]">
          <div>
            <p className="font-editorial text-3xl font-medium italic leading-snug sm:text-4xl">
              Not a marketplace. Not a network to join. You run both halves.
            </p>
            <p className="mt-6 max-w-lg text-sm leading-relaxed text-concrete">
              An independent human review — the one check a project cannot run on itself
              — is still open. A first pass of external research is on the record in the
              repository, and it is not pretended to be the last word.
            </p>
          </div>
          <div className="flex flex-col justify-between gap-8">
            <ul className="flex flex-col gap-px">
              {COLOPHON_LINKS.map((link) => {
                const external = link.href.startsWith("http");
                return (
                  <li key={link.label}>
                    <Link
                      href={link.href}
                      target={external ? "_blank" : undefined}
                      rel={external ? "noreferrer" : undefined}
                      className="group flex items-center justify-between border-b hairline py-3 font-terminal text-xs uppercase tracking-[0.18em] text-concrete transition-colors hover:text-lead"
                    >
                      {link.label}
                      <span aria-hidden className="transition-transform group-hover:translate-x-1">
                        &rarr;
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
            <p className="font-terminal text-[0.62rem] uppercase tracking-[0.2em] text-concrete">
              Public Intelligence &middot; v1.0.0 &middot; Apache-2.0
            </p>
          </div>
        </div>
      </section>
    </main>
  );
}
