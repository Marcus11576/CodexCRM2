# Learning Model Note

## Shared learning scope

Current shared learning sources:

- `PLATFORM_MEMORY`
- aggregated `AI_FEEDBACK` patterns

Current effect:

- user feedback weights influence ranking and review ordering
- extracted global insights can be reinforced in `PLATFORM_MEMORY`

Current limitation:

- this phase does not yet train a separate learned weight model outside SQLite
- shared learning is present as stored memory and weighted heuristics, not a standalone model-training pipeline

## Profile-specific learning scope

Current profile-specific signals:

- per-profile feedback history in `AI_FEEDBACK`
- per-profile signal scoring in `compute_signal_scores`
- per-profile brief regeneration from current signal truth

Current effect:

- promoted/approved content ranks higher
- rejected/demoted content ranks lower
- manual edits and manual additions are treated as strong overrides

## Non-negotiable data boundary

- person-specific facts stay on the profile side (`AI_SIGNAL`, legacy intelligence, briefs)
- shared memory is used for pattern/style support, not as global fact-copying between people
