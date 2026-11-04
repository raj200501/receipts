# Runner pools

Our CI jobs run on self-hosted runners that the platform team operates. The pools and
their labels are listed in `infra/runners.json`:

- `build`: compiling and packaging jobs,
- `test`: test jobs,
- `release`: jobs that publish artifacts (needs approval).

A job selects a pool by listing all of that pool's labels in `runs-on`. The platform team
owns the file; do not edit it from this repository. Questions go to the platform channel.
