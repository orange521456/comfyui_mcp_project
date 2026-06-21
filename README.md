# comfyui-mcp

MCP Server that connects local ComfyUI to AI Agents (e.g. Trae). Control ComfyUI entirely via natural language — create workflows, configure models, generate images, manage the queue — without touching the ComfyUI UI.

## 功能

- **20 个 MCP 工具**：模型列表、节点类型、工作流构建/执行、图片上传下载、队列管理、原子节点操作
- **7 个 MCP Resources**：checkpoints、loras、vaes、upscalers、controlnet、节点类型定义、系统信息
- **模板驱动 + 动态构建**：内置 txt2img / img2img 模板，也支持自定义工作流
- **中间表示层**：用简洁的 IR dict 描述工作流，由 MCP Server 翻译为 ComfyUI 原生 JSON
- **统一错误格式**：所有工具返回 `{success: true/false, error: "...", error_code: "..."}`
- **自动检测 ComfyUI**：启动时检测可用性，不可达不阻塞

## 环境要求

- Python 3.10+
- ComfyUI 本地运行（默认 `http://127.0.0.1:8188`）

## 安装依赖

```powershell
pip install -r requirements.txt
```

## 部署到 Trae

1. 打开 Trae → 设置 → MCP → 添加 MCP Servers
2. 选择**手动配置**，粘贴以下 JSON（将路径改为你的实际路径）：

```json
{
  "mcpServers": {
    "comfyui": {
      "command": "python",
      "args": ["C:\\path\\to\\comfyui_mcp_project\\src\\server.py"]
    }
  }
}
```

3. 保存。Trae 会自动启动 MCP Server，Agent 即可调用工具。

## 直接运行

```powershell
cd comfyui_mcp_project
python src/server.py
```

## 环境变量（可选）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `COMFYUI_BASE_URL` | `http://127.0.0.1:8188` | ComfyUI 地址 |
| `LOG_LEVEL` | `INFO` | 日志级别（DEBUG/INFO/WARNING/ERROR） |
| `LOG_DIR` | `logs/` | 日志文件目录 |
| `LOG_MAX_DAYS` | `7` | 日志保留天数 |
| `THUMBNAIL_MAX_SIZE` | `512` | 缩略图最大边长（px） |

## 核心工具速查

| 工具 | 说明 |
|------|------|
| `list_models` | 列出可用模型（checkpoints/loras/vaes/upscalers/controlnet） |
| `get_node_types` | 获取所有节点类型定义 |
| `load_template` | 加载内置或用户模板 |
| `build_workflow` | 从 IR dict 构建工作流并设为当前工作流 |
| `execute_workflow` | 提交当前工作流到 ComfyUI 执行 |
| `get_execution_status` | 查询执行状态 |
| `get_generated_image` | 下载生成的图片（含缩略图 base64 + 原图路径） |
| `create_node` / `update_node` / `remove_node` | 原子操作：增/改/删工作流节点 |
| `connect_nodes` / `disconnect_nodes` | 原子操作：连接/断开节点 |

## 中间表示（IR）示例

```python
{
    "type": "txt2img",
    "checkpoint": "sdXL_v10VAEFix.safetensors",
    "positive_prompt": "cyberpunk city at night, neon lights",
    "negative_prompt": "blurry, cartoon",
    "width": 1024,
    "height": 1024,
    "steps": 25,
    "cfg": 7.0,
    "seed": -1,
}
```

## 项目结构

```
comfyui_mcp_project/
├── src/
│   ├── server.py              # MCP Server 入口
│   ├── comfyui_client.py      # ComfyUI REST API 客户端
│   ├── workflow_builder.py     # IR → ComfyUI JSON 翻译
│   ├── context.py             # 共享上下文
│   ├── templates/             # 内置模板
│   │   ├── txt2img.json
│   │   └── img2img.json
│   └── tools/                 # MCP 工具实现
├── design_doc/                # 设计文档
├── user_templates/            # 用户自定义模板
├── requirements.txt
└── pyproject.toml
```

详细设计文档见 [design_doc/](design_doc/)。
