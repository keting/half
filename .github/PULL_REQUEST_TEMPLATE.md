## Summary

Describe the change and why it is needed.

Closes #

Related discussion:

## Scope

- [ ] This PR is small and focused.
- [ ] This PR does not mix unrelated refactors, formatting-only changes, or
      translation work into a feature change.
- [ ] Public API, data model, permissions, security boundaries, and deployment
      behavior are unchanged, or the impact is described below.

## Screenshots Or Recordings

Add screenshots or recordings for UI changes, or write "N/A".

## Migration / Configuration Impact

Describe any environment variable, data model, deployment, or migration impact,
or write "N/A".

## Testing

- [ ] `cd src/backend && uv run python -m pytest tests/ -v`
- [ ] `cd src/frontend && npm test`
- [ ] `cd src/frontend && npm run build`

If any test was not run, explain why:

## Checklist

- [ ] The change stays scoped and focused.
- [ ] Related issues are linked when applicable.
- [ ] Related discussions are linked when applicable.
- [ ] Docs were updated where behavior, API shape, or setup changed.
- [ ] No secrets, private URLs, or local machine paths were introduced.
