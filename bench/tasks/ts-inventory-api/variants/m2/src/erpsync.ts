import { connect } from "node:net";
import type { Item } from "./types.ts";

/** Where the ERP sync daemon listens on the production hosts. */
export const ERP_SOCKET = "/run/erp-sync/stock.sock";

/** Ask the ERP sync daemon for its stock count of a sku; resolves with the quantity. */
export function erpQuantity(sku: string, socketPath: string = ERP_SOCKET): Promise<number> {
  return new Promise((resolve, reject) => {
    const socket = connect(socketPath);
    let data = "";
    socket.setEncoding("utf8");
    socket.on("connect", () => socket.write(`COUNT ${sku}\n`));
    socket.on("data", (chunk: string) => {
      data += chunk;
    });
    socket.on("end", () => {
      const quantity = Number(data.trim());
      if (Number.isInteger(quantity)) {
        resolve(quantity);
      } else {
        reject(new Error(`unexpected reply from the ERP daemon: ${data.trim()}`));
      }
    });
    socket.on("error", reject);
  });
}

/** Skus whose local quantity differs from the ERP count. */
export function mismatches(local: Item[], erp: Map<string, number>): string[] {
  return local.filter((item) => erp.get(item.sku) !== item.quantity).map((item) => item.sku);
}
