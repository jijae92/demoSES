# Repository Guidelines

## Project Structure & Module Organization
- `template.yaml` defines the AWS SAM stack (Lambda, EventBridge schedule, DynamoDB table, IAM).
- `src/` holds runtime code: `handler.py` orchestrates fetch-and-notify, `config.py` loads secrets, `dal.py` wraps DynamoDB, `mailer.py` sends SES/SMTP mail, `runtime.py` merges overrides, `pipeline/filtering.py` dedupes results, and `sources/` integrates Crossref, PubMed, and RSS.
- `tests/` hosts pytest suites for runtime merging and filtering logic; mirror new modules with `tests/test_<module>.py`.
- `event.json` and `event-wide.json` are sample payloads for local runs; tweak copies, not originals.

## Build, Test, and Development Commands
- `python -m pip install -r requirements.txt` in a virtualenv; add `pytest` for local checks.
- `sam build` compiles the Lambda bundle under `.aws-sam/` using the code in `src/` and dependencies in `vendor/`.
- `sam local invoke PaperWatcherFunction --event event.json` exercises the handler locally with stub secrets.
- `python -m pytest tests` runs the offline unit tests; add `-k` filters when iterating.
- `sam deploy --guided` walks through first-time deployment; reuse `samconfig.toml` afterward for repeatable deploys.

## Coding Style & Naming Conventions
- Target Python 3.11, 4-space indentation, and type hints for public APIs; prefer `@dataclass(slots=True)` when modeling config bundles like `RuntimeOptions`.
- Keep side-effects in integration modules (`handler.py`, `dal.py`, `mailer.py`); helpers should stay pure.
- Use `snake_case` for functions/variables, `PascalCase` for classes, and UPPER_SNAKE_CASE for constants and environment keys.
- Mirror existing docstrings and reserve inline comments for non-obvious logic.

## Testing Guidelines
- Add pytest cases in `tests/` using the `test_<area>.py` naming pattern.
- Mock AWS and HTTP clients via fixtures or monkeypatching as shown in `tests/test_runtime.py`.
- Cover dedupe logic and source adapters; run `python -m pytest --maxfail=1 --disable-warnings` before pushing and capture the output in PRs.

## Commit & Pull Request Guidelines
- Use concise, imperative commit subjects (optional `type:` prefixes such as `chore:` match history).
- Keep commits focused; ship template or config edits with the dependent code.
- PRs need a summary, linked tickets, verification commands (`sam build`, `python -m pytest`), and screenshots only for user-visible email changes.
- Call out secret or schema updates early in the PR body to alert operators.

## Security & Configuration Tips
- Keep secrets in AWS Secrets Manager; use `.env.example` as the local template and avoid committing overrides.
- Test SMTP or schedule tweaks via temporary copies of `event.json`, and review IAM or schedule diffs carefully—default to least privilege in `template.yaml`.
