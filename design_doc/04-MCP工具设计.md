# 04 - MCP 工具设计

## 统一返回格式

所有工具遵循统一的返回格式（详见 [02-架构设计.md](./02-架构设计.md) 统一错误格式）：

```python
# 成功: {"success": true, ...}
# 失败: {"success": false, "error": "...", "error_code": "..."}
```

## MCP Resources

以下只读数据通过 MCP Resource 机制暴露，Agent 可订阅读取，无需反复调用 Tool：

| Resource URI | 内容 |
|--------------|------|
| `comfyui://models/checkpoints` | checkpoint 列表 |
| `comfyui://models/loras` | LoRA 列表 |
| `comfyui://models/vaes` | VAE 列表 |
| `comfyui://models/upscalers` | upscale 模型列表 |
| `comfyui://models/controlnet` | ControlNet 模型列表 |
| `comfyui://node_types` | 所有节点类型定义 |
| `comfyui://system_info` | ComfyUI 系统信息 |

> 保留 `list_models` 和 `get_node_types` 两个 Tool 作为补充，用于需要按条件过滤查询的场景。

## 工具清单总览

| 序号 | 工具名 | 分类 | 说明 |
|------|--------|------|------|
| 1 | `list_models` | 模型管理 | 获取模型列表（checkpoints/loras/vaes/upscalers 等） |
| 2 | `get_node_types` | 节点管理 | 获取所有可用节点类型定义 |
| 3 | `load_template` | 工作流 | 加载工作流模板（内置/用户自定义） |
| 4 | `list_templates` | 工作流 | 列出所有可用模板 |
| 5 | `build_workflow` | 工作流 | 基于 Pipeline IR 构建工作流 |
| 6 | `get_workflow` | 工作流 | 获取当前工作流节点列表 |
| 7 | `save_workflow` | 工作流 | 保存当前工作流到文件 |
| 8 | `execute_workflow` | 执行 | 提交工作流到 ComfyUI 执行 |
| 9 | `execute_and_watch` | 执行 | 提交工作流并通过 WebSocket 实时监控执行过程（推荐） |
| 10 | `get_execution_status` | 执行 | 查询执行状态/进度 |
| 11 | `get_execution_history` | 执行 | 获取历史执行记录 |
| 12 | `get_generated_image` | 图片 | 获取生成的图片（缩略图+原图路径） |
| 13 | `upload_image` | 图片 | 上传图片到 ComfyUI |
| 14 | `create_node` | 原子操作 | 创建节点 |
| 15 | `update_node` | 原子操作 | 修改节点参数 |
| 16 | `remove_node` | 原子操作 | 删除节点 |
| 17 | `connect_nodes` | 原子操作 | 连接两个节点 |
| 18 | `disconnect_nodes` | 原子操作 | 断开连接 |
| 19 | `queue_clear` | 队列 | 清空执行队列 |
| 20 | `queue_cancel` | 队列 | 取消当前执行 |
| 21 | `queue_status` | 队列 | 查看队列状态 |

---

## 详细参数设计

### 1. list_models

获取 ComfyUI 中可用的模型列表。

```
参数:
  model_type: string (可选)
    模型类型过滤。可选值: "checkpoints", "loras", "vaes", "upscalers", "controlnet", "clip", "all"
    默认: "all"

返回:
  {
    "checkpoints": [
      {"name": "dreamshaper_v8.safetensors", "path": "models/checkpoints/dreamshaper_v8.safetensors"},
      ...
    ],
    "loras": [...],
    "vaes": [...],
    ...
  }
```

### 2. get_node_types

获取 ComfyUI 中所有可用节点类型的定义，让 Agent 知道有哪些节点、每个节点有哪些参数。

```
参数: 无

返回:
  {
    "KSampler": {
      "input": {
        "required": {
          "model": ["MODEL"],
          "seed": ["INT", {"default": 0, "min": 0, "max": 1125899906842624}],
          "steps": ["INT", {"default": 20, "min": 1, "max": 10000}],
          "cfg": ["FLOAT", {"default": 8.0, "min": 0.0, "max": 100.0}],
          "sampler_name": [["euler", "euler_ancestral", "dpmpp_2m", ...]],
          "scheduler": [["normal", "karras", "exponential", ...]],
          "denoise": ["FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0}]
        }
      },
      "output": ["LATENT"],
      ...
    },
    ...
  }
```

### 3. load_template

加载工作流模板到当前工作区。

