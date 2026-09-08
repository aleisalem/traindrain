# Module Content Format for Release 1: Sanitized HTML vs. Structured Editor JSON (vs. Hybrid)

**Status:** Research complete, decision pending
**Scope:** TrainDrain Release 1 — "Learning Modules." A module is metadata plus an ordered list of
pages; each page holds one rich-text body authored by a non-technical **Content Manager** in a
WYSIWYG editor and rendered to every **Learner** inside an authenticated session. The question is
what that body is *stored as*: sanitized HTML, a structured editor document (a ProseMirror/Tiptap
JSON node tree), or a hybrid (JSON as source of truth with a sanitized-HTML projection cached
alongside it). The choice has to survive Release 1's module **import** feature and Release 4's
**AI-authored modules**, which must save into whatever schema Release 1 defines.
**Method:** Primary sources only (official docs, source repositories, specs, CVE/GitHub Security
Advisory and RustSec advisory entries, first-party API docs). Every claim below is followed back to
the page that states it; see inline citations and the References section. Two claims about
PostgreSQL indexing behaviour could not be settled from the PostgreSQL documentation, so they were
measured directly against a throwaway PostgreSQL 16.11 container — those are labelled as
measurements, not citations, with the exact commands so they can be re-run.

---

## 1. Stored-XSS exposure and the track record of the sanitizers in play

The two formats fail differently, and the difference is structural rather than a matter of degree.

**Sanitized HTML.** The entire defense is a single server-side sanitizer that must model a browser's
HTML parser correctly. That is the load-bearing assumption, and it is exactly the assumption that
mutation-XSS (mXSS) attacks break: markup that is inert when the sanitizer parses it becomes active
when the browser re-parses the sanitizer's own output.

