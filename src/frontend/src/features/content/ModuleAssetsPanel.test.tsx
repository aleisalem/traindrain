import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "../../i18n";
import "../../i18n";
import { ModuleAssetsPanel } from "./ModuleAssetsPanel";
import { ModulePagesPanel } from "./ModulePagesPanel";
import { SCHEMA_VERSION } from "../../content/schema";
import { useModuleAssets } from "./useModuleAssets";

const MODULE_ID = "11111111-1111-1111-1111-111111111111";
const ASSETS_URL = `/api/content/modules/${MODULE_ID}/assets`;
const PAGES_URL = `/api/content/modules/${MODULE_ID}/pages`;

type MockResponse = { status: number; body?: unknown };

/**
 * The authoring screen's shape, minus the metadata form: one owner of the asset
 * state, shared by the page editor and the asset panel. Rendering it this way
 * rather than stubbing the hook is the point — the thing worth testing is that
 * an image uploaded from inside the editor shows up in the panel, and that is
 * exactly what a stub would assume rather than prove.
 */
function AuthoringSurface() {
  const assets = useModuleAssets(MODULE_ID);
  return (
    <>
      <ModulePagesPanel moduleId={MODULE_ID} assets={assets} />
      <ModuleAssetsPanel assets={assets} />
    </>
  );
}

function asset(overrides: Record<string, unknown> = {}) {
  return {
    id: "asset-a",
    kind: "image",
    url: `/api/modules/${MODULE_ID}/assets/asset-a`,
    content_type: "image/png",
    size_bytes: 2048,
    original_filename: "diagram.png",
    uploaded_by: { id: "user-a", display_name: "Cora Manager" },
    created_at: "2026-09-01T00:00:00Z",
    referenced_by_pages: 0,
    referenced_by_versions: 0,
    ...overrides,
  };
}

function assetsBody(assets: ReturnType<typeof asset>[]) {
  return {
    assets,
    total_bytes: assets.reduce((sum, one) => sum + (one.size_bytes as number), 0),
    max_module_bytes: 100 * 1024 * 1024,
    max_image_bytes: 5 * 1024 * 1024,
    max_attachment_bytes: 20 * 1024 * 1024,
  };
}

const ONE_PAGE = [
  {
    id: "page-a",
    position: 0,
    title: "Intro",
    schema_version: SCHEMA_VERSION,
    body: { type: "doc", content: [{ type: "paragraph" }] },
    updated_at: "2026-09-01T00:00:00Z",
  },
];

function pagesBody(draftRevision: number) {
  return { draft_revision: draftRevision, schema_version: SCHEMA_VERSION, pages: ONE_PAGE };
}

function createFetchMock() {
  const queues = new Map<string, MockResponse[]>();
  const requests: { key: string; body: unknown }[] = [];

  function queue(method: string, url: string, response: MockResponse) {
    const key = `${method} ${url}`;
    queues.set(key, [...(queues.get(key) ?? []), response]);
  }

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = init?.method ?? "GET";
    const key = `${method} ${url}`;
    requests.push({ key, body: init?.body });
    const queued = queues.get(key)?.shift();
    if (!queued) throw new Error(`No mocked response queued for ${key}`);
    return new Response(JSON.stringify(queued.body), {
      status: queued.status,
      headers: { "Content-Type": "application/json" },
    });
  });

  return { fetchMock, queue, requests };
}

function pngFile(name = "diagram.png") {
  return new File([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], name, { type: "image/png" });
}

