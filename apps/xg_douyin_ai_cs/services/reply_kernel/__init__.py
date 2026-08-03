"""统一回复内核纯业务模块（P0-B）。

无 DB、无 HTTP、无 LLM 调用、无发送、无频控。
三端通过 ContextProvider 构造 ReplyContext，调用 Kernel.decide 得到 ReplyPolicyDecision。
"""
