# Preregistrations

Files named `prereg/NNNN-<slug>.md` hold hypotheses, metrics, analysis plans,
thresholds, sample sizes, exclusions, and stopping rules. A file is frozen with
`python tools/prereg.py freeze prereg/NNNN-<slug>.md`, which appends its
SHA-256 to the hash chain in `prereg/LOCK.json`; commit both together before
any confirmatory data exists. A frozen file is never edited. A change is a new,
dated amendment file whose first lines include `Amends: prereg/NNNN-<slug>.md`.

`make prereg-verify` checks the chain, that no frozen file changed after its
freeze commit, and that every confirmatory artifact cites a frozen
preregistration whose freeze commit is a strict ancestor of the artifact's
first commit.
