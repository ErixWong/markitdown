# Design - 架构设计

系统架构、队列策略、OCR 优化等技术设计文档。

## 设计文档

| 文档 | 日期 | 说明 |
|------|------|------|
| [MCP 服务器分析与可行性研究](mcp-server-analysis.md) | - | MCP 协议支持、工具设计、异步任务架构 |
| [双服务部署设计](dual-service-deployment.md) | - | API + MCP 双服务模式部署方案 |
| [任务队列策略设计](task-queue-strategy-design.md) | 2026-05-03 | FIFO / Ratio 队列策略及管理员 API |
| [OCR 图像缩放设计](mocr-resize-design.md) | 2026-04-10 | 大图像缩放优化，减少 LLM Vision API 负载 |
