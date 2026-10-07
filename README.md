# ComfyUI Qwen Omni AudioTagger

在 ComfyUI 中使用本地 **Qwen3-Omni-30B-A3B-Instruct GGUF** 分析音频，生成中文分类标签、声音描述和用途建议。适用于音效、BGM、环境声和人声素材的初步整理。

插件通过独立的 `llama-server` 推理，不需要安装或替换 `llama-cpp-python`。首次配置软件和模型路径后，可以直接执行工作流自动启动服务，也可以使用浮动工具栏管理服务。

## 功能

- 接收 ComfyUI 的 `AUDIO` 输入，发送原始声音进行理解，不先转录成文字。
- 输出分类标签文本，以及耗时、token 用量、结束原因和 JSON 格式检查。
- 支持自定义分类提示词，默认包含 UI 点击、确认、报错、通知、转场等候选类别。
- 可拖动、折叠的浮动工具栏，显示状态和日志，提供启动、停止和配置按钮。
- 工作流首次执行时自动启动服务，等待模型就绪；后续请求复用服务。
- Windows 托管服务随 ComfyUI 后端退出；使用 Job Object 处理父进程被强制结束的情况。
- 推理请求和健康检查仅连接本机 `127.0.0.1`，不使用系统 HTTP 代理。

## 环境与依赖

主要开发和验证环境是 Windows x64、NVIDIA CUDA、ComfyUI。Linux/macOS 未验证；Windows Job Object 的强制退出清理只适用于 Windows，其他系统目前使用正常退出时的清理。

插件使用 ComfyUI 环境已有的 `numpy` 和 `aiohttp`，不需要额外安装 Python 包。还需要以下组件：

