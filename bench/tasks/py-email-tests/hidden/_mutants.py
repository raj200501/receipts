"""The seeded faulty versions of addrcheck used by the write_tests hidden checks.

Each fault is hand-written for this benchmark. It is one textual replacement in one
source file of the starting implementation: ``(file, old, new)``. ``old`` must occur in
the file exactly once. The faults are grouped by the requirement whose class of faults
they belong to, and every one of them leaves the repository's starting tests passing.
"""

from __future__ import annotations

LOCAL = "src/addrcheck/local.py"
DOMAIN = "src/addrcheck/domain.py"
VALIDATOR = "src/addrcheck/validator.py"

#: name -> (path of the source file, text to replace, replacement)
MUTANTS: dict[str, tuple[str, str, str]] = {
    # R1: the local part (rule 2).
    "local_part_of_65_is_accepted": (
        LOCAL,
        "    if len(local) > MAX_LOCAL:\n",
        "    if len(local) > MAX_LOCAL + 1:\n",
    ),
    "local_part_of_64_is_rejected": (
        LOCAL,
        "    if len(local) > MAX_LOCAL:\n",
        "    if len(local) >= MAX_LOCAL:\n",
    ),
    "leading_dot_is_accepted": (
        LOCAL,
        '    if local.startswith("."):\n',
        "    if False:\n",
    ),
    "trailing_dot_in_local_part_is_accepted": (
        LOCAL,
        '    if local.endswith("."):\n',
        "    if False:\n",
    ),
    "consecutive_dots_are_accepted": (
        LOCAL,
        '    if ".." in local:\n',
        "    if False:\n",
    ),
    "apostrophe_is_rejected": (
        LOCAL,
        'LOCAL_SPECIALS = "!#$%&\'*+/=?^_`{|}~-"\n',
        'LOCAL_SPECIALS = "!#$%&*+/=?^_`{|}~-"\n',
    ),
    "non_ascii_letters_are_accepted_in_the_local_part": (
        LOCAL,
        "    if not set(local) <= _LOCAL_CHARS:\n",
        "    if not all(char in _LOCAL_CHARS or not char.isascii() for char in local):\n",
    ),
    # R2: the domain (rule 3).
    "label_of_64_is_accepted": (
        DOMAIN,
        "        if len(label) > MAX_LABEL:\n",
        "        if len(label) > MAX_LABEL + 1:\n",
    ),
    "label_of_63_is_rejected": (
        DOMAIN,
        "        if len(label) > MAX_LABEL:\n",
        "        if len(label) >= MAX_LABEL:\n",
    ),
    "leading_hyphen_in_a_label_is_accepted": (
        DOMAIN,
        '        if label.startswith("-"):\n',
        "        if False:\n",
    ),
    "trailing_hyphen_in_a_label_is_accepted": (
        DOMAIN,
        '        if label.endswith("-"):\n',
        "        if False:\n",
    ),
    "domain_without_a_dot_is_accepted": (
        DOMAIN,
        "    if len(labels) < 2:\n",
        "    if len(labels) < 1:\n",
    ),
    "numeric_last_label_is_accepted": (
        DOMAIN,
        "    if labels[-1].isdigit():\n",
        "    if False:\n",
    ),
    "domain_of_254_is_accepted": (
        DOMAIN,
        "    if len(domain) > MAX_DOMAIN:\n",
        "    if len(domain) > MAX_DOMAIN + 1:\n",
    ),
    "domain_of_253_is_rejected": (
        DOMAIN,
        "    if len(domain) > MAX_DOMAIN:\n",
        "    if len(domain) >= MAX_DOMAIN:\n",
    ),
    "underscore_is_accepted_in_a_label": (
        DOMAIN,
        '_LABEL_CHARS = frozenset(string.ascii_letters + string.digits + "-")\n',
        '_LABEL_CHARS = frozenset(string.ascii_letters + string.digits + "-_")\n',
    ),
    "non_ascii_letters_are_accepted_in_a_label": (
        DOMAIN,
        "        if not set(label) <= _LABEL_CHARS:\n",
        "        if not all(char in _LABEL_CHARS or char.isalnum() for char in label):\n",
    ),
    # R3: surrounding whitespace and normalization (rules 1 and 4).
    "surrounding_whitespace_is_not_ignored": (
        VALIDATOR,
        "    text = address.strip()\n",
        "    text = address\n",
    ),
    "normalize_keeps_the_domain_case": (
        VALIDATOR,
        'normalized=f"{local}@{domain.lower()}"',
        'normalized=f"{local}@{domain}"',
    ),
    "normalize_lowercases_the_local_part": (
        VALIDATOR,
        'normalized=f"{local}@{domain.lower()}"',
        'normalized=f"{local.lower()}@{domain.lower()}"',
    ),
    "trailing_dot_of_the_domain_is_rejected": (
        VALIDATOR,
        '        if domain.endswith("."):\n            domain = domain[:-1]\n',
        "",
    ),
    "several_trailing_dots_are_accepted": (
        VALIDATOR,
        "            domain = domain[:-1]\n",
        '            domain = domain.rstrip(".")\n',
    ),
    # R4: plus tags and blocked domains (rules 5 and 6).
    "plus_tags_are_rejected_by_default": (
        VALIDATOR,
        "    allow_plus_tags: bool = True,\n",
        "    allow_plus_tags: bool = False,\n",
    ),
    "plus_tags_are_accepted_when_not_allowed": (
        VALIDATOR,
        '    if reason is None and not allow_plus_tags and "+" in local:\n',
        "    if False:\n",
    ),
    "blocked_domains_are_matched_case_sensitively": (
        VALIDATOR,
        '        entry = entry.strip().lower().rstrip(".")\n',
        '        entry = entry.strip().rstrip(".")\n',
    ),
    "subdomains_of_a_blocked_domain_are_accepted": (
        VALIDATOR,
        '        if domain == entry or domain.endswith("." + entry):\n',
        "        if domain == entry:\n",
    ),
    "blocked_domain_matches_any_domain_ending_with_its_text": (
        VALIDATOR,
        '        if domain == entry or domain.endswith("." + entry):\n',
        "        if domain.endswith(entry):\n",
    ),
}
