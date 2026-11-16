# How to contribute

Everyone can change anything here: the toolkit (`src/dss_toolkit/`), the example scripts (`examples/`) and the docs.

**main → your branch → Pull Request → teammate approves → Squash and merge → main**

Flow diagrams of this process are in the `diagrams/` folder.

## Rules
1. `main` is the only permanent branch. Nobody pushes to it directly.
2. One short-lived branch per task, made from a fresh `main`, owned by one person.
3. Work reaches `main` only through a Pull Request (PR) that one teammate approves, merged with **Squash and merge**.
4. **Never press VS Code's "Sync Changes" button.** Use the commands below.
5. `data_confidential/` and `results/` never go into git.

## One-time setup
```
git clone https://github.com/AvryKry/Gulf_Power.git
cd Gulf_Power
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
git config --global user.name  "Your Name"
git config --global user.email "your-github-email"
git config --global pull.ff only
```
The sample data folders (`tut_2_data`, `tut_3_data`, `tut_4_data` and the Tut 1.1 dss files) are not in git. Ask Avry for them.

## Every task
**0. Claim it.** Open a GitHub Issue that says what you'll do and which files you'll change. If someone else is working on one of those files, talk to them first.

**1. Start a branch:**
```
git switch main
git pull
git switch -c yourname/short-task-name
```

**2. Work and commit (repeat):**
```
git add -A
git status
git commit -m "Add voltage profile plot to plots.py"
```
Read the `git status` list before committing. If it shows anything from `data_confidential/` or `results/`, stop.

**3. If `main` changed, bring it in** (daily, and always before step 5):
```
git fetch origin
git merge origin/main
```
Use `merge`, never `rebase`.

**4. Check.** Run the scripts your change affects (see "Toolkit changes" below).

**5. Push and open a PR:**
```
git push -u origin yourname/short-task-name
```
Open the link git prints and fill in the checklist. A teammate approves, then you click **Squash and merge**.

**6. Clean up:**
```
git switch main
git pull
git branch -d yourname/short-task-name
```

## Toolkit changes
- **Reuse first.** Extend an existing function with a new optional argument before writing a new one. The module list is at the top of `src/dss_toolkit/__init__.py`.
- **Work on any network.** No hard-coded file, bus or element names.
- **Settings in scripts, logic in the toolkit.**
- **Don't break callers.** New arguments get defaults that keep the old behaviour. If you rename or change a function, update every script that uses it in the same PR.
- **Docstring** on every new function: what it does, its arguments, what it returns.

Before opening the PR, run:

| If you changed… | Run |
|---|---|
| `engine`, `paths`, `network`, `der`, `reports`, `plots`, or not sure | all toolkit scripts: Tut 1.1 functions, Tut 2, Tut 3/3a/3b, Tut 4/4a/4b/4c |
| `timeseries`, `scenario`, `hosting` | Tut 2, Tut 3/3a/3b, Tut 4 |
| `extract` | Tut 1.1 functions, Tut 4b, Tut 4c |
| `results` | Tut 3a, Tut 3b, Tut 4, Tut 4b, Tut 4c |
| `topology`, `interactive`, `basecircuit` | Tut 4, Tut 4a, Tut 4b, Tut 4c |

Results on the sample networks should not change unless you meant them to. If they did, explain why in the PR.

## Confidential data
- Never `git add -f` anything in `data_confidential/` or `results/`.
- Never put confidential data, or results made from it, in Issues, PRs, screenshots or AI tools.
- If you committed something confidential, don't push, and tell Avry immediately.

## When something goes wrong
| You see | Do |
|---|---|
| VS Code shows both ↑ (to push) and ↓ (to pull) | Stop, don't Sync, ask Avry |
| Committed on `main` by mistake (not pushed) | `git switch -c yourname/task`, then `git switch main` and `git reset --hard origin/main` |
| `CONFLICT` after merging main | In each file, keep the right version, delete the `<<<<<<<`, `=======` and `>>>>>>>` lines, then `git add -A` and `git commit`. Or `git merge --abort` and ask. |
| `git push` rejected | Don't use `--force`. Ask. |
