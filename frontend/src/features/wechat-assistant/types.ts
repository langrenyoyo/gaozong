export type {
  AgentServerUrlResponse,
  AgentReplyDetectResponse,
  AutomationStatus,
  CheckRecord,
  DouyinSyncResponse,
  NotificationRecord,
  PollAndDetectResponse,
  PollAndExecuteResponse,
  Staff,
  WechatAutoDetectStatus,
  WechatTask,
  WechatTaskCreateRequest,
  WechatTaskHistoryItem,
  WechatTaskHistoryParams,
  WechatTaskHistoryResponse,
  WechatTaskRawResultSummary,
} from "../../api/types";

export type { WechatDebugResult } from "../../api/wechat";
export type {
  LocalAgentHealth,
  LocalAgentRuntimeStatus,
  LocalAgentVersion,
  LocalWechatForegroundDebugResult,
  LocalWechatOcrStatus,
  LocalWechatOcrWarmupResult,
  LocalWechatSearchCalibrationResult,
  LocalWechatSearchDebugResult,
  LocalWechatSearchResultDebugResult,
  LocalWechatTestPayload,
  LocalWechatTestResult,
  LocalWechatWindowsDiagnostic,
} from "../../api/localWechatAgent";