```
参数:
  template_name: string (必填)
    模板名称，如 "txt2img", "img2img", 或用户自定义模板文件名（不含.json）
  params: object (可选)
    模板参数覆盖。如 {"checkpoint": "dreamshaper_v8.safetensors", "width": 1024}

返回:
  {
    "success": true,
    "template_name": "txt2img",
    "workflow": {...},  # 参数化后的工作流 JSON
    "applied_params": {...}  # 实际应用的参数
  }
```

### 4. list_templates

列出所有可用模板。

```
参数: 无

返回:
  {
    "builtin": [
      {"name": "txt2img", "description": "文生图工作流"},
      {"name": "img2img", "description": "图生图工作流"},
    ],
    "user": [
      {"name": "my_workflow", "path": "user_templates/my_workflow.json"},
      ...
    ]
  }
```

### 5. build_workflow

基于 Pipeline IR 构建工作流。Pipeline IR 是一种声明式的模块化工作流描述方式，Agent 只需描述处理步骤序列，引擎自动创建节点并连线。

```
参数:
  ir: object (必填)
    Pipeline IR，格式见 [03-工作流中间表示.md](./03-工作流中间表示.md)

返回:
  {
    "success": true,
    "node_count": 8,
    "pipeline_modules": ["load_checkpoint", "prompt_pos", "prompt_neg", "empty_latent", "ksampler", "vae_decode", "save_image"]
  }
```

### 6. get_workflow

获取当前内存中的工作流节点列表。

```
参数: 无

返回:
  {
    "success": true,
    "node_count": 8,
    "nodes": [
      {"id": "1", "type": "CheckpointLoaderSimple", "title": "Load Checkpoint"},
      ...
    ]
  }
```

### 7. save_workflow

保存当前工作流到文件。

```
参数:
  filepath: string (必填)
    保存路径。可以是相对于 user_templates/ 的路径，也可以是绝对路径。
  overwrite: boolean (可选, 默认: false)
    是否覆盖已存在的文件。

返回:
  {
    "success": true,
    "filepath": "user_templates/my_saved_workflow.json"
  }
```

### 8. execute_workflow

提交当前工作流到 ComfyUI 执行。提交后立即返回 prompt_id，不等待执行完成。

> **推荐使用 `execute_and_watch`**（见下方），它通过 WebSocket 实时监控执行过程，执行完成后自动返回结果。

```
参数:
  client_id: string (可选)
    客户端标识，用于 WebSocket 连接

返回:
  {
    "prompt_id": "abc123-def456",  # ComfyUI 返回的执行 ID
    "message": "Workflow submitted successfully"
  }
```

### 9. execute_and_watch

提交工作流并通过 WebSocket 实时监控执行，执行完成后自动返回结果。**这是推荐的执行方式**，自动处理 WebSocket 连接和 REST 降级。

```
参数:
  client_id: string (可选)
    客户端标识，用于 WebSocket 连接。不传则自动生成 UUID。

返回:
  {
    "success": true,
    "prompt_id": "abc123-def456",
    "status": "completed",  # "running", "completed", "failed", "timeout"
    "outputs": {            # 最终输出（同 get_execution_status）
      "8": {"images": [{"filename": "ComfyUI_00001_.png", "type": "output"}]}
    },
    "events": [             # 所有 WebSocket 事件（或降级轮询事件）
      {"type": "execution_start", "data": {"prompt_id": "abc123"}},
      {"type": "progress", "data": {"value": 5, "max": 20, "node": "3"}},
      {"type": "executing", "data": {"node": null, "prompt_id": "abc123"}}
    ]
  }
```

**工作流程：**

```
1. submit_prompt()  ──► REST 提交工作流，获得 prompt_id
2. WebSocket 连接  ──► ws://host/ws?clientId=xxx
3. 接收事件         ──► execution_start → progress → executing → executed
4. 执行完成         ──► REST 获取最终 outputs
5. 降级             ──► WebSocket 失败时自动回退到 REST 轮询
```

### 10. get_execution_status

查询指定执行的进度和状态。

```
参数:
  prompt_id: string (必填)
    执行 ID（由 execute_workflow 返回）

返回:
  {
    "prompt_id": "abc123-def456",
    "status": "running",  # "pending", "running", "completed", "failed", "cancelled"
    "progress": {
      "current": 3,
      "total": 8
    },
    "nodes": {
      "1": {"status": "completed", "output": {...}},
      "3": {"status": "running"},
      "5": {"status": "pending"}
    }
  }
```

