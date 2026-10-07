import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

app.registerExtension({
    name: "QwenOmni.ServiceToolbar",
    setup() {
        const panel = document.createElement("section");
        panel.id = "qwen-omni-toolbar";
        panel.style.cssText = "position:fixed;right:18px;bottom:24px;width:320px;max-width:calc(100vw - 24px);max-height:85vh;overflow:auto;z-index:1000;background:var(--comfy-menu-bg,#242424);color:var(--fg-color,#eee);border:1px solid #666;border-radius:10px;padding:12px;box-shadow:0 5px 22px #0006;font:13px sans-serif";
        panel.innerHTML = `
            <header style="display:flex;justify-content:space-between;cursor:move;touch-action:none">
                <strong>Qwen Omni 音频服务</strong><button data-action="collapse" title="折叠">−</button>
            </header>
            <div data-part="body">
                <p data-part="status" role="status" aria-live="polite">连接状态…</p>
                <div style="display:flex;gap:8px"><button data-action="start">启动</button><button data-action="stop">停止并释放显存</button></div>
                <p data-part="message" style="white-space:pre-wrap;color:#e6b968"></p>
                <details data-part="settings"><summary style="cursor:pointer;margin:12px 0">服务配置</summary>
                    <label style="display:block">llama-server 路径<input data-key="server_exe" type="text"></label>
                    <label style="display:block">模型目录<input data-key="model_dir" type="text"></label>
                    <label style="display:block">端口<input data-key="port" type="number" min="1" max="65535"></label>
                    <label style="display:block">GPU 层数<input data-key="gpu_layers" type="number" min="0" max="256"></label>
                    <label style="display:block">上下文长度<input data-key="context_size" type="number" min="1024" max="262144" step="256"></label>
                    <label style="display:block">加载等待秒数<input data-key="startup_timeout" type="number" min="10" max="3600"></label>
                    <label style="display:block;margin:10px 0"><input data-key="auto_start" type="checkbox">执行工作流时自动启动</label>
                    <button data-action="save">保存配置</button>
                </details>
                <details><summary style="cursor:pointer;margin-top:12px">服务日志</summary><pre data-part="log" style="max-height:220px;overflow:auto;white-space:pre-wrap;font-size:11px"></pre></details>
            </div>`;
        for (const input of panel.querySelectorAll('input:not([type="checkbox"])')) {
            input.style.cssText = "display:block;box-sizing:border-box;width:100%;margin:5px 0 10px;padding:5px;color:inherit;background:var(--comfy-input-bg,#333);border:1px solid #666;border-radius:4px";
        }
        document.body.append(panel);
        const part = (name) => panel.querySelector(`[data-part="${name}"]`);
        const button = (name) => panel.querySelector(`[data-action="${name}"]`);
        let initialized = false;
        let pending = false;
        let polling = false;
        let state;
        let actionError = "";
        const labels = { stopped: "已停止", loading: "模型加载中", running: "已就绪", external: "外部服务", error: "启动失败或已退出" };

        function render(data, updateConfig = false) {
            state = data;
            part("status").textContent = `${labels[data.state] ?? data.state} · 端口 ${data.config.port}${data.pid ? ` · PID ${data.pid}` : ""}${data.active_requests ? " · 音频处理中" : ""}`;
            part("status").style.color = data.ready ? "#83d89b" : "inherit";
            part("message").textContent = data.state === "external"
                ? "此服务由其他终端启动。请先在原终端 Ctrl+C 关闭，再由这里启动，才能跟随 ComfyUI 退出。"
                : actionError || data.error || "";
            part("log").textContent = data.log || "暂无托管服务日志";
            button("start").disabled = pending || data.owned || data.state === "external";
            button("stop").disabled = pending || !data.owned || data.active_requests > 0;
            button("save").disabled = pending || data.owned;
            if (!initialized || updateConfig) {
                for (const input of panel.querySelectorAll("[data-key]")) {
                    if (input.type === "checkbox") input.checked = data.config[input.dataset.key];
                    else input.value = data.config[input.dataset.key];
                }
                initialized = true;
            }
        }

        async function call(action, payload) {
            const response = await api.fetchApi(`/qwen-omni/${action}`, {
                method: action === "status" ? "GET" : "POST",
                headers: { "Content-Type": "application/json" },
                ...(payload ? { body: JSON.stringify(payload) } : {}),
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
            return data;
        }

        async function action(name, payload) {
            actionError = "";
            pending = true;
            if (state) render(state);
            try {
                const data = await call(name, payload);
                pending = false;
                render(data, name === "config");
            } catch (error) {
                pending = false;
                actionError = error.message;
                if (state) render(state);
                part("message").textContent = error.message;
            }
        }
        button("start").onclick = () => action("start");
        button("stop").onclick = () => action("stop");
        button("save").onclick = () => {
            const config = {};
            for (const input of panel.querySelectorAll("[data-key]")) {
                config[input.dataset.key] = input.type === "checkbox" ? input.checked
                    : input.type === "number" ? Number(input.value) : input.value;
            }
            action("config", config);
        };
        button("collapse").onclick = () => {
            part("body").hidden = !part("body").hidden;
            button("collapse").textContent = part("body").hidden ? "+" : "−";
        };

        const header = panel.querySelector("header");
        let drag;
        header.onpointerdown = (event) => {
            if (event.target.closest("button")) return;
            const rect = panel.getBoundingClientRect();
            drag = { x: event.clientX - rect.left, y: event.clientY - rect.top };
            header.setPointerCapture(event.pointerId);
        };
        header.onpointermove = (event) => {
            if (!drag) return;
            panel.style.left = `${Math.max(0, Math.min(innerWidth - panel.offsetWidth, event.clientX - drag.x))}px`;
            panel.style.top = `${Math.max(0, Math.min(innerHeight - 48, event.clientY - drag.y))}px`;
            panel.style.right = "auto";
            panel.style.bottom = "auto";
        };
        header.onpointerup = header.onpointercancel = () => { drag = null; };

        async function poll() {
            if (polling || pending || document.hidden) return;
            polling = true;
            try { render(await call("status")); }
            catch (error) {
                part("status").textContent = "ComfyUI 服务未连接";
                part("message").textContent = "新增插件后需重启 ComfyUI，再刷新页面。";
                for (const name of ["start", "stop", "save"]) button(name).disabled = true;
            } finally { polling = false; }
        }
        poll();
        setInterval(poll, 3000);
    },
});
