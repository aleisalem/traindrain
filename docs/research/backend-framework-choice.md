# Backend Framework Choice for Release 0: FastAPI vs. Django + DRF

**Status:** Research complete, decision pending
**Scope:** TrainDrain Release 0 — email+password auth, opt-in per-user TOTP 2FA, three fixed roles
(Administrator, Content Manager, Learner), invite-based user creation, User Groups (basic CRUD),
and an admin shell UI for managing users/groups/roles. Deployment target: AWS `eu-central-1`,
simulated locally via LocalStack.
**Method:** Primary sources only (official framework/library docs and repos). Every claim below is
followed back to the page that states it; see inline citations and the References section.

---

## 1. Async/streaming support maturity

**FastAPI.** Async is native and optional at the same time. FastAPI explicitly supports mixing
`async def` and `def` path operations in the same app: a `def` handler is run in an external
threadpool and awaited, so it never blocks the event loop, while `async def` handlers run directly
on the loop. FastAPI's own guidance when unsure is "just use normal `def`," and it states the
framework "will still work asynchronously and be extremely fast" either way
([fastapi.tiangolo.com/async](https://fastapi.tiangolo.com/async/)). For streaming, FastAPI (via
Starlette) ships `StreamingResponse`, which takes a sync or async generator and streams the
response body — the exact shape needed for token-by-token LLM output. The docs do flag a real
caveat: an async generator without an internal `await` cannot be cancelled cleanly, so examples
insert `await anyio.sleep(0)` to yield control to the event loop, and the docs actually recommend
their newer "Stream Data" helper over raw `StreamingResponse` because it "handles cancellation
behind the scenes"
([fastapi.tiangolo.com/advanced/custom-response](https://fastapi.tiangolo.com/advanced/custom-response/)).
Underneath, if using SQLAlchemy 2.0's asyncio extension, SQLAlchemy's own docs are functional but
guarded: "a single instance of `AsyncSession` is not safe for use in multiple, concurrent tasks,"
and the docs devote substantial space to avoiding implicit I/O (lazy-loading) pitfalls
([docs.sqlalchemy.org/en/20/orm/extensions/asyncio](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)).
So FastAPI's async path is mature for HTTP/streaming, but the async ORM layer beneath it still asks
the developer to be careful.

**Django.** Django 4.1+/5.x supports `async def` views and ASGI deployment, and Django's own docs
are candid about the tradeoffs rather than declaring blanket production-readiness. Under WSGI,
"async views will still work... but with performance penalties, and without the ability to have
efficient long-running requests" — i.e., streaming/long-polling specifically requires ASGI
deployment. Async is also "only fully async" if there is no synchronous middleware in the stack;
otherwise Django "must use a thread per request to safely emulate a synchronous environment," and
mixing sync/async views under the "wrong" server type costs "around a millisecond" per
context-switch ([docs.djangoproject.com/en/5.2/topics/async](https://docs.djangoproject.com/en/5.2/topics/async/)).
The ORM's async story is the most load-bearing caveat for this decision: Django states outright
"we're still working on async support for the ORM and other parts of Django. You can expect to see
this in future releases." Blocking QuerySet methods get `a`-prefixed async twins (`aget`,
`acreate`, `async for` iteration), but **methods that return new querysets (e.g. `filter()`) have
no async twin at all** — there is no `afilter()`; you call the sync `filter()` (non-blocking,
lazy) and only await the terminal method
([docs.djangoproject.com/en/5.2/topics/db/queries](https://docs.djangoproject.com/en/5.2/topics/db/queries/)).
Most consequentially, **transactions do not work in async mode** — Django's docs say attempting
one under `async def` raises `SynchronousOnlyOperation`, and recommend wrapping transactional code
in a sync function called via `sync_to_async()`
([docs.djangoproject.com/en/5.2/topics/db/queries](https://docs.djangoproject.com/en/5.2/topics/db/queries/),
[docs.djangoproject.com/en/5.2/topics/async](https://docs.djangoproject.com/en/5.2/topics/async/)).

**Tradeoff.** For Release 0's CRUD-and-forms surface (auth, users, groups, roles), this gap barely
matters — none of that needs streaming or high concurrency, and Django's sync views/ORM are exactly
as mature as always. It matters for the *next* release's streaming LLM chat: FastAPI's
`StreamingResponse`/async generator path is a first-class, well-trodden pattern; doing the
equivalent in Django means an ASGI deployment, avoiding sync middleware, and likely wrapping any
transactional DB writes around the stream in `sync_to_async()` — doable, but visibly more caveated
in Django's own docs than in FastAPI's.

## 2. Built-in admin panel

**Django admin** is a genuinely large amount of "admin shell UI" for zero bespoke frontend code.
Registering a model gives list views with pagination, add/edit forms generated from the model,
delete confirmation, search, and filtering, all enforcing the permission system automatically
(`is_staff` gate, plus per-model `view`/`add`/`change`/`delete` checks via `has_*_permission()`
hooks) ([docs.djangoproject.com/en/5.2/ref/contrib/admin](https://docs.djangoproject.com/en/5.2/ref/contrib/admin/)).
Because `django.contrib.auth`'s `User`, `Group`, and `Permission` models are ordinary Django
models, they are manageable through this same admin with no extra code — literally covering "admin
UI for managing users and role/group membership" out of the box. Django's own docs are explicit
about the intended ceiling, though: "the admin's recommended use is limited to an organization's
internal management tool. It's not intended for building your entire front end around," and warn
against over-relying on its hooks for a "process-centric interface"
([docs.djangoproject.com/en/5.2/ref/contrib/admin](https://docs.djangoproject.com/en/5.2/ref/contrib/admin/)).
For TrainDrain, whose AGENTS.md calls for an "interactive, modern, and responsive" UI with
dark/light/colorblind themes and German/English localization, the stock Django admin's own visual
shell is not that UI — it would most likely serve as an internal fallback/ops tool while the
customer-facing admin shell is still a bespoke TypeScript frontend calling the API, same as under
FastAPI.

**FastAPI has no admin equivalent at all.** There is no first-party admin app; a team either builds
the admin shell entirely in the TypeScript frontend against API endpoints, or adopts a third-party
package. Two candidates, checked against their own repos:
- **SQLAdmin** — "a flexible Admin interface for SQLAlchemy models," integrating with Starlette and
  FastAPI, supporting sync/async engines, WTForms-based forms, SQLModel, and optional
  authentication via `itsdangerous` as an add-on rather than default
  ([github.com/aminalaee/sqladmin](https://github.com/aminalaee/sqladmin)). It has meaningful
  adoption (2.8k stars, active issues/PRs) but its own README makes no claim of parity with Django
  admin, and auth/permissions are opt-in extras rather than an integrated permission model.
- **fastapi-admin** — an older, similarly-scoped Tortoise-ORM-oriented admin package
  (~3.8k stars, 63 open issues at time of research); its README did not surface an explicit
  maintenance statement or recent release timestamp in this pass, which is itself a signal to
  verify freshness before depending on it ([github.com/fastapi-admin/fastapi-admin](https://github.com/fastapi-admin/fastapi-admin)).

**Tradeoff.** This is the dimension where the two frameworks diverge most sharply for Release 0's
literal requirements. Django gets "manage Users/Groups/role membership through an admin UI" close
to free, using models that already exist in `django.contrib.auth`. FastAPI has nothing analogous in
the core framework, and the closest third-party options (SQLAdmin, fastapi-admin) are real but
smaller-scope projects that would need bespoke wiring for permissions/roles and would not, by
themselves, replace the "interactive, modern, responsive, themeable, bilingual" admin UI AGENTS.md
calls for regardless of framework — meaning under *either* framework, the customer-facing admin
shell is realistically a custom TypeScript frontend against the API, and Django admin's value here
is mainly as an internal-only safety-net UI, not the delivered product surface.

## 3. Auth/RBAC ecosystem for a custom, evolving permission model

**Django's built-in model** is `User` + `Group` + `Permission`, where `django.contrib.auth`
auto-creates four permissions per model (`add`, `change`, `delete`, `view`), permissions can be
attached to a `User` directly or via `Group` membership, and "a user in a group automatically has
the permissions granted to that group"
([docs.djangoproject.com/en/5.2/topics/auth/default](https://docs.djangoproject.com/en/5.2/topics/auth/default/)).
This is exactly where TrainDrain's domain model creates friction rather than fit: **TrainDrain's
"Groups" are organizational/targeting units** (who a campaign or module is assigned to), while
**"Roles" are the permission-bearing construct** (Administrator, Content Manager, Learner). Django's
`Group` model is *itself* the permission-bearing construct — a Django `Group` is really "a role,"
not a targeting cohort. Reusing Django's `Group` model for TrainDrain's groups would conflate two
distinct domain concepts the project has deliberately kept separate; reusing it for TrainDrain's
Roles is a closer fit conceptually but still caps out at the four generic per-model permissions
unless custom `Permission` rows are created explicitly via `Meta.permissions` or
`Permission.objects.create()`, which the docs describe as a manual, code-level exercise, not a
runtime-configurable one
([docs.djangoproject.com/en/5.2/topics/auth/default](https://docs.djangoproject.com/en/5.2/topics/auth/default/)).
Given Release 0 ships only three *fixed* roles (not yet the eventual admin-authored custom
permission matrix), this manual-definition property is a wash for Release 0 but a known future
cost: Django's auth app was not designed for a fully dynamic, admin-editable permission matrix, and
teams that build one on top of it typically end up bypassing `Group`/`Permission` semantics rather
than growing them.

**FastAPI has no built-in auth or RBAC concept at all.** The de facto library, **fastapi-users**,
provides a pluggable base user model, ready-made register/login/reset-password/verify-email routes,
OAuth2 social login, JWT/database/Redis session strategies, and async SQLAlchemy or Beanie (MongoDB)
adapters ([github.com/fastapi-users/fastapi-users](https://github.com/fastapi-users/fastapi-users)).
Its maintenance status must be weighed honestly: the README states plainly, **"This project is now
in maintenance mode. While we'll continue to provide security updates and dependency maintenance,
no new features will be added,"** and the maintainers say they are building a successor toolkit
that will "ultimately supersede" it
([github.com/fastapi-users/fastapi-users](https://github.com/fastapi-users/fastapi-users)). It is
still active enough to ship releases (v15.0.5, March 2026 per PyPI) and has low open-issue count (4)
relative to its size (6.2k stars), so it is not abandoned — but adopting it for Release 0 means
building on a library that has explicitly frozen its feature surface. Because fastapi-users has no
opinion on Groups/Roles beyond a single `is_superuser` boolean and whatever custom fields are added
to the user model, TrainDrain's Role/Group split would be modeled entirely from scratch either way —
custom tables plus custom dependency-injected permission checks (FastAPI's `Depends()` mechanism),
which is more upfront work but exactly matches TrainDrain's actual domain rather than requiring a
reinterpretation of Django's Group/Permission semantics.

**Tradeoff.** Django's auth app is more "free" machinery, but that machinery encodes assumptions
(Groups-as-roles, four generic per-model permissions) that don't cleanly map onto TrainDrain's
explicit Role-vs-Group split, meaning some of that free functionality would need to be worked around
or ignored rather than used as-is. FastAPI requires building Roles, Groups, and role-permission
checks from nothing (or on top of a maintenance-mode library for the user/session plumbing only),
but the resulting model maps directly onto TrainDrain's actual domain language with no impedance
mismatch, and nothing needs to be un-learned when Release 0's fixed roles later grow into an
admin-authored permission matrix.

## 4. OpenAPI/schema generation for future scoped API tokens

**FastAPI** generates the OpenAPI schema automatically from Python type hints with no separate
documentation step: "FastAPI generates a schema with all your API using the OpenAPI standard,"
exposed automatically at `/openapi.json`, with Swagger UI (`/docs`) and ReDoc (`/redoc`) served out
of the box from the same schema, from a bare route definition with zero extra annotation
([fastapi.tiangolo.com/tutorial/first-steps](https://fastapi.tiangolo.com/tutorial/first-steps/)).

**DRF's own built-in schema generation is deprecated by DRF itself**: "REST framework's built-in
support for generating OpenAPI schemas is deprecated in favor of 3rd party packages," with DRF's
docs explicitly recommending **drf-spectacular** as "a full-fledged replacement... [with] extensive
support for generating OpenAPI 3 schemas from REST framework APIs"
([www.django-rest-framework.org/api-guide/schemas](https://www.django-rest-framework.org/api-guide/schemas/)).
drf-spectacular's own docs describe a pragmatic, mostly-automatic-but-not-fully-automatic design: it
aims to "extract as much schema information from DRF as possible" with "sane fallbacks" from
serializers/views/viewsets, but documents concrete cases needing the `@extend_schema` /
`@extend_schema_field` decorators — `SerializerMethodField` typing, non-standard response
status codes, polymorphic responses (`PolymorphicProxySerializer`), and custom filter parameters
([drf-spectacular.readthedocs.io/en/latest/readme](https://drf-spectacular.readthedocs.io/en/latest/readme.html)).

**Tradeoff.** Both land in a similar place operationally — a real OpenAPI 3 schema good enough to
drive docs and generate a client for scoped API tokens — but FastAPI's is inherent to the framework
(schema comes from the same type hints that give you request validation), whereas DRF's requires
adding, configuring, and periodically hand-annotating a separate third-party package. This is a
genuine, if modest, integration-tax difference in FastAPI's favor for the "scoped API tokens usable
independently of the frontend" requirement, since that feature is explicitly schema/docs-driven.

## 5. AWS deployment shape and LocalStack fit

Both frameworks are deployable to `eu-central-1` as long-running containers on ECS/Fargate without
any framework-specific obstacle — this is standard WSGI/ASGI-behind-a-container deployment either
way, and LocalStack's own docs list ECS, Fargate, Lambda, API Gateway, and Cognito all as supported
services with no framework-differentiated guidance
([docs.localstack.cloud/aws/services](https://docs.localstack.cloud/aws/services/)). At that level
the finding is genuinely neutral, as anticipated.

One concrete, framework-adjacent asymmetry did turn up for a **Lambda-based** deployment path, which
matters specifically because of Release 0→later-release streaming plans: FastAPI can run on Lambda
via **Mangum**, an ASGI adapter supporting "Function URL, API Gateway, ALB, and Lambda@Edge events"
across Starlette, FastAPI, Quart, and Django alike
([github.com/Kludex/mangum](https://github.com/Kludex/mangum)) — so Mangum is not even
FastAPI-exclusive; Django (via its own ASGI support) could use the same adapter. Its README shows
active-enough signs (29 open issues, 9 open PRs against 501 commits) without an explicit maintenance
statement either way. The real asymmetry is not framework-vs-framework, it's **container vs.
Lambda**: LocalStack's own Lambda documentation states plainly, **"Response streaming is currently
not supported [in LocalStack], so it will still return a synchronous/full response instead"**
([docs.localstack.cloud/aws/services/lambda](https://docs.localstack.cloud/aws/services/lambda/)).
That means if a future release's streaming LLM chat were deployed to real Lambda (which does support
response streaming natively), local testing against LocalStack's Lambda emulation would silently
fall back to buffered, non-streaming responses — a LocalStack fidelity gap, not a FastAPI/Django
gap. A container-based ECS/Fargate deployment sidesteps this entirely, since a long-running ASGI
server streams the same way locally (via `docker-compose`, per AGENTS.md's own testing requirement)
as it does in AWS.

**Tradeoff.** Neither framework has a deployment-shape advantage on AWS or under LocalStack for
Release 0's non-streaming CRUD scope. The one actionable finding is infrastructure-level, not
framework-level: given AGENTS.md already commits to LocalStack for local AWS simulation and
`docker-compose` for local runs, and given the roadmap includes streaming chat, **ECS/Fargate is the
safer target than Lambda for this project regardless of which framework is chosen**, specifically
because LocalStack cannot faithfully emulate Lambda response streaming today.

## 6. TOTP 2FA ecosystem

**django-otp** integrates directly with `django.contrib.auth` — "it integrates with
`django.contrib.auth`, although it is not a Django authentication backend" — and ships standard HOTP
and TOTP device implementations "as these are standard OTP algorithms used by multiple plugins"
([django-otp-official.readthedocs.io/en/stable](https://django-otp-official.readthedocs.io/en/stable/)).
Its own docs are candid about its current maintenance state: **"This project is stable and
maintained, but is no longer actively used by the author and is not seeing much ongoing
investment."** It is not abandoned — PyPI shows a release as recent as v1.7.0 (January 2026) — but
the "not seeing much ongoing investment" framing, from the maintainer directly, should factor into
risk assessment ([django-otp-official.readthedocs.io/en/stable](https://django-otp-official.readthedocs.io/en/stable/),
PyPI project page). Because it plugs into `django.contrib.auth`'s `User` model and Django's session
middleware conventions, adopting it under Django is largely configuration: add device models,
register a per-view/middleware verification step, done.

**pyotp** is a framework-agnostic, low-level library: "PyOTP is a Python library for generating and
verifying one-time passwords," implementing TOTP/HOTP generation and verification only
([pyauth.github.io/pyotp](https://pyauth.github.io/pyotp/)). It explicitly does not touch web
frameworks, QR codes, secret storage, or replay-attack prevention — its docs say the provisioning
URI "can then be rendered as a QR code" by the caller, that secrets must be kept confidential "by
storing secrets in a controlled access database" by the caller, and that replay-attack prevention
"requires storing the most recently authenticated timestamp" — again, by the caller
([pyauth.github.io/pyotp](https://pyauth.github.io/pyotp/)). Under FastAPI, adopting pyotp means
building: the secret-storage model/migration, the enrollment endpoint plus QR code rendering, the
verification endpoint, and replay-window tracking, all by hand (though this is a small, well-scoped
amount of code — perhaps a day or two of implementation plus tests).

**Tradeoff.** django-otp is lower integration-effort because it assumes and reuses
`django.contrib.auth`, at the cost of adopting a library whose own maintainer describes it as
low-investment (still receiving releases, but not actively evolving). pyotp is more manual work
under FastAPI — secret storage, enrollment/QR flow, verification, and replay protection all become
application code — but that code is small, framework-agnostic, fully within the team's control, and
carries no third-party-integration risk tied to an unmaintained web-framework glue layer. Given
Release 0 needs is "opt-in per-user TOTP," the FastAPI path's extra effort is bounded and one-time;
it is not a meaningfully higher-risk path, just a marginally higher-effort one.

---

## Summary table

| Dimension | FastAPI | Django + DRF | Edge |
|---|---|---|---|
| Async/streaming maturity | Native async, `StreamingResponse` well-trodden; async ORM (SQLAlchemy 2.0) needs care | Async views/ASGI work but Django's own docs flag ORM async as unfinished, no async transactions, sync-middleware and WSGI penalties | FastAPI, especially for future streaming chat |
| Built-in admin panel | None; SQLAdmin/fastapi-admin are smaller third-party projects, no built-in permission model | Full admin UI over `User`/`Group`/`Permission` essentially free | Django, but the value is mostly internal/ops-only given AGENTS.md's bespoke-UI requirement |
| Auth/RBAC fit for TrainDrain's Role-vs-Group split | No built-in auth; fastapi-users covers user/session plumbing (now in maintenance mode) but Roles/Groups modeled from scratch, cleanly matching TrainDrain's domain | Built-in `User`/`Group`/`Permission`, but Django's `Group` *is* a role-like construct, conflicting with TrainDrain's Groups-as-targeting-units concept | Mixed — Django gives more machinery, FastAPI gives a cleaner conceptual fit |
| OpenAPI generation for future scoped tokens | Automatic from type hints, built into the framework | DRF's own schema support is deprecated in favor of drf-spectacular, which is mostly-automatic but needs manual decorators for edge cases | FastAPI, modestly |
| AWS/LocalStack deployment shape | No framework-level difference on ECS/Fargate | No framework-level difference on ECS/Fargate | Neutral; ECS/Fargate preferred over Lambda for either framework, since LocalStack cannot emulate Lambda response streaming |
| TOTP 2FA ecosystem | pyotp: framework-agnostic primitives only, more manual work (storage, QR, verification, replay protection), low ongoing risk | django-otp: integrates with `django.contrib.auth` with little glue code, but maintainer describes it as low-investment | Django, lower effort; FastAPI, lower dependency risk |

## Recommendation

The evidence is genuinely mixed rather than a clean sweep, but it is not evenly mixed *for this
project's specific trajectory*. Release 0 itself (fixed roles, basic CRUD, invite-based users) is a
domain both frameworks handle comfortably, and Django's built-in admin/auth is the more "free"
option for that release in isolation. But three of the six dimensions point specifically toward
where TrainDrain is *going*, not just where it is now: streaming LLM chat (dimension 1) is
core to the product ("whatever means necessary" per AGENTS.md's app description), scoped API tokens
are an explicit later-release requirement (dimension 4), and TrainDrain's Role-vs-Group domain
split does not map cleanly onto Django's Group/Permission model (dimension 3) — a mismatch that
would need to be worked around now and would likely get more awkward, not less, as Release 0's fixed
roles evolve into the planned admin-authored custom permission matrix. Django admin's biggest
Release-0 advantage (dimension 2) is also weaker than it first appears once AGENTS.md's own
requirement for a bespoke, themeable, bilingual admin UI is taken into account — Django admin would
likely serve as an internal fallback, not the delivered product.

**On balance, FastAPI is the better fit for this project**, provided the team accepts doing more
Release 0 groundwork by hand: a from-scratch Role/Group/Permission model (which pays off precisely
because it will match TrainDrain's actual domain rather than fight Django's), a hand-built or
fastapi-users-backed auth/session layer (weighing that project's maintenance-mode status), pyotp
wired in manually for TOTP, and no built-in admin UI (already a bespoke build under AGENTS.md's UI
requirements regardless of framework). If the team instead weights Release 0 delivery speed above
the later-release streaming/API-token/permission-matrix trajectory, Django + DRF remains a
legitimate, well-supported choice — its admin and auth machinery are real, mature, and would
meaningfully accelerate Release 0 specifically, at the cost of the Role/Group modeling friction and
comparatively more caveated async/streaming story documented above.

---

## References

- FastAPI — Async: https://fastapi.tiangolo.com/async/
- FastAPI — Custom Response / StreamingResponse: https://fastapi.tiangolo.com/advanced/custom-response/
- FastAPI — First Steps (OpenAPI/docs): https://fastapi.tiangolo.com/tutorial/first-steps/
- Django — Asynchronous support: https://docs.djangoproject.com/en/5.2/topics/async/
- Django — Making queries (async ORM section): https://docs.djangoproject.com/en/5.2/topics/db/queries/
- Django — The admin site: https://docs.djangoproject.com/en/5.2/ref/contrib/admin/
- Django — Using the Django authentication system: https://docs.djangoproject.com/en/5.2/topics/auth/default/
- SQLAlchemy 2.0 — Asynchronous I/O (asyncio extension): https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
- Django REST Framework — Schemas: https://www.django-rest-framework.org/api-guide/schemas/
- Django REST Framework — home page: https://www.django-rest-framework.org/
- drf-spectacular — README/overview: https://drf-spectacular.readthedocs.io/en/latest/readme.html
- fastapi-users — GitHub repo/README: https://github.com/fastapi-users/fastapi-users
- fastapi-users — PyPI (version/release date): https://pypi.org/project/fastapi-users/
- SQLAdmin — GitHub repo/README: https://github.com/aminalaee/sqladmin
- fastapi-admin — GitHub repo: https://github.com/fastapi-admin/fastapi-admin
- Mangum — GitHub repo/README: https://github.com/Kludex/mangum
- django-otp — official docs: https://django-otp-official.readthedocs.io/en/stable/
- django-otp — PyPI (version/release date): https://pypi.org/project/django-otp/
- pyotp — official docs: https://pyauth.github.io/pyotp/
- LocalStack — supported AWS services: https://docs.localstack.cloud/aws/services/
- LocalStack — Lambda service docs (response streaming limitation): https://docs.localstack.cloud/aws/services/lambda/
