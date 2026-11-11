# exprlex

A small expression language for alert rules, such as

    severity >= 3 && service.name in ["api", "billing"] ? "page" : "ticket"

exprlex has a tokenizer (`src/tokenizer.ts`), a parser (`src/parser.ts`), and an evaluator
(`src/evaluate.ts`). The rule editor and the rule linter use the same token rules; they are
written down in `docs/TOKEN_RULES.md`, which the language tooling team owns.

## Usage

    node --experimental-strip-types bin/exprlex.ts tokens 'a >= 1.5e2 && b'
    node --experimental-strip-types bin/exprlex.ts eval '(a + 1) * 2' --var a=4
    npm run eval -- 'x in [1, 2, 3]' --var x=2

`tokens` prints one line per token as `line:column kind text`. `eval` parses the
expression, evaluates it with the `--var NAME=VALUE` variables (a value is a number, `true`,
`false`, `null`, or text), and prints the result; strings are printed in quotes. A lexical,
syntax, or evaluation error prints `exprlex: MESSAGE` on standard error and exits with
status 2.

## The language

Numbers, strings in single or double quotes, `true`, `false`, `null`, names, lists
(`[1, 2]`), member access (`a.b`), indexing (`a[0]`), the operators `+ - * / % **`,
comparisons, `&&`/`and`, `||`/`or`, `!`/`not`, `in`, and the conditional `test ? yes : no`.
`**` binds tighter than the unary minus and groups to the right. `#` starts a comment.

## Development

    npm test

There are no dependencies: the code is TypeScript run directly by Node 22 with
`--experimental-strip-types`, and the tests use `node:test`. The tests of the tokenizer are
in `test/tokenizer.test.ts`.