**`bleach` is disqualified outright on maintenance grounds, not on merit.** Its README states,
verbatim: **"NOTE: 2026-06-05: Bleach is no longer maintained. There will be no future releases
including for security issues"** ([github.com/mozilla/bleach](https://github.com/mozilla/bleach)).
PyPI shows the last release is 6.4.0, published 2026-06-05 — the same day as that notice
([pypi.org/project/bleach](https://pypi.org/project/bleach/)). GitHub's advisory database lists ten
advisories against the `bleach` pip package, including a critical URI-scheme-restriction bypass
(CVE-2018-7753), two mXSS advisories tied to allowlisted `math`/`svg`/`noscript` plus a raw-text tag
(CVE-2020-6816, CVE-2020-6802), a cross-site-scripting advisory (CVE-2021-23980), two ReDoS
advisories (CVE-2020-6817, CVE-2014-8881), and three advisories published 2026-06-16
([github.com/advisories?query=bleach](https://github.com/advisories?query=bleach)). Those last three
— a `formaction` scheme-sanitization bypass (GHSA-gj48-438w-jh9v), a `linkify(parse_email=True)` CPU
exhaustion (GHSA-g75f-g53v-794x), and a URI-scheme bypass using Unicode above U+00A0
(GHSA-8rfp-98v4-mmr6) — are all patched in 6.4.0
([GHSA-gj48-438w-jh9v](https://github.com/advisories/GHSA-gj48-438w-jh9v),
[GHSA-8rfp-98v4-mmr6](https://github.com/advisories/GHSA-8rfp-98v4-mmr6)). So `bleach` is *currently*
patched. The problem is the forward-looking guarantee: its maintainers have stated there will be no
further security releases, and its ten-advisory history shows this is a library class that keeps
finding new bypasses. Adopting it would mean building TrainDrain's only anti-XSS control on a
component with a declared end-of-life.

**`nh3` / `ammonia` is the credible HTML-sanitizer option.** `nh3` is "Python bindings to the ammonia
HTML sanitization library," MIT-licensed, latest release 0.3.7 on 2026-08-23
([github.com/messense/nh3](https://github.com/messense/nh3),
[pypi.org/project/nh3](https://pypi.org/project/nh3/)), and its `Cargo.toml` pins `ammonia = "4.1.4"`
([nh3 Cargo.toml](https://raw.githubusercontent.com/messense/nh3/main/Cargo.toml)). Ammonia is
"a whitelist-based HTML sanitization library... designed to prevent cross-site scripting, layout
breaking, and clickjacking caused by untrusted user-provided HTML being mixed into a larger web
page," and it "uses html5ever to parse and serialize document fragments the same way browsers do,
so it is extremely resilient to syntactic obfuscation"
([github.com/rust-ammonia/ammonia](https://github.com/rust-ammonia/ammonia)) — that browser-identical
parser is precisely the property that makes mXSS harder to land, and it is the strongest technical
argument the HTML option has.

Its defaults are conservative and are what `nh3` inherits: `nh3`'s `ALLOWED_TAGS`,
`ALLOWED_ATTRIBUTES`, and `ALLOWED_URL_SCHEMES` are built by calling `ammonia::Builder::default()`
and cloning its collections ([nh3 src/lib.rs](https://raw.githubusercontent.com/messense/nh3/main/src/lib.rs)).
That default tag set is prose-shaped — `a, abbr, blockquote, br, code, em, h1`–`h6, img, li, ol, p,
pre, strong, table, …` — and notably contains **no `svg`, no `math`, no `script`, no `style`, no
`iframe`, no form elements**. `script` and `style` have their *contents* removed, comments are
stripped by default, `link_rel` defaults to `Some("noopener noreferrer")` (which the docs describe as
preventing "a particular type of XSS attack" and say "should usually be turned on for untrusted
HTML"), and the default URL-scheme allowlist is a fixed set — `http`, `https`, `mailto`, `ftp`,
`tel`, `bitcoin`, `magnet`, `irc`, `xmpp` and similar — that does **not** include `javascript:` or
`data:` ([docs.rs — ammonia::Builder](https://docs.rs/ammonia/latest/ammonia/struct.Builder.html)).
`nh3.clean()`'s own signature defaults are `strip_comments=True` and
`link_rel="noopener noreferrer"`, with everything else falling back to those ammonia constants
([nh3.readthedocs.io](https://nh3.readthedocs.io/en/latest/)).

Ammonia's advisory history is instructive precisely because of *where* the bugs land. RustSec lists
six advisories for the crate: RUSTSEC-2026-0213 ("XSS in ammonia via SVG `animate` and `set`
animation tags"), RUSTSEC-2026-0193 ("mXSS in ammonia via MathML `annotation-xml` encoding strip"),
RUSTSEC-2025-0071 ("Incorrect handling of embedded SVG and MathML leads to mutation XSS after
removal"), RUSTSEC-2022-0003, RUSTSEC-2021-0074 (an earlier SVG/MathML mXSS), and RUSTSEC-2019-0001
(uncontrolled recursion, HIGH) ([rustsec.org/packages/ammonia](https://rustsec.org/packages/ammonia.html)).
Three of those are from the last two years, which is a candid signal that this bug class is still
being found. But the two most recent both state that the default configuration is not affected:
RUSTSEC-2026-0213 says **"Applications that do not explicitly allow either of these tags should not
be affected, since neither are allowed by default"**
([RUSTSEC-2026-0213](https://rustsec.org/advisories/RUSTSEC-2026-0213.html)), and RUSTSEC-2025-0071
says the vulnerability "only has an effect when the `svg` or `math` tag is allowed" *and* at least
one raw-text element (`style`, `script`, `title`, `textarea`, `iframe`) is allowed — none of which
are permitted by default ([RUSTSEC-2025-0071](https://rustsec.org/advisories/RUSTSEC-2025-0071.html)).
Maintenance response is the mirror image of `bleach`'s: ammonia 4.1.4, 4.0.3, and 3.3.3 were all
published within three minutes of each other on 2026-07-22, i.e. the fix was backported across three
release lines simultaneously ([crates.io API — ammonia](https://crates.io/api/v1/crates/ammonia)).

**Structured editor JSON.** No HTML string is ever stored, so there is nothing for a sanitizer to get
wrong at write time. The document is a node tree validated against an explicit schema —
ProseMirror's "schema describes the kind of nodes that may occur in the document, and the way they
are nested" ([prosemirror.net/docs/guide](https://prosemirror.net/docs/guide/)) — and Tiptap
describes the same schema as the gate: "This schema is *very* strict. You can't use any HTML element
or attribute that is not defined in your schema"
([tiptap.dev — Schema](https://tiptap.dev/docs/editor/core-concepts/schema)). At render time, React
escapes text content by construction, and Tiptap ships a renderer that produces React elements
rather than an HTML string: `renderToReactElement` from `@tiptap/static-renderer/pm/react`, where
"The static renderer doesn't require a browser, DOM or even an editor instance to render the
content. It's a pure JavaScript function that takes a document (as JSON or Prosemirror Node
instance) and returns the target format back"
([tiptap.dev — Static renderer](https://tiptap.dev/docs/editor/api/utilities/static-renderer)); the
package is MIT and lives in the main Tiptap monorepo
([registry.npmjs.org/@tiptap/static-renderer](https://registry.npmjs.org/@tiptap/static-renderer/latest)).
That path means `dangerouslySetInnerHTML` never appears in the learner-facing render — the API React's
own docs describe as: "**This is dangerous. As with the underlying DOM `innerHTML` property, you must
exercise extreme caution! Unless the markup is coming from a completely trusted source, it is trivial
to introduce an XSS vulnerability this way**"
([react.dev — Common components](https://react.dev/reference/react-dom/components/common)).

**Where the residual risk actually sits under JSON.** Not in text, but in *attributes*. A link mark's
`href` and an image node's `src` are still passed to the DOM as attribute values, and a
`javascript:` href in a schema-valid document is a schema-valid document. Tiptap's Link extension
does expose `protocols`, `defaultProtocol`, `isAllowedUri`, and `shouldAutoLink` options, but its own
documentation frames them as autolinking/recognition controls and contains no explicit statement
that it blocks `javascript:` URLs for security
([tiptap.dev — Link extension](https://tiptap.dev/docs/editor/extensions/marks/link)) — so link/image
URL validation must be treated as the application's job, enforced server-side at write time, not
delegated to the editor. Note also that these are *client-side* options in an editor the Content
Manager controls: a hostile client can POST any JSON it likes, so the schema and URL checks are only
a security control if they run on the FastAPI side.

**Tradeoff.** Under sanitized HTML, the security property is "one library, on every write, models the
browser's parser correctly" — and that library's own advisory record (ten for `bleach`, six for
ammonia, three of ammonia's in the last two years) shows the assumption is periodically violated.
The mitigation is real and cheap (stay on the default tag set, never allow `svg`/`math`/raw-text
elements, keep `nh3` patched), and ammonia's default-configuration exemptions plus its
three-release-line backport in July 2026 are genuine evidence that this is a well-run project. Under
structured JSON, the class of "sanitizer got the parse wrong" simply does not exist, because no
attacker-influenced HTML string is ever parsed or serialized; what remains is a narrower, more
auditable obligation — validate the node/mark allowlist and validate `href`/`src` schemes — that is
application code you own rather than a dependency you trust. The honest counterweight is that JSON's
guarantee holds only as long as nothing downstream projects the tree back into an HTML string; the
moment anything does (email, PDF export, a cached HTML column), every HTML risk above returns for
that path.

## 2. Interaction with a strict Content-Security-Policy

CSP is the same defense-in-depth layer for both formats, and MDN is explicit about what it buys: "If
a CSP contains either a `default-src` or a `script-src` directive, then inline JavaScript will not be
allowed to execute unless extra measures are taken to enable it. This includes: JavaScript included
inside a `<script>` element in the page; JavaScript in an inline event handler attribute; JavaScript
in a `javascript:` URL," with the warning that "Developers should avoid `'unsafe-inline'`, because it
defeats much of the purpose of having a CSP. Inline JavaScript is one of the most common XSS vectors"
([MDN — Content Security Policy](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CSP)).

Concretely: a strict `script-src` neutralises the two payload shapes that both a sanitizer bypass and
an unvalidated `href` most commonly produce — an `onerror=` attribute that survived sanitization, and
a `javascript:` link. It does **not** neutralise everything either format can carry. An `<img src>`
or a CSS `url()` pointing at an attacker-controlled host still exfiltrates a request (and, on an
authenticated learner page, whatever is in the referrer or the surrounding context) unless `img-src`
and `style-src` are locked down too, and neither format's storage decision changes that.

**Tradeoff.** CSP is required for TrainDrain regardless of which format wins, and it does not
meaningfully separate the two — it is strictly a second line behind whichever primary control is
chosen. What it *does* change is the cost of being wrong: under sanitized HTML a CSP failure and a
sanitizer failure must coincide for stored XSS to land, and under JSON a CSP failure and a
URL-validation failure must coincide. The second pair is smaller and entirely in-repo, but the
practical difference here is modest, and it would be overstating the case to treat CSP as a reason to
pick one format over the other.

## 3. Accessibility to non-technical authors, and Tiptap's licensing

The first thing to record is that **this dimension is close to neutral, and the reason is that the
same editor produces both formats.** Tiptap is built on ProseMirror and exposes both `getJSON()` and
`getHTML()`; its own guidance on the choice reads, in full: JSON "is probably easier to loop through,
for example to look for a mention" and "it's more like what Tiptap uses under the hood," while HTML
"can be easily rendered in other places, for example in emails" and "it's widely used, so it's
probably easier to switch the editor at some point"
([tiptap.dev — JSON and HTML](https://tiptap.dev/docs/guides/output-json-html)). The WYSIWYG
experience a Content Manager sees is identical either way. Neither format constrains the toolbar.

Where the formats *do* diverge for authors is round-tripping. Because the schema is strict, content
that exists in the database but not in the schema is silently discarded on the next save — and
Tiptap says plainly that its ability to *detect* that differs by format: "The content checking that
Tiptap runs is 100% accurate on JSON content types. But, if you provide your content as HTML, we have
done our best to try to alert on missing nodes but marks can be missed in certain situations"
([tiptap.dev — Schema](https://tiptap.dev/docs/editor/core-concepts/schema)). The vendor's own
documented illustration of the failure is a data-loss one: "If you paste something like `This is
<strong>important</strong>` into Tiptap, but don't have any extension that handles `strong` tags,
you'll only see `This is important` – without the strong tags." For a compliance-training platform
where a module's content is the record, "an author opened a page and formatting silently vanished on
save" is a real product defect, and HTML storage is the format for which the vendor declines to
guarantee detection.

**Licensing, which materially affects what is actually available.** The Tiptap repository is MIT:
"The MIT License (MIT). Please see License File for more information"
([github.com/ueberdosis/tiptap](https://github.com/ueberdosis/tiptap)), and the pricing page states
"The Tiptap Editor is open source (MIT) and free. Only platform features and cloud documents are
priced" ([tiptap.dev/pricing](https://tiptap.dev/pricing)). The free StarterKit covers essentially
all of Release 1's authoring surface — nodes Blockquote, BulletList, CodeBlock, Document, HardBreak,
Heading, HorizontalRule, ListItem, OrderedList, Paragraph, Text; marks Bold, Code, Italic, Link,
Strike, Underline; plus Dropcursor, Gapcursor, Undo/Redo, ListKeymap, TrailingNode
([tiptap.dev — StarterKit](https://tiptap.dev/docs/editor/extensions/functionality/starterkit)).

What is **not** free matters for later releases and for import specifically. The README states "Pro
Extensions need a valid subscription" and names the paid surface as "collaborative editing,
commenting, versioning, document conversion and AI related features"
([github.com/ueberdosis/tiptap](https://github.com/ueberdosis/tiptap)); the Pro Extensions guide says
"A Tiptap account is required to access Pro extensions. Select extensions such as Snapshots,
Comments, and some features of AI Toolkit also require an active subscription," installed "from
Tiptap's private NPM registry with your personal access token"
([tiptap.dev — Pro Extensions](https://tiptap.dev/docs/guides/pro-extensions)). Most consequentially
for Release 1's import feature: **Tiptap Conversion — the DOCX/Markdown import and DOCX/PDF/ODT/EPUB/
Markdown export product — is paid.** Its own overview states "Conversion is a Pro package included
with all Tiptap subscriptions," and requires the private NPM registry
([tiptap.dev — Conversion overview](https://tiptap.dev/docs/conversion/getting-started/overview)).
The pricing page places real-time collaboration, comments, document history, and the in-line AI
extension on the Start plan and above ([tiptap.dev/pricing](https://tiptap.dev/pricing)).

**Tradeoff.** Authoring experience is a wash — the same MIT-licensed editor, the same toolbar, the
same StarterKit, whichever format is persisted. The format-specific author-facing risk is
round-trip fidelity, and it points at JSON: Tiptap guarantees 100%-accurate content checking for JSON
and explicitly declines to guarantee it for HTML. The licensing finding is orthogonal to the format
question but binds either choice: TrainDrain gets a full free WYSIWYG, and must plan to build its own
Markdown/HTML import path (Section 5) rather than assume Tiptap Conversion, unless a subscription is
budgeted.

## 4. AI generation, regeneration, and diffing (the Release 4 constraint)

This is the dimension with the sharpest, most checkable asymmetry, and it cuts in a more nuanced
direction than "JSON is structured, therefore better for LLMs."

**Only JSON can be constrained at decode time.** Anthropic's structured outputs "constrain Claude's
responses to follow a specific schema, ensuring valid, parseable output for downstream processing,"
via `output_config.format` with `{"type": "json_schema", "schema": {...}}`; the sibling feature,
strict tool use (`strict: true`), "guarantees Claude's tool inputs match your JSON Schema by
constraining the model's token sampling to schema-valid outputs (a technique called
grammar-constrained sampling)," with the stated guarantees that "Tool `input` strictly follows the
`input_schema`" and "Tool `name` is always valid"
([Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs),
[Strict tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/strict-tool-use)).
Both are supported on `claude-opus-5` and the rest of the current model line. There is no equivalent
mechanism for HTML — no schema, no grammar, no guarantee. Under HTML you find out whether the model
produced acceptable markup only *after* generation, by sanitizing it, and sanitization silently
rewrites rather than erroring, so a malformed or out-of-schema generation degrades quietly instead
of failing loudly.

**But the ProseMirror document shape collides with a documented limitation.** The supported JSON
Schema subset explicitly lists **"Recursive schemas"** under *NOT supported*, alongside external
`$ref`, numerical constraints (`minimum`/`maximum`/`multipleOf`), string constraints
(`minLength`/`maxLength`), and array constraints beyond `minItems` of 0 or 1
([Structured outputs — JSON Schema limitations](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)).
A ProseMirror document is recursive by definition: a node's `content` is an array of nodes, which is
how "the schema describes the kind of nodes that may occur in the document, **and the way they are
nested**" ([prosemirror.net/docs/guide](https://prosemirror.net/docs/guide/)). So a *general*
ProseMirror document tree cannot be expressed as a constrained schema. This is workable but must be
designed for: define the generation schema as a **depth-unrolled** shape (`doc` → `block[]` → inline
runs, with one extra level for list items) rather than a self-referential node type, and treat that
bounded shape as the AI-authoring contract rather than the full editor schema. That is a real
constraint that a Release 4 ticket has to budget for, and it is the strongest honest argument
*against* assuming JSON makes AI authoring trivially easy.

**Markdown as the intermediate.** The most common third path — have the model emit Markdown, convert
server-side — is available to both formats, and converts to JSON with the same MIT-licensed tooling
used for import (Section 5). **No primary source found in this pass measures how reliably a model
emits ProseMirror-shaped JSON versus HTML versus Markdown**; claims of that kind circulate widely but
are not something Anthropic's documentation or ProseMirror's states, so this research does not assert
it. The verifiable asymmetry is narrower and sufficient: JSON is the only one of the three that can
be *grammar-constrained*, and constraint is a guarantee rather than an observed tendency.

**Regeneration and diffing.** Release 4's requirement is a chat loop that "continues to enhance and
regenerate the content, until the user saves the module," so the ability to compare successive
versions matters. ProseMirror documents are immutable values with structural sharing — "nodes are
simply *values*, and should be approached much as you'd approach the value representing the number
3," so every update produces a new document with unchanged sub-nodes shared between versions
([prosemirror.net/docs/guide](https://prosemirror.net/docs/guide/)) — which gives a well-defined
node-level identity to diff against. HTML has no equivalent: two serializations of the same content
can differ in whitespace, attribute order, or tag normalization, so a textual diff reports changes
the reader would not consider changes. This research did not find a primary source benchmarking diff
quality between the two, so this is stated as a structural property of the formats, not as a measured
result.

**Tradeoff.** JSON is the only format the Claude API can *guarantee* the shape of, which for
AI-authored modules saving directly into the Release 1 schema is the difference between a validation
gate and a hope. The cost is concrete and must not be glossed: recursive schemas are unsupported, so
the AI-authoring schema has to be a bounded, unrolled subset of the editor schema, deliberately
designed and kept in sync with it. HTML offers no constraint mechanism at all, and its failure mode
under generation is silent rewriting by the sanitizer rather than an error — which is the worse
failure mode for a system that must reliably persist what the author approved.

## 5. Import and export

Release 1 includes importing modules, with Markdown and HTML as the likely inputs. Both formats need
an importer; the work is comparable, and neither gets it free — Tiptap's own Conversion product is
paid (Section 3).

**Markdown in.** For a Python backend, `markdown-it-py` is the natural CommonMark parser, and its own
security page is unusually direct about the default: "By default, the `MarkdownIt` parser is
initialised to comply with the CommonMark spec, which allows for parsing arbitrary HTML tags," and
"This is not safe when using `markdown-it-py` in web applications that parse user-submitted content."
It offers two strategies — "Enable HTML (as is needed for full CommonMark compliance), and then use
external sanitizer package(s)" or "Disable HTML, and then use plugins to selectively enable markup
features" — and "strongly recommend[s]" the `js-default` preset, which disables HTML parsing, for web
applications handling user content
([markdown-it-py — security](https://markdown-it-py.readthedocs.io/en/latest/security.html)). This
is a direct consequence of the CommonMark spec itself, under which HTML blocks are "treated as raw
HTML (and will not be escaped in HTML output)"
([CommonMark 0.31.2](https://spec.commonmark.org/0.31.2/)). Practically: **a Markdown importer must
disable raw-HTML passthrough regardless of which storage format is chosen**, or every Markdown import
becomes an HTML-injection channel.

**JavaScript-side conversion.** `prosemirror-markdown` provides "a parser and serializer to convert
between ProseMirror documents in that schema and CommonMark/Markdown text" — both directions — under
an MIT license, with the `defaultMarkdownParser` covering "unextended CommonMark, without inline
HTML"
([github.com/ProseMirror/prosemirror-markdown](https://github.com/ProseMirror/prosemirror-markdown)).
Two caveats worth recording honestly: it targets the CommonMark/basic schema, so anything TrainDrain
adds beyond it needs custom parser/serializer tokens; and **the GitHub repository was archived on
2026-04-01 and now points to `code.haverbeke.berlin`** — the same is true of `prosemirror-model`,
whose GitHub repo carries "This repository was archived by the owner on Apr 1, 2026. It is now
read-only" and "This repository has moved to https://code.haverbeke.berlin/prosemirror/prosemirror-model"
([github.com/ProseMirror/prosemirror-model](https://github.com/ProseMirror/prosemirror-model)). This
is a relocation by the maintainer, not an abandonment, but it means GitHub-based signals (stars,
issues, security advisories) no longer track ProseMirror, and dependency-monitoring should be pointed
at npm instead.

**HTML in.** Tiptap's `generateJSON` "convert[s] HTML to JSON by taking an HTML string and returning
a JSON object representing the HTML as a ProseMirror document," and the server-compatible
`@tiptap/html` package uses "a virtual DOM... to generate the HTML"
([tiptap.dev — HTML utility](https://tiptap.dev/docs/editor/api/utilities/html)) — meaning that path
needs a JavaScript runtime, which a FastAPI backend does not have. The pure-Python alternative is
**`prosemirror-py`**, a native Python port of `prosemirror-model`, `prosemirror-transform`,
`prosemirror-schema-basic` and related modules; it uses lxml for HTML parsing, includes custom
Element/DocumentFragment classes for serialization and a `from_html()` helper for parsing HTML
strings directly, is BSD-3-Clause licensed, Python-3-only, and states "The full ProseMirror test
suite has been translated and passes"
([github.com/fellowapp/prosemirror-py](https://github.com/fellowapp/prosemirror-py)). That library is
what makes structured JSON viable on a Python-only backend: it provides both server-side schema
validation and HTML→JSON conversion without a Node sidecar.

**Export.** HTML storage exports to HTML for free. JSON storage exports via
`@tiptap/static-renderer`, which renders "JSON content as HTML, markdown, or React components without
an editor instance," explicitly without a browser or DOM
([tiptap.dev — Static renderer](https://tiptap.dev/docs/editor/api/utilities/static-renderer)) — but
that is a JavaScript package, so a Python backend producing HTML/Markdown export would either use
`prosemirror-py`'s serializer or move that step to the frontend/a small Node service. Anything richer
(DOCX/PDF/ODT/EPUB) is Tiptap Conversion, i.e. paid, for either format
([tiptap.dev — Conversion overview](https://tiptap.dev/docs/conversion/getting-started/overview)).

**Tradeoff.** Import is a genuine point in HTML's favour on effort: HTML in, sanitize, store, done.
JSON import needs one extra hop (sanitize → parse to a node tree), which `prosemirror-py` supplies in
Python, MIT/BSD-licensed, with no Node dependency. Both paths must disable raw-HTML passthrough in
the Markdown parser, so that obligation is shared. The real asymmetry is on the *export* side and it
favours HTML: a Python backend rendering stored JSON to HTML for email or PDF has to reach for
`prosemirror-py`'s serializer or a JS step, whereas stored HTML is already in the target format.

## 6. PostgreSQL full-text search

This is the dimension where the documentation was insufficient and direct measurement settled it.

PostgreSQL's `to_tsvector` accepts `text`, `json`, and `jsonb`; for JSON input it "converts each
string value in the JSON document to a `tsvector`... The results are then concatenated in document
order." The filtered variants `json_to_tsvector`/`jsonb_to_tsvector` take a `filter` argument that
"must be a `jsonb` array containing zero or more of these keywords: `"string"` (to include all string
values), `"numeric"`, `"boolean"`, `"key"` (to include all keys), `"all"`"
([PostgreSQL — Text Search Functions](https://www.postgresql.org/docs/current/functions-textsearch.html)).
The default parser does recognise HTML/XML markup as its own token type — `tag`, described as "XML
tag" with the example `<a href="dictionaries.html">`
([PostgreSQL — Parsers](https://www.postgresql.org/docs/current/textsearch-parsers.html)) — but the
documentation does not publish the complete token-type mapping of the built-in `english`
configuration, and the configuration example only notes in passing that "We choose not to index or
search some token types that the built-in configuration does handle"
([PostgreSQL — Configuration Example](https://www.postgresql.org/docs/current/textsearch-configuration.html)).
Whether HTML tags end up in the index therefore cannot be answered from the docs.

**Measured, not cited** (PostgreSQL 16.11, `postgres:16-alpine`, throwaway container, `\dF+ english`
plus two `SELECT`s). `\dF+ english` shows `pg_catalog.english` maps 19 token types — `asciiword`,
`word`, `hword*`, `numword`, `email`, `url`, `url_path`, `host`, `file`, `int`, `uint`, `float`,
`sfloat`, `version` — and **`tag` is not among them**. The consequence:

```
to_tsvector('english', '<p class="lead">Fire <a href="https://evil.example/x">safety</a> rules</p>')
  → 'fire':1 'rule':3 'safeti':2

jsonb_to_tsvector('english',
  '{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text",
    "text":"Fire safety rules","marks":[{"type":"link",
    "attrs":{"href":"https://evil.example/x"}}]}]}]}'::jsonb, '["string"]')
  → '/x':15 'doc':1 'evil.example':14 'evil.example/x':13 'fire':5 'link':11
    'paragraph':3 'rule':7 'safeti':6 'text':9
```

HTML indexes cleanly out of the box — tags, class names, and the `href` are all absorbed into
unindexed `tag` tokens, leaving exactly the prose. The JSONB tree does not: `"string"` means *all*
string values, and in a ProseMirror document that includes every node's `type` discriminator
(`doc`, `paragraph`, `text`, `link`) and every string attribute value (the link URL, split into
`evil.example`, `/x`, `evil.example/x`). A learner searching for "link" or "text" would match every
page in the system.

The fix is routine and does not require a second format. PostgreSQL's own recommended pattern is a
stored generated column plus a GIN index: `ALTER TABLE ... ADD COLUMN textsearchable_index_col
tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(title,'') || ' ' || coalesce(body,'')))
STORED;` then `CREATE INDEX ... USING GIN (...)`, which the docs recommend over an expression index
because "Searches will be faster, since it will not be necessary to redo the `to_tsvector` calls to
verify index matches"
([PostgreSQL — Tables and Indexes](https://www.postgresql.org/docs/current/textsearch-tables.html)).
Under JSON storage, the module-page row gains a plain-text `search_text` column populated on write by
walking the node tree and concatenating `text` nodes, with the generated `tsvector` column derived
from that. That is a small, well-understood piece of application code — and it is worth noting the
same extraction is needed anyway for search excerpts, reading-time estimates, and AI context.

**Tradeoff.** This is the clearest single dimension in HTML's favour, and it should not be
soft-pedalled: `to_tsvector` over sanitized HTML produces a correct, noise-free index with zero
application code, while indexing a JSONB document tree with the documented `["string"]` filter
produces measurably polluted results. The mitigation for JSON is a derived plain-text column, which
is cheap and reusable, but it is real work that HTML does not require.

## 7. Is the hybrid warranted, or is it premature complexity?

The hybrid — JSON as source of truth, sanitized HTML cached alongside for rendering and/or search —
is worth taking seriously because it appears to buy Section 6's clean FTS and Section 5's free export
without giving up Section 4's schema guarantees. On inspection it mostly does not.

- **For search, the hybrid solves the wrong problem.** Section 6's measurement shows the JSONB
  problem is fixed by extracting *plain text*, not by producing HTML. Caching an HTML projection to
  feed `to_tsvector` is a strictly more expensive way to get a string that a node-tree walk would
  produce directly, and it means the search index depends on the sanitizer being correct.
- **For rendering, the hybrid reintroduces the exact risk JSON removes.** A cached HTML column is
  rendered with `dangerouslySetInnerHTML`, which React's docs call trivial to turn into an XSS hole
  ([react.dev](https://react.dev/reference/react-dom/components/common)), and its safety again rests
  on nh3/ammonia parsing identically to the browser — the assumption Section 1's advisory record
  shows is periodically violated. Rendering from JSON via `renderToReactElement` has no such
  dependency.
- **It doubles the write path and adds an invalidation surface.** Every save must produce both
  representations, and any schema change or sanitizer-config change makes every cached projection
  stale. On a Python-only backend the projection step also needs either `prosemirror-py`'s serializer
  or a Node sidecar (`@tiptap/static-renderer` / `@tiptap/html`, which "uses a virtual DOM"
  ([tiptap.dev](https://tiptap.dev/docs/editor/api/utilities/html))) — a new deployment component in
  an AWS ECS/Fargate stack that currently has none.
- **It contradicts AGENTS.md's "KEEP THE DESIGN SIMPLE" for a benefit that is deferrable.** Nothing
  in Release 1 requires an HTML projection. The concrete future need — HTML for notification emails,
  or a PDF/print export — is a *boundary* concern that can be satisfied by generating HTML on demand
  at that boundary, where its output goes to an email client or a PDF renderer rather than back into
  the learner's authenticated session.

**Tradeoff.** The hybrid is premature complexity for Release 1: two write paths, a cache-invalidation
problem, an extra runtime dependency, and the reintroduction of the HTML-sanitizer trust assumption
into the render path — in exchange for a search benefit that a plain-text column delivers more
cheaply and an export benefit that is not yet needed. It becomes defensible later, and only if a
measured need appears (e.g. HTML email digests are shipped and the JSON→HTML render becomes a
throughput problem) — at which point it should be a derived, regenerable projection with an explicit
version stamp, never a second source of truth.

---

## Summary table

| Dimension | Sanitized HTML (`nh3`/ammonia) | Structured editor JSON (ProseMirror/Tiptap) | Edge |
|---|---|---|---|
| Stored-XSS exposure | Entire defense is one sanitizer modelling the browser parser; ammonia has 6 RustSec advisories (3 since 2025), though the two newest explicitly do not affect the default config. `bleach` is disqualified: "no longer maintained... no future releases including for security issues" | No attacker-influenced HTML string is ever parsed or serialized; render via `renderToReactElement`, no `dangerouslySetInnerHTML`. Residual risk narrows to `href`/`src` scheme validation, which is in-repo application code | JSON |
| Sanitizer/library health | ammonia 4.1.4 + backports to 4.0.3/3.3.3 published together 2026-07-22; `nh3` 0.3.7 (2026-08-23) pins 4.1.4; MIT. `bleach` end-of-life | Tiptap MIT; `@tiptap/static-renderer` MIT; `prosemirror-py` BSD-3. ProseMirror repos archived on GitHub 2026-04-01, moved to `code.haverbeke.berlin` (relocation, not abandonment) | Roughly even; different risks |
| CSP interaction | Strict `script-src` blocks surviving `onerror`/`javascript:` payloads | Same protection, against a smaller residual surface | Neutral |
| Author (WYSIWYG) experience | Identical — same editor, same free StarterKit | Identical | Neutral |
| Round-trip fidelity for authors | Tiptap: content checking on HTML input "can be missed in certain situations"; unmodelled markup silently dropped on save | Tiptap: content checking "100% accurate on JSON content types" | JSON |
| AI generation (Release 4) | No schema, no grammar constraint; failures surface as silent sanitizer rewrites | Only format Claude can grammar-constrain (`output_config.format` / `strict: true`) — but **recursive schemas are unsupported**, so the AI schema must be a depth-unrolled subset | JSON, with a real design cost |
| Diff/regeneration | Textual diffs sensitive to whitespace/attribute-order/normalization | Immutable node values with structural sharing give node-level identity | JSON (structural claim, not benchmarked) |
| Import | Sanitize and store; one hop | One extra hop (sanitize → node tree) via `prosemirror-py` `from_html()`, pure Python. Both must disable raw-HTML passthrough in the Markdown parser | HTML, modestly |
| Export | Already in target format | Needs `prosemirror-py` serializer or a JS step; DOCX/PDF/ODT/EPUB is paid Tiptap Conversion either way | HTML |
| Postgres FTS | `to_tsvector('english', html)` yields clean prose tokens — `tag` is not mapped in `pg_catalog.english` (measured, PG 16.11); zero application code | `jsonb_to_tsvector(..., '["string"]')` indexes node type names and URL fragments (measured); needs a derived plain-text column + generated `tsvector` + GIN | HTML, clearly |

## Recommendation

**Store the page body as structured editor JSON — a ProseMirror/Tiptap document tree in a `jsonb`
column — with a plain-text column derived from it for search. Do not adopt the hybrid for Release 1.**

The evidence is genuinely mixed on two dimensions and should not be read as a sweep. PostgreSQL
full-text search favours HTML clearly and measurably (Section 6), and export favours HTML (Section
5). Authoring experience and CSP are neutral. The decision rests on three things, in priority order:

1. **It removes a vulnerability class rather than mitigating one, which is what AGENTS.md's security
   mandate asks for.** AGENTS.md makes OWASP Top 10 avoidance mandatory and states that the platform
   processes internal, sensitive, and potentially personal data. Under HTML storage, TrainDrain's
   protection against stored XSS in learner-facing content *is* the correctness of one dependency's
   HTML parser on every write, forever. Ammonia is a good bet for that job — browser-identical
   `html5ever` parsing, a conservative default allowlist with no `svg`/`math`/`script`/`style`,
   `noopener noreferrer` by default, no `javascript:`/`data:` in the default scheme list, and a
   three-release-line backport within a day of the July 2026 advisory. But it has still shipped three
   mXSS/attribute-filtering advisories since 2025, and its predecessor in this role, `bleach`, has
   ten advisories and a maintainer statement that no further security releases will ever come. Under
   JSON, that class of bug has nowhere to occur: no HTML string is stored, and `renderToReactElement`
   means `dangerouslySetInnerHTML` never appears in the learner render path. The residual risk
   shrinks to `href`/`src` scheme validation — a dozen lines of code you own and can unit-test, not a
   dependency you must trust.
2. **It is the only format the Claude API can guarantee the shape of, which Release 4 depends on.**
   AI-authored modules must save into the Release 1 schema. Structured outputs and strict tool use
   constrain sampling to schema-valid output; HTML has no such mechanism, and its failure mode under
   generation is the sanitizer quietly rewriting the model's output rather than the system rejecting
   it. Deciding this in Release 1 costs nothing; deciding it wrong means Release 4 either migrates
   every stored module or builds an HTML-to-JSON conversion layer under deadline.
3. **It is the format Tiptap will not silently corrupt.** Tiptap guarantees 100%-accurate content
   checking on JSON and explicitly declines to guarantee it on HTML, where "marks can be missed in
   certain situations." On a compliance-training platform, a Content Manager opening a page and
   losing formatting on save is a defect against the record itself.

The honest cost of this recommendation is Section 6: the JSONB tree cannot be indexed directly
without polluting the index, so a derived plain-text column is not optional — and Section 5's extra
import/export hop. If the team weights Release-1 delivery speed and search simplicity above the
security and Release-4 arguments, sanitized HTML via `nh3` on ammonia's **default** allowlist is a
legitimate, defensible choice; it is `bleach` that is not.

### Follow-on obligations this choice creates

**Schema and validation (backend, non-negotiable):**
- Define one explicit ProseMirror schema as the single source of truth, checked into the repo and
  carrying a `schemaVersion` integer stored on every document. Changing it requires a migration
  ticket, because Tiptap silently drops content outside the schema.
- Validate every incoming document **server-side** against that schema with `prosemirror-py`
  (BSD-3-Clause, pure Python, lxml-backed —
  [github.com/fellowapp/prosemirror-py](https://github.com/fellowapp/prosemirror-py)). Reject with
  422 on failure; never "sanitize and accept." Client-side editor configuration is UX, not a control.
- Enforce a per-node attribute allowlist server-side, and validate URL-bearing attributes explicitly:
  link `href` restricted to `https:` and `mailto:` (plus site-relative paths); image `src` restricted
  to `https:` and the platform's own asset paths; reject `javascript:`, `data:`, and `vbscript:` and
  anything not in the allowlist. Do not rely on Tiptap's `protocols`/`isAllowedUri` — its docs make
  no security claim for them.
- Reject unbounded documents: cap node count, nesting depth, and total serialized size at ingest.

**Rendering (frontend):**
- Render exclusively via `renderToReactElement` from `@tiptap/static-renderer/pm/react` (MIT).
- Add an ESLint rule banning `dangerouslySetInnerHTML` across `src/frontend`, so the guarantee is
  enforced by CI rather than by convention.
- Ship a strict Content-Security-Policy with no `'unsafe-inline'` in `script-src`, and lock down
  `img-src`, `style-src`, and `connect-src` to the platform's own origins as defense-in-depth
  (Section 2: a strict `script-src` alone does not stop exfiltration via `<img src>`).

**Search (backend + migration):**
- Add `search_text text` to the page table, populated on write by walking the node tree and
  concatenating `text` nodes (do **not** use `jsonb_to_tsvector` on the raw tree).
- Add `search_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(search_text,''))) STORED`
  plus a GIN index, per PostgreSQL's recommended pattern. Plan a second configuration for German
  content (`to_tsvector('german', ...)`) given AGENTS.md's bilingual requirement — the language
  choice is per-module and must be stored, not inferred at query time.

**Import (Release 1 scope):**
- Markdown import: `markdown-it-py` configured with the `js-default` preset (raw HTML disabled), per
  its own security guidance — then to a node tree. Never enable CommonMark's raw-HTML passthrough.
- HTML import: sanitize with `nh3` (MIT; keep it as a dependency for this path only) on the
  **default** allowlist — explicitly never adding `svg`, `math`, `style`, `script`, `iframe`,
  `textarea`, or `title`, which is the precondition for both recent ammonia mXSS advisories — then
  parse to a node tree via `prosemirror-py`'s `from_html()`. Treat import as lossy by design and
  report to the importing user what was dropped.
- Do **not** budget on Tiptap Conversion: it is a Pro package requiring a subscription and the
  private NPM registry. Free StarterKit + `prosemirror-markdown` (MIT) covers Release 1.

**AI authoring (Release 4 prerequisite, decide now, build later):**
- Define the AI-generation schema as a **depth-unrolled, non-recursive** JSON Schema (recursion is
  unsupported by structured outputs) that maps 1:1 onto a documented subset of the editor schema, and
  keep the two in sync with a test that round-trips every generated shape through server-side
  validation.
- Use `output_config.format` (or `strict: true` tool use) so generation is grammar-constrained, and
  still run the same server-side validator on the result — the constraint guarantees schema validity,
  not that `href` values are safe.

**Dependency monitoring:**
- ProseMirror's GitHub repositories are archived and development moved to `code.haverbeke.berlin`;
  point dependency and advisory monitoring at the npm packages, not at GitHub, or upstream security
  fixes will go unnoticed.
- Track `nh3`/`ammonia` advisories via RustSec as well as PyPI, since the vulnerability record lives
  on the Rust side.

---

## References

**Sanitizers and advisories**
- Bleach — GitHub repo (unmaintained notice): https://github.com/mozilla/bleach
- Bleach — PyPI (version 6.4.0, 2026-06-05): https://pypi.org/project/bleach/
- GitHub Security Advisories — bleach: https://github.com/advisories?query=bleach
- GHSA-gj48-438w-jh9v — bleach `formaction` URI scheme bypass: https://github.com/advisories/GHSA-gj48-438w-jh9v
- GHSA-8rfp-98v4-mmr6 — bleach URI scheme bypass via Unicode > U+00A0: https://github.com/advisories/GHSA-8rfp-98v4-mmr6
- Ammonia — GitHub repo/README: https://github.com/rust-ammonia/ammonia
- Ammonia — `Builder` defaults (tags, URL schemes, `link_rel`, `url_relative`): https://docs.rs/ammonia/latest/ammonia/struct.Builder.html
- Ammonia — crates.io API (4.1.4 / 4.0.3 / 3.3.3, all 2026-07-22; MIT OR Apache-2.0): https://crates.io/api/v1/crates/ammonia
- RustSec — ammonia advisory list: https://rustsec.org/packages/ammonia.html
- RUSTSEC-2026-0213 — SVG `animate`/`set` XSS (defaults unaffected): https://rustsec.org/advisories/RUSTSEC-2026-0213.html
- RUSTSEC-2025-0071 — SVG/MathML mutation XSS (defaults unaffected): https://rustsec.org/advisories/RUSTSEC-2025-0071.html
- nh3 — GitHub repo/README: https://github.com/messense/nh3
- nh3 — PyPI (0.3.7, 2026-08-23, MIT): https://pypi.org/project/nh3/
- nh3 — `Cargo.toml` (`ammonia = "4.1.4"`): https://raw.githubusercontent.com/messense/nh3/main/Cargo.toml
- nh3 — `src/lib.rs` (defaults derived from `ammonia::Builder::default()`): https://raw.githubusercontent.com/messense/nh3/main/src/lib.rs
- nh3 — API docs (`clean()` parameters/defaults): https://nh3.readthedocs.io/en/latest/
- DOMPurify — GitHub repo (client-side comparison; Apache-2.0 / MPL-2.0, jsdom required in Node): https://github.com/cure53/DOMPurify
- OWASP — Cross Site Scripting Prevention Cheat Sheet (WYSIWYG guidance): https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html

**Editor, document model, and rendering**
- ProseMirror — Guide (document model, schema, nesting): https://prosemirror.net/docs/guide/
- ProseMirror — Reference manual (`Node.check()`, `fromJSON`, `toJSON`): https://prosemirror.net/docs/ref/
- prosemirror-model — GitHub repo (archived 2026-04-01, moved to code.haverbeke.berlin; MIT): https://github.com/ProseMirror/prosemirror-model
- prosemirror-markdown — GitHub repo (bidirectional CommonMark; MIT; archived/moved): https://github.com/ProseMirror/prosemirror-markdown
- prosemirror-py — GitHub repo (Python port, `from_html()`, BSD-3-Clause): https://github.com/fellowapp/prosemirror-py
- Tiptap — GitHub repo/README (MIT; "Pro Extensions need a valid subscription"): https://github.com/ueberdosis/tiptap
- Tiptap — Schema ("very strict"; JSON vs HTML content checking): https://tiptap.dev/docs/editor/core-concepts/schema
- Tiptap — JSON and HTML output guidance: https://tiptap.dev/docs/guides/output-json-html
- Tiptap — StarterKit contents: https://tiptap.dev/docs/editor/extensions/functionality/starterkit
- Tiptap — Link extension options: https://tiptap.dev/docs/editor/extensions/marks/link
- Tiptap — HTML utility (`generateHTML`/`generateJSON`, virtual DOM): https://tiptap.dev/docs/editor/api/utilities/html
- Tiptap — Static renderer (`renderToReactElement`, no DOM/editor required): https://tiptap.dev/docs/editor/api/utilities/static-renderer
- Tiptap — Pro Extensions (account/subscription, private NPM registry): https://tiptap.dev/docs/guides/pro-extensions
- Tiptap — Conversion overview ("Conversion is a Pro package"): https://tiptap.dev/docs/conversion/getting-started/overview
- Tiptap — Pricing ("The Tiptap Editor is open source (MIT) and free"): https://tiptap.dev/pricing
- `@tiptap/static-renderer` — npm registry metadata (3.31.3, MIT): https://registry.npmjs.org/@tiptap/static-renderer/latest
- React — Common components (`dangerouslySetInnerHTML` warning): https://react.dev/reference/react-dom/components/common
- MDN — Content Security Policy (inline scripts, event handlers, `javascript:` URLs): https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CSP

**AI generation**
- Anthropic — Structured outputs (`output_config.format`, supported/unsupported JSON Schema keywords, no recursive schemas): https://platform.claude.com/docs/en/build-with-claude/structured-outputs
- Anthropic — Strict tool use (grammar-constrained sampling, guarantees): https://platform.claude.com/docs/en/agents-and-tools/tool-use/strict-tool-use

**Markdown / import**
- markdown-it-py — Security (CommonMark default allows arbitrary HTML; `js-default` preset): https://markdown-it-py.readthedocs.io/en/latest/security.html
- CommonMark Spec 0.31.2 (raw HTML passed through unescaped): https://spec.commonmark.org/0.31.2/

**PostgreSQL full-text search**
- PostgreSQL — Text Search Functions and Operators (`to_tsvector`, `jsonb_to_tsvector`, `filter`): https://www.postgresql.org/docs/current/functions-textsearch.html
- PostgreSQL — Parsers (token types incl. `tag`): https://www.postgresql.org/docs/current/textsearch-parsers.html
- PostgreSQL — Configuration Example: https://www.postgresql.org/docs/current/textsearch-configuration.html
- PostgreSQL — Tables and Indexes (generated `tsvector` column + GIN index): https://www.postgresql.org/docs/current/textsearch-tables.html
- *Measured, not cited:* `\dF+ english` and the two `to_tsvector`/`jsonb_to_tsvector` queries in
  Section 6 were run against `postgres:16-alpine` (PostgreSQL 16.11) in a throwaway container, because
  the PostgreSQL documentation does not publish the `english` configuration's full token-type mapping.
</content>
</invoke>
