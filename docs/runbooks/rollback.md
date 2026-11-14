# Runbook: rollback

## Code

```bash
git log --oneline -10                 # find the bad commit
git revert --no-edit <hash>           # a revert is safe on shared history; never force-push
git push origin <branch>
```

Each phase is tagged (`phase-0-complete` … `phase-8-complete`, `v1.0.0`). To see the state at a tag: `git checkout phase-6-complete`.

## Database

Applied migrations are never edited. To undo one, add a forward migration that reverses it:

```bash
npx supabase migration new revert_<name>
# write the reversing SQL, then
npx supabase db push --remote="$DATABASE_URL"
```

The hosted project keeps no automatic backups on the free plan; a fresh database is rebuilt from `supabase/migrations` plus `scripts/seed_dev.py`.

## Deployment

- Render: service → Events → Rollback to the previous deploy.
- Vercel: Deployments → previous deployment → Promote to Production.
- Then revert the code as above so the next deploy is correct.

## Rehearsal (done in Phase 9)

A revert of the last commit on a scratch branch, `npm run build` and `pytest -q`, then branch deleted. The steps above are what was exercised.