describe("module assets", () => {
  let queue: ReturnType<typeof createFetchMock>["queue"];
  let requests: ReturnType<typeof createFetchMock>["requests"];

  beforeEach(async () => {
    await i18n.changeLanguage("en");
    const mock = createFetchMock();
    queue = mock.queue;
    requests = mock.requests;
    vi.stubGlobal("fetch", mock.fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lists a module's images and attachments with their sizes", async () => {
    queue("GET", PAGES_URL, { status: 200, body: pagesBody(5) });
    queue("GET", ASSETS_URL, {
      status: 200,
      body: assetsBody([
        asset({ referenced_by_pages: 2 }),
        asset({
          id: "asset-b",
          kind: "attachment",
          url: `/api/modules/${MODULE_ID}/assets/asset-b`,
          content_type: "application/pdf",
          original_filename: "policy.pdf",
          size_bytes: 1024 * 1024,
        }),
      ]),
    });

    render(<AuthoringSurface />);

    const image = (await screen.findByText("diagram.png")).closest("li");
    expect(within(image as HTMLElement).getByText(/2 KB/)).toHaveTextContent(
      "used on 2 pages",
    );
    const attachment = screen.getByText("policy.pdf").closest("li");
    expect(within(attachment as HTMLElement).getByText(/1\.0 MB/)).toBeInTheDocument();
    // An attachment is a download; an image is not.
    expect(screen.getByRole("link", { name: "Download" })).toHaveAttribute(
      "href",
      `/api/modules/${MODULE_ID}/assets/asset-b`,
    );
  });

  it("shows how much of the module's storage budget is left", async () => {
    queue("GET", PAGES_URL, { status: 200, body: pagesBody(5) });
    queue("GET", ASSETS_URL, { status: 200, body: assetsBody([asset()]) });

    render(<AuthoringSurface />);

    expect(await screen.findByText(/2 KB of 100\.0 MB used/)).toBeInTheDocument();
    expect(
      screen.getByText(/up to 5\.0 MB per image, 20\.0 MB per attachment/),
    ).toBeInTheDocument();
  });

  it("uploads an image as multipart form data with its declared kind", async () => {
    const user = userEvent.setup();
    queue("GET", PAGES_URL, { status: 200, body: pagesBody(5) });
    queue("GET", ASSETS_URL, { status: 200, body: assetsBody([]) });
    queue("POST", ASSETS_URL, { status: 201, body: assetsBody([asset()]) });

    render(<AuthoringSurface />);
    await screen.findByText("Nothing uploaded yet.");

    await user.upload(screen.getByLabelText("Upload image"), pngFile());

    const posted = requests.find((request) => request.key === `POST ${ASSETS_URL}`);
    const form = posted?.body as FormData;
    expect(form.get("kind")).toBe("image");
    expect((form.get("file") as File).name).toBe("diagram.png");
    expect(await screen.findByText("diagram.png")).toBeInTheDocument();
  });

  it("uploads an attachment under the attachment kind", async () => {
    const user = userEvent.setup();
    queue("GET", PAGES_URL, { status: 200, body: pagesBody(5) });
    queue("GET", ASSETS_URL, { status: 200, body: assetsBody([]) });
    queue("POST", ASSETS_URL, { status: 201, body: assetsBody([]) });

    render(<AuthoringSurface />);
    await screen.findByText("Nothing uploaded yet.");

    await user.upload(
      screen.getByLabelText("Upload attachment"),
      new File([new Uint8Array([0x25, 0x50, 0x44, 0x46])], "policy.pdf", {
        type: "application/pdf",
      }),
    );

    const posted = requests.find((request) => request.key === `POST ${ASSETS_URL}`);
    expect(posted).toBeDefined();
    expect((posted!.body as FormData).get("kind")).toBe("attachment");
  });

  it("explains an SVG rejection rather than reporting a generic failure", async () => {
    const user = userEvent.setup();
    queue("GET", PAGES_URL, { status: 200, body: pagesBody(5) });
    queue("GET", ASSETS_URL, { status: 200, body: assetsBody([]) });
    queue("POST", ASSETS_URL, {
      status: 415,
      body: { detail: { code: "svg_not_allowed", message: "no svg" } },
    });

    render(<AuthoringSurface />);
    await screen.findByText("Nothing uploaded yet.");
    // Declared `image/png` so it passes the picker's own `accept` hint — which
    // is exactly the case that matters, since the hint is convenience and the
    // server's byte-sniffing is the control.
    await user.upload(
      screen.getByLabelText("Upload image"),
      new File(["<svg/>"], "logo.png", { type: "image/png" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "SVG files can carry scripts and are not accepted",
    );
    // Nothing was added to the list on a refusal.
    expect(screen.getByText("Nothing uploaded yet.")).toBeInTheDocument();
  });

  it("reports the server's own message when a file is too large", async () => {
    const user = userEvent.setup();
    queue("GET", PAGES_URL, { status: 200, body: pagesBody(5) });
    queue("GET", ASSETS_URL, { status: 200, body: assetsBody([]) });
    queue("POST", ASSETS_URL, {
      status: 413,
      body: {
        detail: {
          code: "file_too_large",
          message: "This file is larger than the 5 MB limit.",
        },
      },
    });

    render(<AuthoringSurface />);
    await screen.findByText("Nothing uploaded yet.");
    await user.upload(screen.getByLabelText("Upload image"), pngFile("huge.png"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This file is larger than the 5 MB limit.",
    );
  });

  it("asks before deleting, and says how many pages still use the image", async () => {
    const user = userEvent.setup();
    queue("GET", PAGES_URL, { status: 200, body: pagesBody(5) });
    queue("GET", ASSETS_URL, {
      status: 200,
      body: assetsBody([asset({ referenced_by_pages: 3 })]),
    });
    queue("DELETE", `${ASSETS_URL}/asset-a`, { status: 200, body: assetsBody([]) });

    render(<AuthoringSurface />);
    await user.click(await screen.findByRole("button", { name: "Delete diagram.png" }));

    expect(screen.getByText("Used on 3 pages — delete anyway?")).toBeInTheDocument();
    // Nothing has been sent yet — the confirmation is a real gate.
    expect(requests.some((request) => request.key.startsWith("DELETE"))).toBe(false);

    await user.click(screen.getByRole("button", { name: /^Delete$/ }));

    expect(requests.some((request) => request.key === `DELETE ${ASSETS_URL}/asset-a`)).toBe(true);
    expect(await screen.findByText("Nothing uploaded yet.")).toBeInTheDocument();
  });

  it("warns harder when a published version still shows the image", async () => {
    // A draft page losing an image is fixable in the editor. A published
    // version is a frozen snapshot — there is no edit that puts it back.
    const user = userEvent.setup();
    queue("GET", PAGES_URL, { status: 200, body: pagesBody(5) });
    queue("GET", ASSETS_URL, {
      status: 200,
      body: assetsBody([asset({ referenced_by_pages: 0, referenced_by_versions: 2 })]),
    });

    render(<AuthoringSurface />);
    await user.click(await screen.findByRole("button", { name: "Delete diagram.png" }));

    expect(
      screen.getByText(
        "Still shown in 2 published versions, which cannot be edited to remove it — delete anyway?",
      ),
    ).toBeInTheDocument();
  });

  it("keeps the asset when the author backs out of the confirmation", async () => {
    const user = userEvent.setup();
    queue("GET", PAGES_URL, { status: 200, body: pagesBody(5) });
    queue("GET", ASSETS_URL, { status: 200, body: assetsBody([asset()]) });

    render(<AuthoringSurface />);
    await user.click(await screen.findByRole("button", { name: "Delete diagram.png" }));
    await user.click(screen.getByRole("button", { name: "Keep" }));

    expect(requests.some((request) => request.key.startsWith("DELETE"))).toBe(false);
    expect(screen.getByText("diagram.png")).toBeInTheDocument();
  });

  it("inserts an uploaded image into the page body as an image node", async () => {
    const user = userEvent.setup();
    queue("GET", PAGES_URL, { status: 200, body: pagesBody(5) });
    queue("GET", ASSETS_URL, { status: 200, body: assetsBody([asset()]) });
    queue("PATCH", `${PAGES_URL}/page-a`, { status: 200, body: pagesBody(6) });

    render(<AuthoringSurface />);
    await screen.findByLabelText("Page title");

    await user.click(await screen.findByRole("button", { name: "Image" }));
    await user.type(screen.getByLabelText("Alt text"), "A phishing email");
    await user.click(screen.getByRole("button", { name: "Insert diagram.png" }));
    await user.click(screen.getByRole("button", { name: "Save page" }));

    const saved = requests.find((request) => request.key === `PATCH ${PAGES_URL}/page-a`);
    const body = JSON.parse(saved?.body as string);
    const images = JSON.stringify(body.body);
    // The src is the authorizing API path the schema's `imageSrcPattern` pins,
    // never a presigned URL and never an outside host.
    expect(images).toContain(`"src":"/api/modules/${MODULE_ID}/assets/asset-a"`);
    expect(images).toContain('"alt":"A phishing email"');
  });

  it("offers no way to point an image at an arbitrary URL", async () => {
    const user = userEvent.setup();
    queue("GET", PAGES_URL, { status: 200, body: pagesBody(5) });
    queue("GET", ASSETS_URL, { status: 200, body: assetsBody([asset()]) });

    render(<AuthoringSurface />);
    await screen.findByLabelText("Page title");
    await user.click(await screen.findByRole("button", { name: "Image" }));

    // Alt text and a picker, and nothing that takes a src.
    const inputs = screen.getAllByRole("textbox");
    expect(inputs.map((input) => input.getAttribute("aria-label") ?? "")).not.toContain("src");
    expect(screen.queryByPlaceholderText("https://")).not.toBeInTheDocument();
  });

  it("uploads from inside the editor and inserts the result immediately", async () => {
    const user = userEvent.setup();
    queue("GET", PAGES_URL, { status: 200, body: pagesBody(5) });
    queue("GET", ASSETS_URL, { status: 200, body: assetsBody([]) });
    queue("POST", ASSETS_URL, { status: 201, body: assetsBody([asset()]) });
    queue("PATCH", `${PAGES_URL}/page-a`, { status: 200, body: pagesBody(6) });

    render(<AuthoringSurface />);
    await screen.findByLabelText("Page title");
    await user.click(await screen.findByRole("button", { name: "Image" }));

    await user.upload(screen.getByLabelText("Upload and insert"), pngFile());
    await user.click(screen.getByRole("button", { name: "Save page" }));

    const saved = requests.find((request) => request.key === `PATCH ${PAGES_URL}/page-a`);
    expect(JSON.stringify(JSON.parse(saved?.body as string).body)).toContain(
      `"src":"/api/modules/${MODULE_ID}/assets/asset-a"`,
    );
    // And it is in the panel too — one list, not two.
    expect(await screen.findByText("diagram.png")).toBeInTheDocument();
  });

  it("tells the author when the asset list could not be loaded", async () => {
    queue("GET", PAGES_URL, { status: 200, body: pagesBody(5) });
    queue("GET", ASSETS_URL, { status: 500, body: {} });

    render(<AuthoringSurface />);

    expect(await screen.findByRole("alert")).toHaveTextContent("We couldn't load this");
    // The pages panel loaded fine — only the asset section degrades.
    expect(screen.getByRole("heading", { name: "Images and attachments" })).toBeInTheDocument();
  });
});
