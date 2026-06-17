/**
 * Raw webhook event API.
 *
 * Read-only endpoints from auto_wechat:
 *   GET /webhook-events
 *   GET /webhook-events/{event_id}
 */

import apiClient from "./client";
import type {
  WebhookEventDetailResponse,
  WebhookEventListResponse,
  WebhookEventQuery,
} from "./types";

function compactParams(params: WebhookEventQuery): Record<string, string | number | boolean> {
  const result: Record<string, string | number | boolean> = {};
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    result[key] = value;
  });
  return result;
}

export async function fetchWebhookEvents(
  params: WebhookEventQuery,
): Promise<WebhookEventListResponse> {
  return apiClient.get("/webhook-events", { params: compactParams(params) });
}

export async function fetchWebhookEventDetail(
  eventId: number,
): Promise<WebhookEventDetailResponse> {
  return apiClient.get(`/webhook-events/${eventId}`);
}
