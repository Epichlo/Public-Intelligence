/**
 * The hosting command shown on the landing page (specs/host-a-node-on-the-website.md).
 *
 * The component that renders it cannot be tested here -- `vitest.config.mts` sets
 * `environment: "node"` on purpose and there is no jsdom -- so the string lives in
 * `lib/` and this file tests the string. That is the same split `lib/sse.ts` and
 * `components/contribution-summary.ts` already use.
 *
 * The load-bearing test is the parity one. A command on a website is a set of
 * instructions a stranger will paste into a root-capable shell; the way it goes wrong
 * is not a crash but a *silent* divergence from the command the project actually
 * documents and supports. So the README is read off disk and compared, and the
 * individual properties are asserted separately -- parity alone would pass happily if
 * both sides were edited to the same wrong thing.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { HOST_NODE_COMMAND } from "./host-command";

/**
 * Resolved from this file, not from `process.cwd()`: the gate runs the website suite
 * from `packages/website` and a developer may run it from the repo root. Anchoring to
 * cwd makes the test pass or fail on where it was invoked from.
 */
const REPO_README = fileURLToPath(new URL("../../../../README.md", import.meta.url));

/** The fenced ```bash block under `## Host a node`, with the fences stripped. */
function readmeHostCommand(): string {
  const readme = readFileSync(REPO_README, "utf8");
  const section = readme.split("\n## Host a node\n")[1];
  if (section === undefined) {
    throw new Error(`no "## Host a node" section in ${REPO_README}`);
  }
  const fenced = section.match(/```bash\n([\s\S]*?)```/);
  if (fenced === null) {
    throw new Error(`no bash block under "## Host a node" in ${REPO_README}`);
  }
  return fenced[1].trimEnd();
}

describe("HOST_NODE_COMMAND", () => {
  it("is byte-identical to the command the README documents", () => {
    // The whole point of this file. The site and the docs are two copies of one
    // instruction; this is the ratchet that stops them drifting.
    expect(HOST_NODE_COMMAND).toBe(readmeHostCommand());
  });

  it("fetches bootstrap.sh from this repository", () => {
    // Asserted independently of the parity check above, which would be satisfied by
    // two identically-wrong strings.
    expect(HOST_NODE_COMMAND).toContain(
      "https://raw.githubusercontent.com/Epichlo/Public-Intelligence/main/scripts/bootstrap.sh",
    );
  });

  it("passes every flag bootstrap.sh forwards to install.sh", () => {
    // bootstrap.sh execs `install.sh --start "$@"`. A block missing one of these
    // reads as complete and produces a node that cannot register (W2, W5).
    for (const flag of ["--scheduler-url", "--fleet-token", "--invite-code"]) {
      expect(HOST_NODE_COMMAND).toContain(flag);
    }
  });

  it("points at a placeholder Scheduler, never a real host", () => {
    // D6: there is no operated network. A copyable command that resolves to somebody
    // else's coordinator would enrol a stranger's machine into a fleet they did not
    // choose, and it would look like it worked.
    expect(HOST_NODE_COMMAND).toContain("--scheduler-url https://your-scheduler");
    expect(HOST_NODE_COMMAND).not.toMatch(
      /--scheduler-url\s+https:\/\/(?!your-scheduler\b)[a-z0-9.-]+\.[a-z]{2,}/i,
    );
  });

  it("keeps the credentials as placeholders", () => {
    // Same reasoning: a real token in a public page is a leaked secret, and a
    // plausible-looking one is worse than an obvious placeholder.
    expect(HOST_NODE_COMMAND).toContain("--fleet-token TOKEN");
    expect(HOST_NODE_COMMAND).toContain("--invite-code CODE");
  });
});
