import apiClient from "./client";

export interface AiAgent {
  id: number;
  agent_id: string;
  merchant_id: string;
  name: string;
  avatar_seed: string;
  avatar_url?: string | null;
  prompt: string;
  knowledge_base_text: string;
  status: "active" | "disabled" | "deleted";
  created_at?: string | null;
  updated_at?: string | null;
}

export interface AiAgentPayload {
  name: string;
  prompt: string;
  knowledge_base_text: string;
  avatar_url?: string | null;
}

export interface AiAgentTrainingChatResult {
  reply_text: string;
  warnings: string[];
  llm_used: boolean;
  knowledge_used: boolean;
}

interface ApiResponse<T> {
  success: boolean;
  data: T;
  message: string;
}

export async function fetchAiAgents(): Promise<AiAgent[]> {
  const response = await apiClient.get<unknown, ApiResponse<AiAgent[]>>("/agents");
  return response.data;
}

export async function createAiAgent(payload: AiAgentPayload): Promise<AiAgent> {
  const response = await apiClient.post<unknown, ApiResponse<AiAgent>>("/agents", payload);
  return response.data;
}

export async function updateAiAgent(agentId: string, payload: AiAgentPayload & { status?: "active" | "disabled" }): Promise<AiAgent> {
  const response = await apiClient.put<unknown, ApiResponse<AiAgent>>(`/agents/${agentId}`, payload);
  return response.data;
}

export async function deleteAiAgent(agentId: string): Promise<AiAgent> {
  const response = await apiClient.delete<unknown, ApiResponse<AiAgent>>(`/agents/${agentId}`);
  return response.data;
}

export async function trainingChat(agentId: string, message: string): Promise<AiAgentTrainingChatResult> {
  const response = await apiClient.post<unknown, ApiResponse<AiAgentTrainingChatResult>>(`/agents/${agentId}/training-chat`, {
    message,
  });
  return response.data;
}
