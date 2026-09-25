# InsightXpert Web — UI / A11y Fixes PRD

Target repo: `projects/insightxpert.in` — app: `apps/web` (Next.js 16, live at `https://insightxpert.in`, API rewrite to `https://api.insightxpert.in` in `apps/web/vercel.json`).
Source of findings: Playwright CLI `1.63.0` / `playwright cli --browser chromium` — `open`, `snapshot`, `fill`, `click`, `eval`, `console`, `requests`, `screenshot`. Logged in as `admin@insightxpert.in`. Screenshots in `/tmp/opencode/insight-*.png`.

## Scope
In scope: `apps/web/src/app/login`, `register`, `layout`, `components/layout/header.tsx`, `left-sidebar.tsx`, `app-shell.tsx`, `docs-dialog.tsx`, `components/sidebar/conversation-item.tsx`, `conversation-list.tsx`, `components/chat/*`, `components/sample-questions/*`, `components/sql/*`, `components/ui/dialog.tsx`, `button.tsx`.
Out of scope: backend, LLM quality, public marketing page, old app `projects/insightxpert/frontend` (rewrites to `old.insightxpert.in`).

## Issue inventory (all verified)

### Auth
- AUTH-01 — No `h1` on login/register. `apps/web/src/app/login/page.tsx:69-74` uses `CardTitle` (div) + `CardDescription`; Playwright `eval` showed `h1:0`. Same on register.
- AUTH-02 — Show-password toggle not keyboard reachable. `apps/web/src/app/login/page.tsx:104-116`, `tabIndex={-1}`.
- AUTH-03 — Single global title. `apps/web/src/app/layout.tsx:25-28` `title: "InsightXpert - AI Data Analyst"` for all routes.
- AUTH-04 — Primary button ~`334x36`. Below 44px touch guideline. Verify in `components/ui/button.tsx`.

### Chat history / sidebar (P0)
- A11Y-01 — Overflow menu trigger has no name. `apps/web/src/components/sidebar/conversation-item.tsx:128-139`: `button.size-7` with only `<MoreHorizontal/>`, no `aria-label`. Playwright: `buttons:101, buttonsNoName:74`, `focusable:174`.
- A11Y-02 — Rename confirm/cancel only `title`. Same file `:75-90` (`title="Confirm"/"Cancel"`, no `aria-label`).
- A11Y-03 — Nested interactive. Same file `:96-108` `div role="button" tabIndex=0` wraps `DropdownMenu` trigger button `:126-140`. Enter/Space + click both fire, SR confusing.
- A11Y-04 — Hover-only reveal. Same file `:131-133` `opacity-0 group-hover:opacity-100`. Touch/keyboard users can't discover; `focus-visible:opacity-100` exists but trigger itself is unnamed (see A11Y-01).
- PERF-01 — Full list rendered. `apps/web/src/components/sidebar/conversation-list.tsx:71-90` maps all `conversations`; no virtualization despite `@tanstack/react-virtual` in `apps/web/package.json:21`. Causes 174 tab stops.
- CONTRAST-01 — Timestamp `text-[10px] text-muted-foreground/50`. Same file `:115-123`. 10px + 50% muted almost certainly fails WCAG 1.4.3.

### Dialogs
- DIALOG-01 — `console` warning (repro): `Missing Description or aria-describedby={undefined} for DialogContent`. `components/layout/docs-dialog.tsx:119-121` already has `DialogDescription sr-only`, so warning comes from another `DialogContent` without description (audit `sample-questions-modal`, `insight-all-modal`, `notification-*-modal`, `share-dialog`, `connect-db-*`). Base: `components/ui/dialog.tsx:47-76`.

### Touch targets / mobile
- TOUCH-01 — Small controls: `More options 28x28`, `Auto 85x22`, `DeepSeek V4 Flash 146x24`, voice/send `32x32` (Playwright `eval` on `main button`). Code: `components/layout/header.tsx:39-48,65-74` (`size-9` = 36px ok, but sidebar `size-7` = 28px in `left-sidebar.tsx:88-111`), chat toolbar.
- MOBILE-01 — Sidebar is `w-full md:w-[308px]` (`left-sidebar.tsx:80`). Mobile open state, overlay vs push, focus trap, close-on-navigate need explicit spec. `app-shell.tsx:115-128` already does full-screen sheet for SQL on mobile — apply same rigor to left sidebar.

### What is already good (don't regress)
Landmarks `header/aside/main`, `h1 InsightXpert` on main, `textbox "Ask anything..."`, send disabled-until-text, DB cards `169x49` with `pressed` state, empty states (`No insights yet`, `No new notifications`), `menu/menuitem` for DB switcher, docs dialog `Escape` close + `aria-hidden` bg, 0 console errors, APIs all 200.

---

