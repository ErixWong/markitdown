# MarkItDown Server 文档

## 目录结构

```
docs/
├── design/           # 架构设计文档
│   ├── mcp-server-analysis.md      # MCP 服务器可行性研究
│   ├── dual-service-deployment.md  # 双服务部署设计
│   ├── task-queue-strategy-design.md  # 任务队列策略设计
│   └── mocr-resize-design.md       # OCR 图像缩放设计
├── audit/            # 代码审计报告
│   ├── api-code-audit.md           # API 代码审计
│   ├── mcp-code-audit.md           # MCP 代码审计
│   └── mcp-performance-audit.md    # OCR 性能审计
├── workflow/         # 工作流程与对比
│   ├── mcp-workflow.md             # MCP 工作流程
│   └── api-vs-ocr-mcp-comparison.md  # API vs MCP 对比
├── implementation/   # 实现说明
│   └── pdf-page-by-page-implementation.md  # PDF 逐页处理实现
├── tracking/         # 任务追踪
│   └── api-pdf-processor-audit.md  # PDF 处理器审计追踪
└── tasks/            # 任务管理
    └── active/                     # 进行中任务
        ├── task-001-api-ocr-mcp-comparison/
        ├── task-002-api-code-audit/
        ├── task-003-api-fix-high-priority/
        └── task-004-unified-server-audit-fix/
```

## 快速导航

- **架构设计** → `design/`
- **审计报告** → `audit/`
- **工作流程** → `workflow/`
- **实现细节** → `implementation/`
- **任务管理** → `tasks/`
