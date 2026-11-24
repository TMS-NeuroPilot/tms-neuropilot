# Contributing to TMS NeuroPilot

This GitHub repository is a **read-only mirror** of the group's GitLab
project (`tms-localization/tms-neuropilot/tms-neuropilot`). Development
happens there: `dev` is the integration branch, `main` carries released
states, and the mirror updates on every push to either.

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
force-updated from GitLab, so a merge on GitHub would be overwritten. Open
the pull request anyway and it is ported upstream by hand, with your
authorship preserved in the commit.

## Data

The example subject is not part of this repository. It lives in
`tms-localization/tms-neuropilot/tms-neuropilot-data` and is cloned into
`data/ernie`.
