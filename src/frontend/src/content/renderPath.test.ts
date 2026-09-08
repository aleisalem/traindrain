import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const FRONTEND_ROOT = process.cwd();

/**
 * The learner render path's guarantee is "no HTML string is ever injected".
 * That is worth only as much as its enforcement, so it is enforced twice:
 * by a lint rule that fails the build, and by this test, which checks both
 * that no such call exists today and that the lint rule would actually catch
 * one if someone added it.
 */
describe("the ban on dangerouslySetInnerHTML", () => {
  it("holds across the whole frontend source tree", () => {
    // `git grep` exits 1 when nothing matches, which is the passing case, so
    // the exit status is read rather than allowed to throw. This file is
    // excluded because it necessarily names the thing it bans.
    const result = run("git", [
      "grep",
      "-l",
      "--",
      "dangerouslySetInnerHTML",
      "--",
      "src",
      ":(exclude)src/content/renderPath.test.ts",
    ]);

    expect(result.output.trim()).toBe("");
  });

  it("is enforced by the linter, not just by convention", () => {
    const directory = mkdtempSync(join(tmpdir(), "traindrain-lint-"));
    const probe = join(directory, "Probe.tsx");
    writeFileSync(
      probe,
      "export function Probe({ html }: { html: string }) {\n" +
        "  return <div dangerouslySetInnerHTML={{ __html: html }} />;\n" +
        "}\n",
    );

    try {
      const result = run(resolve(FRONTEND_ROOT, "node_modules/.bin/oxlint"), [
        "--config",
        resolve(FRONTEND_ROOT, ".oxlintrc.json"),
        probe,
      ]);

      expect(result.status).not.toBe(0);
      expect(result.output).toContain("no-danger");
    } finally {
      rmSync(directory, { recursive: true, force: true });
    }
  });
});

function run(command: string, args: string[]): { status: number | null; output: string } {
  try {
    const output = execFileSync(command, args, {
      cwd: FRONTEND_ROOT,
      encoding: "utf8",
      stdio: "pipe",
    });
    return { status: 0, output };
  } catch (error) {
    const failure = error as { status: number | null; stdout?: string; stderr?: string };
    return {
      status: failure.status,
      output: `${failure.stdout ?? ""}${failure.stderr ?? ""}`,
    };
  }
}
