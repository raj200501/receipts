import { createServer } from "node:http";
import type { IncomingMessage, Server } from "node:http";
import { createHandler } from "./handler.ts";
import type { Handler } from "./handler.ts";

/** Read and parse the JSON body of a request; undefined when the body is empty. */
async function readBody(req: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) {
    chunks.push(chunk as Buffer);
  }
  const text = Buffer.concat(chunks).toString("utf8").trim();
  return text === "" ? undefined : JSON.parse(text);
}

/** Wrap a handler as a node:http server. Malformed JSON bodies get a 400 here. */
export function createApp(handler: Handler = createHandler()): Server {
  return createServer(async (req, res) => {
    const url = new URL(req.url ?? "/", "http://localhost");
    let body: unknown;
    try {
      body = await readBody(req);
    } catch {
      res.writeHead(400, { "content-type": "application/json" });
      res.end(JSON.stringify({ error: "bad_json" }));
      return;
    }
    const response = handler({
      method: req.method ?? "GET",
      path: url.pathname,
      query: Object.fromEntries(url.searchParams),
      body,
    });
    res.writeHead(response.status, response.headers);
    res.end(response.body === null ? undefined : JSON.stringify(response.body));
  });
}