### 11. get_execution_history

获取历史执行记录。

```
参数:
  max_items: int (可选, 默认: 10)
    返回的最大记录数

返回:
  {
    "history": [
      {
        "prompt_id": "abc123",
        "timestamp": "2026-06-21T10:30:00",
        "outputs": {
          "8": {"images": [{"filename": "ComfyUI_00001_.png", "type": "output"}]}
        }
      },
      ...
    ]
  }
```

### 12. get_generated_image

获取生成的图片。

```
参数:
  filename: string (必填)
    图片文件名
  subfolder: string (可选)
    子文件夹路径
  image_type: string (可选, 默认: "output")
    类型: "output" 或 "temp"
  thumbnail: boolean (可选, 默认: true)
    是否返回缩略图 base64

返回:
  {
    "filename": "ComfyUI_00001_.png",
    "original_path": "C:/ComfyUI/output/ComfyUI_00001_.png",
    "thumbnail_base64": "data:image/png;base64,iVBORw0KGgo...",  # 仅 thumbnail=true 时返回
    "width": 1024,
    "height": 1024,
    "file_size": 1234567
  }
```

### 13. upload_image

上传图片到 ComfyUI 的 input 目录。

```
参数:
  image_path: string (必填)
    本地图片文件路径
  subfolder: string (可选)
    目标子文件夹
  overwrite: boolean (可选, 默认: false)
    是否覆盖同名文件

返回:
  {
    "success": true,
    "filename": "uploaded_image.png",
    "subfolder": "",
    "full_path": "C:/ComfyUI/input/uploaded_image.png"
  }
```

### 14. create_node

在当前工作流中创建新节点。

```
参数:
  node_type: string (必填)
    节点类型，如 "KSampler", "LoadCheckpoint" 等
  params: object (可选)
    节点参数
  title: string (可选)
    节点显示名称

返回:
  {
    "success": true,
    "node_id": "15",
    "node_type": "KSampler"
  }
```

### 15. update_node

修改已有节点的参数。

```
参数:
  node_id: string (必填)
    节点 ID
  params: object (必填)
    要更新的参数，如 {"steps": 30, "cfg": 8.5}

返回:
  {
    "success": true,
    "node_id": "15",
    "updated_params": {"steps": 30, "cfg": 8.5}
  }
```

### 16. remove_node

从当前工作流中删除节点。

```
参数:
  node_id: string (必填)
    节点 ID

返回:
  {
    "success": true,
    "node_id": "15"
  }
```

### 17. connect_nodes

连接两个节点的输入/输出槽位。

```
参数:
  from_node_id: string (必填)
    源节点 ID
  from_slot: int (必填)
    源节点输出槽位索引
  to_node_id: string (必填)
    目标节点 ID
  to_slot: int (必填)
    目标节点输入槽位索引
  to_input_name: string (必填)
    目标节点输入参数名（如 "model", "positive", "latent_image"）

返回:
  {
    "success": true,
    "link": {"from": ["15", 0], "to": ["16", "model"]}
  }
```

### 18. disconnect_nodes

断开节点连接。

```
参数:
  node_id: string (必填)
    节点 ID
  input_name: string (必填)
    输入参数名

返回:
  {
    "success": true
  }
```

### 19. queue_clear

清空 ComfyUI 执行队列。

```
参数: 无

返回:
  {
    "success": true,
    "cleared_count": 3
  }
```

### 20. queue_cancel

取消当前正在执行的任务。

```
参数: 无

返回:
  {
    "success": true
  }
```

### 21. queue_status

查看 ComfyUI 队列状态。

```
参数: 无

返回:
  {
    "queue_running": [
      {"prompt_id": "abc123", "client_id": "..."}
    ],
    "queue_pending": [
      {"prompt_id": "def456", "client_id": "..."}
    ]
  }
```

## Agent 多图生成指南

Agent 需要生成多张图片时，不要使用单次工具调用，而是：

1. 用大模型将用户的长描述语义拆分为多个独立的子 prompt
2. 对每个子 prompt，依次调用 `build_workflow` → `execute_and_watch` → `get_generated_image`
3. 汇总所有结果返回给用户

> `execute_and_watch` 会自动等待执行完成并通过 WebSocket 返回状态，无需手动轮询 `get_execution_status`。
> 如需兼容旧流程，仍可使用 `execute_workflow` + `get_execution_status` 的组合。
