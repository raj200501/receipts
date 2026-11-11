# edge-router

The routing layer of the edge proxy. It reads the route manifest that the API catalog
exports (`routes.manifest.json`) and decides for each request which route handles it,
and so which upstream service the proxy forwards it to. The `edge` command shows what
the router decides for a request, which helps when a route does not behave as expected.

## Usage

    node --experimental-strip-types bin/edge.ts match GET /v2/customers/C-77
    node --experimental-strip-types bin/edge.ts match POST /v2/orders --manifest staging.json
    node --experimental-strip-types bin/edge.ts routes
    npm run match -- GET /v2/customers/C-77

`edge match METHOD TARGET` prints the route that handles the request, its upstream, and
the parameter values:

    route:    customers.get
    upstream: http://crm-api.prod.internal:8080
    params:   customerId=C-77

It exits with status 0 when a route matches. When none does it prints
`404 no route for GET /v2/nothing`, and when the path matches only routes for other
methods it prints `405 DELETE is not allowed for /v2/customers/C-77 (allow: GET, HEAD,
PATCH)`; both exit with status 1. The query string of the target is ignored.
`edge routes` lists the routes of the manifest in order.

Both commands read `routes.manifest.json` in the current directory unless
`--manifest FILE` names another one. A manifest or a request target that cannot be read
stops the command with a message on stderr and exit status 2.

## Route manifest

    {
      "version": 3,
      "routes": [
        {"name": "customers.get", "method": "GET", "pattern": "/v2/customers/:customerId",
         "upstream": "http://crm-api.prod.internal:8080"},
        {"name": "health.live", "method": "GET", "pattern": "/healthz",
         "upstream": "http://edge-health.prod.internal:8080", "strict": true}
      ]
    }

Every route has a unique `name`, a `method` (`GET`, `POST`, `PUT`, `PATCH`, or `DELETE`),
a `pattern`, an `upstream` URL (`http://` or `https://`), and optionally
`"strict": true`. Other top-level keys (`generatedAt`, `source`) are ignored.

## Patterns

- A static segment such as `orders` matches exactly that text (case matters).
- `:name` matches one segment that is not empty; its value is percent-decoded.
- `:name?` is an optional parameter. Optional parameters may only come at the end of a
  pattern, one or more in a row. The route matches with or without their segments
  (`/v2/reports/:period?` matches `/v2/reports` and `/v2/reports/2026-Q3`), and a
  parameter whose segment is left out is not in the params at all.
- `*name` matches the rest of the path, one or more segments, and may only be the last
  segment. Its value is the matched segments joined with `/`.
- A request path may end with one slash: `/v2/orders/` matches the route for
  `/v2/orders` with the same params, and the slash is never part of a value. A route
  with `"strict": true` matches only the path without the trailing slash.

A pattern starts with `/`, has no empty segments, and does not end with `/` (except the
root pattern `/` itself).

## Choosing a route

Routes without parameters win over routes with parameters, so `/v2/orders/export` is
not taken for an order id; otherwise the first matching route in manifest order wins. A
HEAD request is answered by the GET route. When the path matches routes but none for the
request's method, the answer is a 405 that lists the methods that would match (HEAD
whenever GET would).

## Development

    npm test

There are no dependencies: the code is TypeScript run directly by Node 22 with
`--experimental-strip-types`, and the tests use `node:test`.
