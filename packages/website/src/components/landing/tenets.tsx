import { Reveal } from "./reveal";

const TENETS = [
  {
    numeral: "I",
    metaphor: "The vault, not the visit.",
    title: "Sovereignty is the point",
    body: "When your data is the input to intelligence, where that intelligence runs is the whole thing. The models you depend on run entirely on machines inside your own trust boundary. A prompt never has to leave for someone else's servers, terms, or goodwill. Not private mode bolted onto a cloud — private by construction.",
  },
  {
    numeral: "II",
    metaphor: "A tool you own, not a tenancy.",
    title: "Infrastructure, not a service",
    body: "There is no Public Intelligence network to join, no company holding your keys, no marketplace that can reprice or shut down. You run the coordinator and the nodes. It is software you own under Apache-2.0 — if we vanished tomorrow, your setup keeps working.",
  },
  {
    numeral: "III",
    metaphor: "A room of colleagues, not a public square.",
    title: "Small and trusted beats big and open",
    body: "This is not a public grid of strangers renting out GPUs. It is for you and the people you already trust — a lab, a team, a handful of friends — admitted by invite. When the thing crossing the wire is your data, a small circle you chose is worth more than a large one you didn't.",
  },
  {
    numeral: "IV",
    metaphor: "The stamp, not the sales pitch.",
    title: "Honesty is a build requirement",
    body: "The project is built by a process that refuses to report intentions as achievements. One gate defines what passes; the author of a change cannot certify it; every load-bearing assumption is written down with what would prove it wrong. When the system can't do something, it returns an honest error — never invented output.",
  },
];

export function Tenets() {
  return (
    <section id="tenets" className="border-b hairline bg-iron text-lead">
      <div className="mx-auto max-w-6xl px-6 py-24">
        <Reveal className="flex flex-col gap-4 border-b hairline pb-8 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="font-terminal text-[0.7rem] uppercase tracking-[0.3em] text-amber">
              01 &nbsp;/&nbsp; The Tenets
            </p>
            <h2 className="mt-4 max-w-xl font-editorial text-4xl font-medium leading-tight sm:text-5xl">
              Four commitments, stated as plainly as they are enforced.
            </h2>
          </div>
          <p className="max-w-xs font-terminal text-xs leading-relaxed text-concrete">
            A manifesto is only worth the machinery behind it. Each of these maps to a
            decision on record in the repository.
          </p>
        </Reveal>

        <div className="grid grid-cols-1 md:grid-cols-2">
          {TENETS.map((tenet, index) => (
            <Reveal
              key={tenet.numeral}
              delay={(index % 2) * 90}
              className={`flex flex-col gap-5 border-b hairline p-8 md:p-10 ${
                index % 2 === 0 ? "md:border-r" : ""
              }`}
            >
              <div className="flex items-baseline justify-between">
                <span className="font-editorial text-6xl font-semibold leading-none text-lead/25">
                  {tenet.numeral}
                </span>
                <span className="font-terminal text-[0.62rem] uppercase tracking-[0.2em] text-amber">
                  Tenet {tenet.numeral}
                </span>
              </div>
              <p className="font-editorial text-2xl font-medium italic leading-snug text-lead">
                &ldquo;{tenet.metaphor}&rdquo;
              </p>
              <h3 className="font-terminal text-xs uppercase tracking-[0.22em] text-concrete">
                {tenet.title}
              </h3>
              <p className="text-sm leading-relaxed text-concrete">{tenet.body}</p>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