| 组件 | 作用 | 地址 |
| --- | --- | --- |
| ComfyUI | 工作流运行环境 | [官方项目](https://github.com/Comfy-Org/ComfyUI) |
| llama.cpp / llama-server | GGUF 模型推理服务 | [官方发行版](https://github.com/ggml-org/llama.cpp/releases) |
| Qwen3-Omni GGUF 与 mmproj | 主模型和音频编码器 | [模型文件仓库](https://huggingface.co/ggml-org/Qwen3-Omni-30B-A3B-Instruct-GGUF/tree/main) |
| ComfyUI-Custom-Scripts | demo 中的 Show Text 显示节点 | [插件仓库](https://github.com/pythongosssss/ComfyUI-Custom-Scripts) |

Show Text 是 demo 工作流的依赖，音频打标节点本身不依赖它。已有其他字符串显示节点时可以替换。

## 安装插件

在 ComfyUI 的 `custom_nodes` 目录打开终端并运行：

```bash
git clone https://github.com/ilisin/ComfyUI-QwenOmni-AudioTagger.git
```

也可以按下面的方式下载 ZIP 安装。

下载本仓库 ZIP 并解压，确保目录结构为：

```text
ComfyUI/
└── custom_nodes/
    └── ComfyUI-QwenOmni-AudioTagger/
        ├── __init__.py
        ├── service.py
        ├── routes.py
        ├── web/
        │   └── toolbar.js
        └── example_workflows/
            └── Qwen3-Omni-Q4-AudioTagger-demo.json
```

避免出现双层插件目录。重启 ComfyUI 后端，再在浏览器按 Ctrl+F5 刷新。页面右下角应出现 **Qwen Omni 音频服务** 浮窗。仅刷新网页不能加载新安装的 Python 插件。

如果还没有 Show Text，可使用 ComfyUI Manager 安装 ComfyUI-Custom-Scripts，或将其仓库放入 `custom_nodes`，然后重启。

## 下载 llama-server

NVIDIA 显卡使用 Windows x64 CUDA 构建。软件可从 [llama.cpp Releases](https://github.com/ggml-org/llama.cpp/releases) 下载。

下面是一组确认存在的 b11429 / CUDA 12.4 下载地址，便于复现环境；它不是对后续最新版本的要求：

- [llama-b11429-bin-win-cuda-12.4-x64.zip](https://github.com/ggml-org/llama.cpp/releases/download/b11429/llama-b11429-bin-win-cuda-12.4-x64.zip)
- [cudart-llama-bin-win-cuda-12.4-x64.zip](https://github.com/ggml-org/llama.cpp/releases/download/b11429/cudart-llama-bin-win-cuda-12.4-x64.zip)

完整解压并合并两个包到同一运行时目录，例如 `C:\Tools\llama.cpp`。保留 EXE 和 DLL 的布局，不要只复制 `llama-server.exe`。其他版本也应使用匹配的程序包和 CUDA DLL 包，并确认支持 Qwen3-Omni 的音频输入。

在 PowerShell 中检查，替换成实际的 EXE 路径：

```powershell
& 'C:\Tools\llama.cpp\llama-server.exe' --version
& 'C:\Tools\llama.cpp\llama-server.exe' --list-devices
```

CUDA 设备列表应能识别你的 NVIDIA 显卡。CPU、ROCm 和 ARM64 发行包不适用于上述 Windows x64 NVIDIA 配置。缺少 DLL 时先检查解压目录和配套依赖。

## 下载主模型和音频编码器

当前托管启动针对下面两个固定文件名。将它们保存在同一个模型目录：

| 文件 | 大小约 | 下载 |
| --- | --- | --- |
| `Qwen3-Omni-30B-A3B-Instruct-Q4_K_M.gguf` | 18.6 GB | [直接下载](https://huggingface.co/ggml-org/Qwen3-Omni-30B-A3B-Instruct-GGUF/resolve/main/Qwen3-Omni-30B-A3B-Instruct-Q4_K_M.gguf) |
| `mmproj-Qwen3-Omni-30B-A3B-Instruct-Q8_0.gguf` | 1.33 GB | [直接下载](https://huggingface.co/ggml-org/Qwen3-Omni-30B-A3B-Instruct-GGUF/resolve/main/mmproj-Qwen3-Omni-30B-A3B-Instruct-Q8_0.gguf) |

大小使用十进制 GB。模型清单见 [ggml-org 仓库](https://huggingface.co/ggml-org/Qwen3-Omni-30B-A3B-Instruct-GGUF/tree/main)。GGUF 无需解压；保留文件名。**只有主模型无法听懂音频，还必须加载对应的 mmproj。**

默认模型目录为当前安装的 `ComfyUI/models/LLM/Qwen3-Omni`，也可以在工具栏设置其他目录：

```text
ComfyUI/models/LLM/Qwen3-Omni/
├── Qwen3-Omni-30B-A3B-Instruct-Q4_K_M.gguf
└── mmproj-Qwen3-Omni-30B-A3B-Instruct-Q8_0.gguf
```

插件不自动下载模型或运行时，不会把这些大文件放进仓库。模型和第三方软件的使用遵循各自的授权条款。

## 配置工具栏

首次使用时展开浮窗的 **服务配置**：

| 参数 | 设置 |
| --- | --- |
| llama-server 路径 | 实际 EXE 的完整路径；首次默认留空，需要填写 |
| 模型目录 | 上述两个 GGUF 所在目录，不是某个文件的路径 |
| 端口 | 默认 8736；与工作流节点的 port 保持一致 |
| GPU 层数 | 默认 24，将其余层留在系统内存；根据显存调整 |
| 上下文长度 | 默认 4096 |
| 加载等待秒数 | 默认 600，仅用于等待模型启动就绪 |
| 执行工作流时自动启动 | 默认开启 |

点击 **保存配置**。配置保存到本机的 `service_config.json`，不会自动开始加载模型。也可以复制 `service_config.example.json` 为 `service_config.json` 后编辑其中的示例路径，再重启 ComfyUI。

如果端口已经有手动启动的服务，浮窗显示 **外部服务**。插件可以向已就绪的外部服务发送请求，但不会停止它，也不会把它绑定到 ComfyUI 生命周期。要使用托管功能，先在原终端 Ctrl+C 关闭外部服务，再从工具栏启动。

## 运行 demo 工作流

1. 把 [example_workflows/Qwen3-Omni-Q4-AudioTagger-demo.json](example_workflows/Qwen3-Omni-Q4-AudioTagger-demo.json) 拖入 ComfyUI。
2. 在 **上传测试音频** 节点选择一个短 WAV 音效，先测试 1 至 5 秒、声音明确的文件。demo 不附带音频，用户自行选择文件。
3. 确认打标节点的 port 与工具栏一致，保留其余默认参数。
4. 点击运行。启用自动启动时，节点会启动服务，等待模型就绪后发送音频。
5. 在 **分类结果** 查看标签，在 **耗时** 查看诊断。换其他音频继续运行，模型无需重新加载。

也可以先点击浮窗 **启动**，等待显示 **已就绪** 后再运行工作流。禁用自动启动时，需要先启动服务。执行工作流指的是节点实际运行；命中 ComfyUI 缓存时不会重新触发服务启动，修改 seed 或更换音频即可重新测试。

默认标签结构示例如下，具体内容由模型生成：

```json
{
  "大类": "音效",
  "子类": ["UI点击"],
  "声音特征": ["电子", "短促", "清脆"],
  "建议用途": ["按钮点击"],
  "音乐风格": [],
  "情绪": [],
  "乐器": [],
  "有人声": false,
  "描述": "一个短促的电子提示音",
  "待人工复核": true
}
```

“声音特征”描述听到的声音，“建议用途”是推测。相似的电子音可能用于点击、确认或通知。格式检查只验证输出是不是有效 JSON，不保证标签正确；节点保留模型原文，不自动修补输出。

工作流每次处理一个音频，默认发送完整内容。测试 BGM 时，可在 LoadAudio 和打标节点之间插入 ComfyUI 自带的 Trim Audio Duration，先截取约 10 秒代表片段。当前没有目录批量扫描、自动分段、标签文件保存或音频重命名功能。

## 参数和资源占用

打标节点默认 `max_tokens=512`、`temperature=0.2`、`seed=42`、`timeout_seconds=600`。请求超时与服务加载等待是不同参数。输出结束原因是 `length` 时，可以把 max_tokens 增加到 768 或 1024。

30B-A3B 是 MoE 模型，激活参数少不等于只需保存 3B 权重。Q4 加 mmproj 的文件大小接近 20 GB，还需要运行缓存；16GB 显存无法全部容纳，可使用 GPU 与系统内存混合运行。16GB 显存、64GB RAM 是参考环境，不是保证速度的最低配置。

显存不足时停止服务，将 GPU 层数降至 16 后保存并重新启动。显存有余量时可逐步增加 GPU 层数比较速度。先卸载其他图像/视频模型。上下文不足时先缩短音频，必要时增加上下文长度，但资源占用也会上升。

## 停止与日志

点击浮窗 **停止并释放显存** 结束托管服务。正在推理时禁止停止，等待请求结束即可。更改运行配置前也需要停止服务。

Windows 下退出 ComfyUI 后端会结束托管服务；关闭浏览器网页不会停止后端。其他终端手动启动的服务需要在原终端停止。

浮窗每 3 秒更新状态，可展开 **服务日志** 查看日志末尾。完整日志在插件目录的 `llama-server.log`，每次托管启动会覆盖上一次日志。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| 节点参数全部 UNKNOWN | 重启 ComfyUI 后端，再 Ctrl+F5 刷新并重新导入 demo |
| 没有浮窗 | 检查插件是否加载、web/toolbar.js 是否存在，查看 ComfyUI 启动日志 |
| Show Text 缺失 | 安装 ComfyUI-Custom-Scripts，或替换为已有字符串显示节点 |
| 提示配置 llama-server 路径 | 填写实际 EXE 的完整路径并保存 |
| 提示缺少模型文件 | 检查模型目录、两个文件名和 mmproj 是否下载完整 |
| 缺少 DLL | 完整解压配套 CUDA 程序包和 cudart 包 |
| 显示外部服务 | 先关闭原终端中的服务，再由浮窗启动 |
| 模型架构或 mmproj 不支持 | 使用支持 Omni 音频输入的运行时，并确认两个模型文件配套 |
| CUDA 显存不足 | 减少 GPU 层数，卸载其他模型，缩短音频 |
| 无法连接或端口不一致 | 检查浮窗状态和节点 port，端口必须一致 |
| HTTP 400/500 或服务退出 | 查看浮窗日志和节点错误文本 |
| 加载超时 | 查看日志；服务保留运行，可等就绪后重新执行 |
| 输出不是有效 JSON | 检查是否截断，增加 max_tokens；提示词要求只返回 JSON |
| 重启服务后仍是旧结果 | 修改节点 seed 或更换音频，避开执行缓存 |

手动健康检查，端口以实际配置为准：

```powershell
curl.exe --noproxy '*' 'http://127.0.0.1:8736/health'
```

## 目录和验证

```text
ComfyUI-QwenOmni-AudioTagger/
├── README.md
├── .gitignore
├── __init__.py
├── service.py
├── routes.py
├── service_config.example.json
├── web/toolbar.js
├── example_workflows/Qwen3-Omni-Q4-AudioTagger-demo.json
└── tests/test_service.py
```

本机配置、日志、缓存、GGUF 和运行时二进制均由 `.gitignore` 排除，保留本机运行数据不会影响公开代码。示例工作流不含本机音频路径，也不依赖仓库外的启动脚本。

Windows 服务生命周期测试使用模拟服务，不下载或加载真实模型。在 Windows 的 Python 环境中从插件目录执行：

```powershell
python tests/test_service.py
```

测试覆盖自动启动、就绪等待、复用、推理期间禁止停止、配置保存、外部服务识别以及父进程强制退出后的清理。真实音频分类质量、量化效果和性能需要用自己的素材评估。