## Phase 1 — P0 a11y blockers
### Status: DONE (2026-09-25, verified)
Changes made in `apps/web/src`:
1. `components/sidebar/conversation-item.tsx` — overflow trigger now `aria-label="Conversation actions for {title}"`, visible on touch (`opacity-100 lg:opacity-0 lg:group-hover...`) + `focus-visible` ring; rename Confirm/Cancel gained `aria-label`s; row refactored from `div role=button` (nested interactive) to plain `div` + inner `button aria-label="Open conversation: {title}"` with `aria-current`; timestamp `text-[10px] text-muted-foreground/50` → `text-xs text-muted-foreground`.
2. `app/login/page.tsx`, `app/register/page.tsx` — removed `tabIndex={-1}` from show-password toggle (now tabbable, verified `tabIndex:0` via Playwright); added `focus-visible` ring.
3. Dialogs — added missing `DialogDescription` (sr-only): `components/sample-questions/sample-questions-modal.tsx` ("Browse and search..."), `components/dataset/dataset-viewer.tsx` ("Preview dataset rows..."), `components/admin/visibility-menu.tsx` ("Choose who can see..."). Sweep: no `DialogContent` without a description remains.
4. Bonus (same pattern): copy button in `sample-questions-modal.tsx` gained `aria-label="Copy question: ..."` + touch-visible opacity.
Verification: `tsc --noEmit` clean; eslint no new issues (2 pre-existing errors unchanged); `vitest` 23/23 incl. new `conversation-item.phase1.test.tsx` (3 tests: named select button, named menu trigger, timestamp classes); Playwright CLI vs local dev (`next dev -p 3001`, prod API proxy): login page `showPwd.tabIndex:0`, `div[role=button]:0`, `text-[10px]:0`. Full authenticated flow not re-runnable locally over http (prod `Secure` cookie → `/me` 401); covered by component tests + static sweeps instead. Live prod re-check deferred to deploy preview.
Goal: keyboard + SR users can use history and dialogs with 0 errors.

1. Add `aria-label="Conversation actions for {title}"` (or `More actions`) to trigger in `conversation-item.tsx:128-139`; ensure `focus-visible:opacity-100` + also show on `focus-within`. Remove pure hover dependency for touch (always show on `md:`? or keep visible on touch via `opacity-100 lg:opacity-0`).
2. `aria-label="Confirm rename"` / `"Cancel rename"` in `conversation-item.tsx:75-90` (keep `title` as tooltip only).
3. Fix nested interactive: change outer `div role=button` (`:96-108`) to non-interactive container with single select button, or keep row click but set `aria-haspopup` correctly and stop propagation; at minimum ensure inner trigger has name (fixes most SR confusion) and row responds to Enter only when focus is on row, not on inner button.
4. `tabIndex={-1}` → remove on login show-password (`login/page.tsx:108`); ensure visible focus ring. Apply same to register.
5. Audit all `DialogContent` usages; add `DialogDescription` (sr-only ok) everywhere. Fix `dialog.tsx` if `aria-describedby` isn't forwarded.
6. Bump timestamp to `text-xs` + `text-muted-foreground` (remove `/50`) in `conversation-item.tsx:115`.

Acceptance (run in `apps/web`):
```bash
npx playwright cli -s=v open --browser chromium https://insightxpert.in
# login via fill/click, then:
npx playwright cli -s=v snapshot
npx playwright cli -s=v eval "() => ({noName: [...document.querySelectorAll('button')].filter(b=>!(b.textContent.trim()||b.getAttribute('aria-label'))).length, focusable: document.querySelectorAll('a[href],button:not([disabled]),input,select,textarea,[tabindex]:not([tabindex=\"-1\"])').length})"
npx playwright cli -s=v console
```
Pass: `noName=0` on history rows, show-password tabbable, `console Errors:0`, no DialogContent warning.

## Phase 2 — Perf + mobile usability
Goal: history scales, touch targets sane, mobile nav predictable.

1. Virtualize `ConversationList` (`conversation-list.tsx:71-90`) with existing `@tanstack/react-virtual`; keep Today/Older groups as sticky headers; fallback to pagination (e.g. 50 + "Show more") if virtualization conflicts with grouping. Add `aria-setsize/posinset` or listbox semantics if trivial.
2. Cap initial tab stops: rows themselves should be single-tab-stop (`tabIndex 0` on row OR on title button, not both + menu). Target `<40` focusables on load with 100+ convos.
3. Touch: raise icon buttons to min `36-40px` (`size-9/size-10`) in `left-sidebar.tsx`, chat toolbar, header; keep `24px` WCAG AA minimum as hard floor with adequate spacing. DB cards already fine.
4. Mobile sidebar spec in `app-shell.tsx` + `left-sidebar.tsx`: overlay sheet, focus trap, `Escape` close, close on select, hamburger `aria-expanded` (already in `header.tsx:44-45` — wire to animation).
5. Keep search (`left-sidebar.tsx:36-77`, min 2 chars, 300ms debounce) working with virtualization.

Acceptance: with admin seed (100+ convos), `focusable` drops by >70%, scroll stays smooth, `390x844` resize keeps composer `~340px` visible and sidebar doesn't trap main.

## Phase 3 — Polish / SEO
1. Add real `h1` (sr-only ok) to login/register; keep visual `CardTitle`.
2. `layout.tsx:25-28` → `title: { template: "%s — InsightXpert", default: "InsightXpert - AI Data Analyst" }`; set per-page `metadata.title` (`Sign in`, `Create account`, chat DB name).
3. Ensure `:focus-visible` rings on all custom buttons (especially `size-7` icon buttons and DB cards).
4. Contrast pass on `muted-foreground` small text; verify with `eval` computed styles.
5. Add skip link (`Skip to chat`) to `app-shell.tsx`.
6. Optional: `autocomplete` already correct on login (`email`, `current-password` at `login/page.tsx:85,98`) — mirror on register (`new-password`).

---

## Test plan for implementing agent
- `npm run typecheck && npm run lint` in `apps/web`.
- `npm run test` (vitest) + relevant `playwright test` in `apps/web/e2e`.
- Manual Playwright CLI script above for a11y counts + `screenshot` at `1440x900` and `390x844` before/after.
- No LLM send needed; use `fill` without submit for composer tests, clear after.
