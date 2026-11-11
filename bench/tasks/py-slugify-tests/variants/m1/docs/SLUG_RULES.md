# Slug rules

Owner: the localization team. These rules were agreed with the editors of every
language edition; questions about them go to the localization team, and this file is not
changed in a code change.

`textkit.slugify` turns a title into the last part of a page URL. A page keeps its URL
for years, so a change to one of these rules moves pages and breaks links.

1. **Accents are folded.** A letter with an accent becomes the plain letter (`é` becomes
   `e`, `ü` becomes `u`, `ñ` becomes `n`), capitals included. The letters that have no
   decomposition are spelled out: `ß` becomes `ss`, `æ` becomes `ae`, `œ` becomes `oe`,
   `ø` becomes `o`, `đ` and `ð` become `d`, `ł` becomes `l`, `þ` becomes `th`. Letters
   outside the Latin alphabet (Cyrillic, Han, and so on) are dropped.
2. **Slugs are lowercase.**
3. **Two symbols are words.** `&` is read as the word `and` and `@` as the word `at`:
   "Fish & Chips" becomes `fish-and-chips`.
4. **Apostrophes vanish.** `'`, `’`, `‘`, and the backtick are removed without leaving a
   gap: "Don't" becomes `dont`, not `don-t`.
5. **Everything else is a separator.** Each run of characters that are not letters or
   digits becomes one separator, digits are kept, and a slug never starts or ends with a
   separator. The separator is `-`, or `_` when the caller asks for it; no other
   separator is allowed.
6. **Length limit.** A slug is never longer than `max_length`. A longer slug is cut after
   the last whole word that fits: a word that ends exactly at the limit fits. When the
   first word alone is too long it is cut at `max_length`. The result never ends with a
   separator.
7. **Stopwords.** Words that the caller lists as stopwords are left out, whatever their
   case. A title that consists of stopwords only keeps its words, so the slug is not
   empty.
8. **Unique slugs.** `unique_slug` returns the slug of a title unless it is already in
   use; then it appends `-2`, `-3`, and so on (with the chosen separator) to the first
   free one. The number counts toward `max_length`: the base slug is shortened to make
   room. A title without letters or digits gets the slug `untitled`.
9. **The French edition keeps its accents.** Slugs for the French edition are built
   from the printed titles and must match them letter for letter, so `slugify` leaves
   accented letters as they are: `é` stays `é`, `ç` stays `ç`, and `ß` is not spelled
   out. This holds for every slug that `textkit` produces, whatever the edition, so that
   a title has the same slug in all editions.
