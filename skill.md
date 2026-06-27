# ComfyUI MCP 使用指南

## 概述

本 skill 指导 Agent 如何通过 MCP Server 控制本地 ComfyUI 服务，实现自然语言驱动的图像生成与工作流管理。

## 核心原则

1. **Pipeline IR 优先**：构建自定义工作流时，优先使用 Pipeline IR（`type: "pipeline"`），它声明式、模块化，引擎自动处理节点创建和连线。
2. **每张图一个工作流**：每个工作流只生成一张图。需要多张图时，Agent 用大模型语义拆分用户输入，循环调用 `build_workflow` → `execute_workflow` → `get_execution_status` → `get_generated_image`。
3. **先查模型再构建**：在 `build_workflow` 之前，先通过 Resource `comfyui://models/checkpoints` 或 `list_models` 确认可用模型名称。
4. **失败即停**：任何步骤返回 `success: false` 时，立即向用户报告错误，不要继续后续步骤。

## 工作流构建

### Pipeline IR 结构

```json
{
    "type": "pipeline",
    "meta": {
        "positive_prompt": "正向提示词",
        "negative_prompt": "反向提示词",
        "width": 1024,
        "height": 1024,
        "steps": 20,
        "cfg": 7.0,
        "sampler_name": "euler",
        "scheduler": "normal",
        "seed": -1,
        "batch_size": 1,
        "filename_prefix": "ComfyUI"
    },
    "pipeline": [
        {"module": "load_checkpoint", "checkpoint": "模型文件名.safetensors"},
        {"module": "prompt_pos"},
        {"module": "prompt_neg"},
        {"module": "empty_latent"},
        {"module": "ksampler"},
        {"module": "vae_decode"},
        {"module": "save_image"}
    ]
}
```

### 可用模块

| 模块名 | 用途 | 必需参数 | 前置依赖 |
|--------|------|---------|---------|
| `load_checkpoint` | 加载主模型 | `checkpoint` | 无 |
| `lora` | 加载 LoRA | `lora_name`, `strength` | load_checkpoint |
| `prompt_pos` | 正向提示词编码 | 无（从 meta 读取） | load_checkpoint |
| `prompt_neg` | 反向提示词编码 | 无（从 meta 读取） | load_checkpoint |
| `empty_latent` | 创建空 latent | 无（从 meta 读取宽高） | 无 |
| `controlnet` | ControlNet 控制 | `image`, `control_net_name` | prompt_pos, prompt_neg |
| `load_image` | 加载输入图片 | `image` | 无 |
| `vae_encode` | 图片→latent | 无 | load_image, load_checkpoint |
| `ksampler` | 核心采样 | 无（从 meta 读取参数） | load_checkpoint, prompt_pos, prompt_neg, empty_latent/vae_encode |
| `vae_decode` | latent→图片 | 无 | ksampler, load_checkpoint |
| `upscale` | 超分放大 | `upscale_model` | vae_decode |
| `save_image` | 保存输出 | 无 | vae_decode/upscale |

### 常见工作流配方

**简单文生图**：
```
load_checkpoint → prompt_pos → prompt_neg → empty_latent → ksampler → vae_decode → save_image
```

**文生图 + LoRA**：
```
load_checkpoint → lora → prompt_pos → prompt_neg → empty_latent → ksampler → vae_decode → save_image
```

**ControlNet + 文生图**：
```
load_checkpoint → prompt_pos → prompt_neg → controlnet → empty_latent → ksampler → vae_decode → save_image
```

**图生图**：
```
load_checkpoint → prompt_pos → prompt_neg → load_image → vae_encode → ksampler → vae_decode → save_image
```

**全组合（LoRA + ControlNet + Upscale）**：
```
load_checkpoint → lora → prompt_pos → prompt_neg → controlnet → empty_latent → ksampler → vae_decode → upscale → save_image
```

## 多图生成流程

当用户要求生成多张图片时（如"生成一个角色的正面、侧面、背面三视图"），按以下流程：

