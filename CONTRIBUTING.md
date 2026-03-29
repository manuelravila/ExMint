# Contributing to ExMint

Thanks for your interest in contributing. All contributions — bug reports, feature requests, documentation improvements, and code changes — are welcome.

---

## Before You Start

- Check [open issues](https://github.com/manuelravila/ExMint/issues) to see if your bug or feature is already being tracked.
- For significant changes (new features, architectural shifts), open an issue first to discuss the approach before writing code. This saves everyone time.
- All work happens on the `dev` branch. `stag` and `main` are promotion-only — never target them in a PR.

---

## Reporting Bugs

Use the **Bug Report** issue template. Include:

- ExMint version (bottom of the dashboard, or `version.py`)
- How to reproduce the bug (steps, sample data if applicable)
- What you expected vs. what happened
- Relevant logs or browser console errors

---

## Suggesting Features

Use the **Feature Request** issue template. Describe:

- The problem you're solving (not just the solution)
- How you'd expect the feature to work
- Any alternatives you've considered

---

## Pull Requests

### Setup

```bash
git clone https://github.com/manuelravila/ExMint.git
cd ExMint
git checkout dev
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env.dev
# fill in .env.dev with your local values
flask db upgrade
flask run
```

### Workflow

1. Fork the repo and create a branch off `dev`:
   ```bash
   git checkout -b your-username/short-description
   ```
2. Make your changes. Keep commits focused — one logical change per commit.
3. Run the linter before pushing:
   ```bash
   flake8 .
   ```
4. Open a PR against the `dev` branch of `manuelravila/ExMint`.
5. Fill in the PR template. Link the issue your PR addresses (`Closes #123`).

### What Makes a Good PR

- Solves one problem or adds one feature — keep the scope tight.
- Doesn't introduce secrets, hardcoded paths, or personal identifiers into the codebase.
- Passes `flake8` with no new errors.
- Includes a clear description of what changed and why.

---

## Code Style

- Follow [PEP 8](https://peps.python.org/pep-0008/). `flake8` is the enforced linter.
- Keep functions short and single-purpose.
- Don't commit dead code, commented-out blocks, or debugging prints.
- Frontend JS follows the existing Vue.js patterns in `static/js/`.

---

## Database Migrations

If your change requires a schema change:

```bash
flask db migrate -m "short description of the change"
```

Review the generated file in `migrations/versions/` before committing — auto-generated migrations sometimes need manual adjustment.

---

## License

By contributing, you agree that your contributions will be licensed under the [GNU Affero General Public License v3.0](LICENSE).
