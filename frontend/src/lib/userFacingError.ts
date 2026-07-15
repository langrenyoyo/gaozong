const DEFAULT_USER_ERROR = "数据加载失败，请稍后重试";

const STATE_TEXT: Record<string, string> = {
  pending: "待处理",
  running: "处理中",
  processing: "处理中",
  success: "成功",
  succeeded: "成功",
  completed: "已完成",
  failed: "失败",
  blocked: "已阻断",
  skipped: "已跳过",
  sent: "已发送",
  pasted: "已粘贴",
  active: "启用",
  inactive: "停用",
  disabled: "停用",
  manual_review: "需要人工复核",
  agent_request_failed: "AI小高助手请求失败",
  ocr_model_missing: "文字识别文件缺失",
  ocr_not_ready: "文字识别尚未就绪",
  ocr_initializing: "文字识别正在初始化",
  open_chat_failed: "打开会话失败",
  search_text_not_verified: "搜索文字未通过验证",
};

function errorText(error: unknown): string {
  if (error instanceof Error) return error.message.trim();
  if (typeof error === "string") return error.trim();
  return "";
}

/** 仅向用户展示安全的中文错误；原始错误只在开发控制台保留。 */
export function userFacingError(error: unknown, fallback = DEFAULT_USER_ERROR): string {
  const message = errorText(error);
  if (import.meta.env.DEV) {
    console.error("前端请求错误", error);
  }
  const withoutKnownNames = message.replace(/AI|NewCarProject|Milvu/gi, "");
  if (message && !/[A-Za-z]{2,}/.test(withoutKnownNames)) return message;
  return message ? DEFAULT_USER_ERROR : fallback;
}

export function userFacingText(message?: string | null, fallback = DEFAULT_USER_ERROR): string {
  if (!message) return fallback;
  const withoutKnownNames = message.replace(/AI|NewCarProject|Milvu/gi, "");
  return /[A-Za-z]{2,}/.test(withoutKnownNames) ? fallback : message;
}

export function userFacingState(value?: string | null, fallback = "未知状态"): string {
  if (!value) return "-";
  return STATE_TEXT[value.trim().toLowerCase()] || (/[A-Za-z_]{2,}/.test(value) ? fallback : value);
}
