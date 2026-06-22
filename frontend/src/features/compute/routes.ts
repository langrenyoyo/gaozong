import type { CapabilityRoute } from "../types";

export const computeRoutes: CapabilityRoute[] = [
  { path: "/compute/center", navId: "compute" },
  { path: "/compute/token-transactions", navId: "compute-token-transactions" },
  { path: "/compute/recharge-orders", navId: "compute-recharge-orders" },
  { path: "/compute/packages", navId: "compute-packages" },
];
