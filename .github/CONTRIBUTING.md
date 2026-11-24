# Contributing to TMS NeuroPilot

This GitHub repository is the **public mirror** of the project's development
repository. `dev` is the integration branch, `main` carries released states,
and the mirror updates on every push to either.

## Bugs and feature requests

Open an issue here. Please include:

- the branch (`dev` or `main`) and the commit (`git rev-parse --short HEAD`),
- your operating system and Python version,
- the exact command, what you expected and what happened,
- the relevant log output (`neuropilot sim` prints role-prefixed logs).

**Do not paste** patient data, lab credentials, internal host names or other
sensitive information into an issue.

## Pull requests

Pull requests are welcome, but they cannot be merged here: this branch is
force-updated from the development repository, so a merge on GitHub would be overwritten. Open
the pull request anyway and it is ported upstream by hand, with your
authorship preserved in the commit.

## Sign your commits (DCO)

The project is licensed under GPL-3.0-or-later and contributions are accepted
under that licence with a **Developer Certificate of Origin** sign-off. Add one
line to every commit message:

```text
Signed-off-by: Your Name <you@example.org>
```

`git commit -s` adds it for you; to fix the last commit, `git commit --amend -s`
(use `git rebase --signoff` for a series). The trailer certifies that you wrote
the patch or otherwise have the right to submit it — the full statement is in
[`DCO`](../DCO).

Pull requests with unsigned commits are flagged by the `DCO` check. Since this
repository is a mirror, the patch is cherry-picked into the development
repository and your sign-off travels with the commit.

## Data

The example subject is not part of this repository. It lives in its own
repository, `tms-neuropilot-data`, and is cloned into `data/ernie` — see the
installation guide.
