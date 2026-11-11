# Heading anchors on the handbook site

Every heading on a handbook page gets an anchor, so that a link such as
`oncall.md#paging-rules` opens the page at that heading. This page describes how the
site builds those anchors, for tools and people that write links to them. The docs
platform team maintains the site and this page; questions and change requests go to
them in #docs-platform.

## How an anchor is built

The site builds the anchor of a heading from its text as the page shows it:

1. Take the heading text without its Markdown formatting. Emphasis markers and the
   backticks of code spans are left out, and a link counts as its link text, so
   ``## The `pager` tool`` reads `The pager tool`.
2. Lowercase it.
3. Remove every character that is not a letter, a digit, a space, a hyphen (`-`), or an
   underscore (`_`). Letters with accents and letters of other alphabets are letters
   and stay, so `Übersicht` becomes `übersicht`.
4. Replace each space with a hyphen. Two spaces in a row give two hyphens, and hyphens
   that were already in the text stay, so `Before - after` becomes `before---after`.

A heading that has nothing left after these steps (for example `## ???`) gets the
anchor `section`.

## Repeated anchors

An anchor is used only once on a page. When the anchor of a heading is already used by
an earlier heading on the same page, the site adds `-1` to it; if that is taken as
well, it tries `-2`, `-3`, and so on, and uses the first one that is still free. Every
heading on the page counts, whatever its level: the page title, and headings that a
table of contents leaves out. Lines in fenced code blocks are not headings and do not
count.

## Examples

| Heading | Anchor |
| --- | --- |
| `## Getting started` | `getting-started` |
| `## Step 2: restart the bridge` | `step-2-restart-the-bridge` |
| `## Q&A` | `qa` |
| `## Over-the-air updates` | `over-the-air-updates` |
| `## **Before** you page` | `before-you-page` |
| `## config_v2 files` | `config_v2-files` |
| The second `## Setup` on a page | `setup-1` |
| The third `## Setup` on a page | `setup-2` |
