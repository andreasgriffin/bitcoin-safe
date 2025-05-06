## Required

- [ ] `pre-commit install` before any commit. If pre-commit wasn't run for all commits, you can squash all commits   `git reset --soft $(git merge-base main HEAD) && git commit -m "squash"` and ensure the squashed commit is properly formatted
- [ ] All commits must be signed. If some are not, you can squash all commits   `git reset --soft $(git merge-base main HEAD) && git commit -m "squash"` and ensure the squashed commit is signed
- [ ] Update all translations
 
## Optional

- [ ] Appropriate pytests were added
- [ ] Documentation is updated
