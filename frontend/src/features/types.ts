import type { NavItem } from "../types";

export interface CapabilityNavCenter {
  id: string;
  title: string;
  shortLabel: string;
  path: string;
  defaultNavId: string;
  permissionCodes: string[];
  children: NavItem[];
}

export interface CapabilityRoute {
  path: string;
  navId: string;
}

export interface LegacyRouteRedirect {
  from: string;
  to: string;
}
