# Repository instructions

## Product boundaries

- Markdown/YAML and append-only audit events are authoritative.
- GTD, knowledge, managed project, publishing, User Story Mapping, and TBP are separate features.
- A GTD project is an outcome requiring multiple actions; it is not a managed project.
- Cross-feature relations use stable IDs and public contracts, never private model imports.
- Provider credentials and provider-specific sync state never enter ordinary document frontmatter unless
  explicitly part of the public mapping contract.

## Development workflow

- Branch hierarchy: `main` → `dev/<epic>` → `feat/<slice>`.
- Do not commit feature work directly to `main` or `dev/*`; merge tested `feat/*` branches with `--no-ff`.
- Use Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`).
- Update `TASK.md` in every material feature commit.
- Preserve user changes and never rewrite published history without explicit approval.

## TDD

1. Add a failing user-observable acceptance or domain test.
2. Add focused unit tests for invariants and errors.
3. Implement the smallest coherent public API.
4. Refactor only while green.
5. Run:

```bash
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/pytest
```

- Test public behavior; avoid tests that couple to private helper structure.
- Every state transition needs allowed, refused, audit-event, and persistence-reload coverage.
- Every direct-editable schema needs malformed, unknown-field, migration, and doctor coverage.

## API and function design

- CLI and HTTP are adapters; domain rules live in application services.
- Avoid `Any` at public boundaries when a Pydantic response model is possible.
- Commands must support unique ID prefixes for humans and full IDs for automation.
- `--json` mode must never prompt or mix human text into stdout.
- Errors must be stable, typed, and mapped consistently across CLI/API.
- Writes that enforce invariants must run under the workspace lock.

## Documentation

- User documentation: `docs/user/`.
- Developer documentation: `docs/development/`, `docs/architecture/`, `docs/specs/`, `docs/research/`.
- Root README is a short product entry point and links to both audiences.
- Mark facts, inferences, hypotheses, and unknowns explicitly in specifications.
