# gradebook

Final grades and a plain-text class report from a CSV export of assignment scores. The
grading rules are in [docs/GRADING.md](docs/GRADING.md).

## Usage

    node --experimental-strip-types bin/gradebook.ts report examples/scores.csv
    npm run report -- examples/scores.csv

The CSV export has a header row and one row per student and assignment:

    student,name,assignment,category,points,max_points
    s01,Ada Lovelace,hw1,homework,9,10

`category` is one of `homework`, `quizzes`, `project`, `exams`. `points` is a number,
empty for missing work, or `EX` for an excused assignment. Names must not contain
commas. A row that cannot be read stops the report with a message that names its line,
and the command exits with status 2.

The report has one line per student (category percentages, the final percentage with
one decimal, and the letter grade), then the class summary: the number of students, the
mean and median final percentage, and how many students got each letter.

## Development

    npm test

There are no dependencies: the code is TypeScript run directly by Node 22 with
`--experimental-strip-types`, and the tests use `node:test`.