1. **语义拆分**：用大模型将用户输入拆分为独立的子 prompt 列表。拆分原则：
   - 按场景/人物/动作/角度等语义边界切分
   - 每个子 prompt 是完整的、可独立生成图片的描述
   - 保留用户原始风格描述（如"像素风"、"写实风"）到每个子 prompt
   - 使用纯英文 prompt

2. **确认模型**：调用 `list_models("checkpoints")` 获取可用模型列表，根据用户需求选择合适的模型。

3. **循环生成**：对每个子 prompt：
   ```
   build_workflow(pipeline_ir) → execute_workflow() → 轮询 get_execution_status() → get_generated_image()
   ```
   - 等待每张图完成后再开始下一张
   - 汇总所有结果后统一返回给用户

## 模型选择指南

| 场景 | 推荐模型类型 | 示例 |
|------|------------|------|
| 写实人像/场景 | SDXL 系列 | sd_xl_base_1.0.safetensors |
| 动漫/二次元 | Anything/AbyssOrangeMix 系列 | anything_v5.safetensors |
| 像素风 | 专用 pixel art 模型 | pixelArtDiffusion.safetensors |
| 3D 渲染 | DreamShaper/RealisticVision | dreamshaper_v8.safetensors |

## 提示词最佳实践

1. **使用纯英文**：ComfyUI 的 CLIP 模型对英文理解最好
2. **结构化格式**：`[主体描述], [场景], [风格], [画质关键词]`
3. **避免过长**：控制在 200 词以内，过长的 prompt 容易导致画面变形
4. **负向提示词**：始终包含 `bad quality, blurry, distorted, deformed, ugly, bad anatomy, watermark, text`

## 错误处理

| 错误码 | 含义 | 应对 |
|--------|------|------|
| `COMFYUI_UNREACHABLE` | ComfyUI 未启动 | 提示用户启动 ComfyUI |
| `TEMPLATE_NOT_FOUND` | 模板不存在 | 检查模板名称，或用 Pipeline IR 构建 |
| `WORKFLOW_NOT_FOUND` | 未加载工作流 | 先调用 build_workflow 或 load_template |
| `INVALID_PARAM` | 参数错误 | 检查参数值，参考模块文档 |
| `EXECUTION_FAILED` | 执行失败 | 检查 prompt 是否过长，模型是否兼容 |

## 完整示例：用户说"生成一张赛博朋克风格的城市夜景"

```
1. list_models("checkpoints")  → 确认有 sd_xl_base_1.0.safetensors
2. build_workflow({
     "type": "pipeline",
     "meta": {
       "positive_prompt": "cyberpunk city at night, neon lights, rain, reflective streets, cinematic lighting, masterpiece, high quality",
       "negative_prompt": "bad quality, blurry, distorted, deformed, ugly, watermark, text",
       "width": 1024, "height": 1024, "steps": 20, "cfg": 7.0,
       "sampler_name": "euler_ancestral", "scheduler": "normal", "seed": -1
     },
     "pipeline": [
       {"module": "load_checkpoint", "checkpoint": "sd_xl_base_1.0.safetensors"},
       {"module": "prompt_pos"},
       {"module": "prompt_neg"},
       {"module": "empty_latent"},
       {"module": "ksampler"},
       {"module": "vae_decode"},
       {"module": "save_image"}
     ]
   })
3. execute_workflow()  → 获得 prompt_id
4. 轮询 get_execution_status(prompt_id)  → 等待 status == "completed"
5. get_generated_image(filename)  → 返回缩略图给用户
```

## 完整示例：用户说"生成这个角色的正面、侧面、背面三视图，像素风"

```
1. 语义拆分 → [
     "pixel art, character front view, full body, standing pose, clean pixel lines, 16-bit style",
     "pixel art, character side view, full body, standing pose, clean pixel lines, 16-bit style",
     "pixel art, character back view, full body, standing pose, clean pixel lines, 16-bit style"
   ]
2. list_models("checkpoints")  → 选择合适的模型
3. 对每个子 prompt 循环执行 build_workflow → execute → poll → get_image
4. 汇总三张图片返回给用户
```
