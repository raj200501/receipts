import { createApp } from "../src/server.ts";

const port = Number(process.env.PORT ?? 8080);
createApp().listen(port, () => {
  console.log(`stockroom listening on port ${port}`);
});
