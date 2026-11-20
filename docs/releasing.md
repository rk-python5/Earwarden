# Releasing

`CLAUDE.md` has the steps for cutting a version. Publishing is automatic once a tag is pushed:
`.github/workflows/release.yml` checks, builds and publishes it. Before the first public release,
the repository's owner does this once.

## One-time setup

1. **Rename the repository to `Earwarden`** (Settings > General > Repository name). GitHub
   redirects the old address. Then, in your clone,
   `git remote set-url origin https://github.com/rk-python5/Earwarden.git`.
2. **Make the repository public** (Settings > General > Danger zone). The voiceprint model is
   downloaded from its releases, and CI minutes for public repositories are free.
3. **Upload the voiceprint model** to a release tagged `model-ecapa-1` (Releases > Draft a new
   release > choose the tag `model-ecapa-1`). Attach the two files from `.tools/earwarden/models/` in your clone
   (or `models/` in the folder `earwarden setup` used): `ecapa_embedding.onnx` and
   `ecapa_embedding.onnx.data`.
   `earwarden setup` downloads them from there and checks them against the SHA-256s in
   `src/earwarden/provision.py`. If you re-export the model, update the hashes with it.
4. **PyPI:** create an account, then add a *pending trusted publisher* at
   <https://pypi.org/manage/account/publishing/>: project `earwarden`, owner `rk-python5`,
   repository `Earwarden`, workflow `release.yml`, environment `pypi`.
5. **GitHub:** Settings > Environments > New environment, named `pypi`.
6. **GitHub:** Settings > Code security > enable *Private vulnerability reporting*, which
   `SECURITY.md` points to.
7. **Signed tags (D-006):** from v1.0.0, release tags are signed. Set up a signing key
   (`git config gpg.format ssh; git config user.signingkey ~/.ssh/id_ed25519.pub`, and add the
   same key to GitHub as a *signing key*), then tag with `git tag -s`.

## Each release

Follow `CLAUDE.md`'s *Releasing*, then push the tag: the workflow does the rest. A new Claude Code
release needs a re-run of the hook fixtures first (`tests/fixtures/claude_code/`).

## After it's published

On a Mac that has never had Earwarden: `uv tool install 'earwarden[voice]'`, then
`earwarden setup`, `earwarden enroll` and `earwarden doctor`.
