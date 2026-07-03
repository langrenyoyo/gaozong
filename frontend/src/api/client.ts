/**
 * API 客户端基础配置。
 *
 * 统一管理后端请求的 baseURL、超时、Authorization 注入和响应解包。
 */

import axios from "axios";
import { clearExternalToken, getExternalToken } from "../authToken";
import { redirectToNewCarLogin } from "../newcarRedirect";

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ||
  import.meta.env.VITE_AUTO_WECHAT_API_BASE_URL ||
  (import.meta.env.DEV ? "http://127.0.0.1:9000" : undefined);

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 10000,
});

apiClient.interceptors.request.use((config) => {
  const token = getExternalToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (error?.response?.status === 401) {
      clearExternalToken();
      if (!redirectToNewCarLogin({ message: "登录已过期，正在重新登录…" })) {
        window.dispatchEvent(new Event("external-auth-expired"));
      }
    }
    return Promise.reject(error);
  },
);

export default apiClient;
