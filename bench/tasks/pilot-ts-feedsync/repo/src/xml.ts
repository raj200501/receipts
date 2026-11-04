/** Small helpers for reading well-formed feed XML without a parser dependency. */

const NAMED: Readonly<Record<string, string>> = {
  amp: "&",
  lt: "<",
  gt: ">",
  quot: '"',
  apos: "'",
};

/** Decode the XML entities and character references in ``text``. */
export function decodeEntities(text: string): string {
  return text.replace(/&(#x[0-9a-fA-F]+|#[0-9]+|[a-z]+);/g, (whole, name: string) => {
    if (name.startsWith("#x")) {
      return String.fromCodePoint(Number.parseInt(name.slice(2), 16));
    }
    if (name.startsWith("#")) {
      return String.fromCodePoint(Number.parseInt(name.slice(1), 10));
    }
    return NAMED[name] ?? whole;
  });
}

/** The text of an element body: a CDATA section as it is, anything else decoded and trimmed. */
export function textContent(body: string): string {
  const cdata = /^\s*<!\[CDATA\[([\s\S]*?)\]\]>\s*$/.exec(body);
  return cdata ? cdata[1] : decodeEntities(body).trim();
}

/** The bodies of every ``<tag>...</tag>`` element in ``text``, in document order. */
export function elements(text: string, tag: string): string[] {
  const pattern = new RegExp(`<${tag}(?:\\s[^>]*)?>([\\s\\S]*?)</${tag}>`, "g");
  return [...text.matchAll(pattern)].map((match) => match[1]);
}

/** The text of the first ``<tag>`` element in ``text``, or null when there is none. */
export function childText(text: string, tag: string): string | null {
  const [first] = elements(text, tag);
  return first === undefined ? null : textContent(first);
}
