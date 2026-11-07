# Smarthack

Repository: https://github.com/Glosperx/Smarthack.git (default branch `main`).

## Branches

- `main`: closed. Only receives releases, merged from `dev` through a pull request.
- `dev`: the integration branch, protected. It is merged into only through a pull request
  with one approval and green CI (`lint`, `test`, `docs`, `docker`).
- Work happens on `feature/<short-name>` or `fix/<short-name>`, branched from `dev`. When
  suggesting a branch name or a pull request, the target is `dev`, never `main`.
- The protection rules are GitHub settings, set by the owner in the web UI. They are not
  in the repository, and Claude does not change them.

## Git: the owner runs it, Claude does not

The repository owner runs every git command that changes state, always: staging,
commits, pushes, branches, merges, rebases, tags, remotes, and pull/merge requests.

- **Never** run `git add`, `commit`, `push`, `pull`, `fetch`, `merge`, `rebase`, `cherry-pick`,
  `checkout`/`switch`, `branch`, `tag`, `remote`, `reset`, `restore`, `stash`, `init`, or `gh pr` /
  `gh repo` / any command that opens, edits or merges a pull request, even when a task seems
  to end with "and commit it".
- Read-only inspection is fine: `git status`, `git diff`, `git log`, `git show`, `git blame`.
- When work is ready, say so and **suggest** what the owner would run: a branch name, the
  commit message and the push command. Do not execute them.
- Commit messages are short, a few words describing what was done. No body, no bullet
  list, and no `Co-Authored-By` or other Claude/Anthropic attribution.
- Do not add the remote, create the GitHub repository, or change its settings.

## Before saying a change is done

Run `make lint` and `make test`; both must pass. See `docs/contributing.md` for the
definition of done and `docs/architecture.md` for where new code goes.

## Full-Stack & Hackathon Conventions

- **Layering ranks:** `config/constants/utils (0)` -> `schemas (1)` -> `clients (2)` -> `services (3)` -> `api (4)` -> `__main__ (5)`. Imports must only point downward.
- **Routes stay thin:** Parse request, call client/service, return schema. If >20 lines, extract into `services/`.
- **Environment:** Only `smarthack/config.py` touches `os.environ`. Document every variable in `.env.example`.
- **API Contract:** TypeScript types are generated from FastAPI OpenAPI. Run `make types` whenever a Pydantic model or route changes, and commit `openapi.json` + `frontend/src/types/api.ts`.
- **Frontend styling:** Tailwind CSS utility classes only; avoid custom CSS files. Keep `src/index.css` to `@import "tailwindcss";`.

