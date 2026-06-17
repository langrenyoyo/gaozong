/**
 * API 客户端基础配置
 *
 * 基于 axios，统一管理后端请求的 baseURL、超时和响应拦截。
 * baseURL 从环境变量读取，开发环境指向 auto_wechat 本地服务。
 */

import axios from "axios";

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ||
  import.meta.env.VITE_AUTO_WECHAT_API_BASE_URL ||
  (import.meta.env.DEV ? "http://127.0.0.1:9000" : undefined);

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 10000,
});

// 响应拦截器：统一返回 response.data，调用方无需再 .data
apiClient.interceptors.response.use(
  (response) => response.data,
  (error) => Promise.reject(error),
);

export default apiClient;
