import base64
import io
import json
import time
import urllib.error
import urllib.request
import wave

import numpy as np

from .service import service
from . import routes


DEFAULT_PROMPT = '''请根据实际听到的声音为素材打标签，只输出一个 JSON 对象：
{"大类":"音乐/音效/环境声/人声/混合/未知","子类":[],"声音特征":[],"建议用途":[],"音乐风格":[],"情绪":[],"乐器":[],"有人声":false,"描述":"","待人工复核":false}
子类可参考：UI点击、UI确认、UI取消、UI报错、通知、拾取、转场、冲击、爆炸、脚步、机械、自然环境、背景音乐；没有合适标签时可填写其他或未知。
区分可听见的声音特征与推测用途。无法确定的用途不要强行归类，设待人工复核为 true。非音乐的音乐风格和乐器字段可留空。不猜测作品名称、具体来源、精确 BPM 或制作设备。'''


class QwenOmniAudioTagger:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "audio": ("AUDIO",),
            "port": ("INT", {"default": 8736, "min": 1, "max": 65535}),
            "prompt": ("STRING", {"default": DEFAULT_PROMPT, "multiline": True}),
            "max_tokens": ("INT", {"default": 512, "min": 64, "max": 4096}),
            "temperature": ("FLOAT", {"default": 0.2, "min": 0.0, "max": 2.0, "step": 0.05}),
            "seed": ("INT", {"default": 42, "min": 0, "max": 2147483647}),
            "timeout_seconds": ("INT", {"default": 600, "min": 10, "max": 3600}),
        }}

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("tags", "diagnostics")
    FUNCTION = "tag"
    CATEGORY = "audio/Qwen Omni"

    def tag(self, audio, port, prompt, max_tokens, temperature, seed, timeout_seconds):
        waveform = audio["waveform"]
        if waveform.ndim != 3 or waveform.shape[0] != 1:
            raise ValueError("请一次输入一个音频，waveform 应为 [1, channels, samples]。")
        samples = waveform[0].detach().float().cpu().numpy().T
        if len(samples) == 0:
            raise ValueError("音频为空，请选择包含声音的文件。")
        sample_rate = int(audio["sample_rate"])
        pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(pcm.shape[1])
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(pcm.tobytes())
        duration = len(samples) / sample_rate
        payload = {
            "model": "qwen3-omni",
            "messages": [
                {"role": "system", "content": "你是音频素材分类员。根据音频证据回答，避免虚构声音。"},
                {"role": "user", "content": [
                    {"type": "input_audio", "input_audio": {
                        "data": base64.b64encode(buffer.getvalue()).decode("ascii"), "format": "wav"}},
                    {"type": "text", "text": f"音频实际时长为 {duration:.3f} 秒。\n{prompt}"},
                ]},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "seed": seed,
            "stream": False,
        }
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        # 本地请求不使用工程启动脚本设置的 HTTP/SOCKS 代理。
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        started = time.perf_counter()
        service.acquire(port)
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:2000]
            raise RuntimeError(f"Qwen Omni 服务 HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"无法连接本地 Qwen Omni 服务 127.0.0.1:{port}：{exc.reason}。"
                "请先启动带主模型和音频 mmproj 的 llama-server。"
            ) from exc
        finally:
            service.release()
        choice = result["choices"][0]
        text = choice["message"].get("content") or ""
        if not text.strip():
            raise RuntimeError("模型没有返回正文；检查服务日志，并增加 max_tokens 或上下文长度。")
        try:
            json.loads(text)
            valid_json = True
        except json.JSONDecodeError:
            valid_json = False
        diagnostics = json.dumps({
            "模型": result.get("model"),
            "音频时长秒": round(duration, 3),
            "请求耗时秒": round(time.perf_counter() - started, 2),
            "输出是有效JSON": valid_json,
            "结束原因": choice.get("finish_reason"),
            "token用量": result.get("usage"),
            "服务计时": result.get("timings"),
        }, ensure_ascii=False, indent=2)
        return (text, diagnostics)


NODE_CLASS_MAPPINGS = {"QwenOmniAudioTagger": QwenOmniAudioTagger}
NODE_DISPLAY_NAME_MAPPINGS = {"QwenOmniAudioTagger": "Qwen3 Omni 本地音频打标"}
WEB_DIRECTORY = "./web"
