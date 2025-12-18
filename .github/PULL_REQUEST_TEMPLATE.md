## Required

- `pre-commit install` before any commit. If pre-commit wasn't run for all commits, you can squash all commits   `git reset --soft $(git merge-base main HEAD) && git commit -m "squash"` and ensure the squashed commit is properly formatted
- All commits must be signed. If some are not, you can squash all commits   `git reset --soft $(git merge-base main HEAD) && git commit -m "squash"` and ensure the squashed commit is signed
- [ ] UI/Design/Menu changes **were** tested on _macOS_, because _macOS_ creates endless problems.  Optionally attach a screenshot.
 
## Optional

- [ ] Update all translations
- [ ] Appropriate pytests were added
- [ ] Documentation is updated
- [ ] If this PR affects builds or install artifacts, set the `Build-Relevant` label to trigger build workflows
