"""语音转文字服务提供器"""

import base64
import hashlib
import time
from pathlib import Path
from typing import Optional

import httpx


# class GroqTranscriptionProvider:
#     """使用 Groq API 进行语音转文字"""
#     
#     def __init__(self, api_key: str):
#         self.api_key = api_key
#         self.base_url = "https://api.groq.com/openai/v1"
#     
#     async def transcribe(self, file_path: Path) -> Optional[str]:
#         """将音频文件转换为文字"""
#         try:
#             async with httpx.AsyncClient() as client:
#                 with open(file_path, "rb") as f:
#                     response = await client.post(
#                         f"{self.base_url}/audio/transcriptions",
#                         headers={"Authorization": f"Bearer {self.api_key}"},
#                         files={
#                             "file": ("audio.webm", f, "audio/webm"),
#                             "model": (None, "whisper-large-v3"),
#                             "response_format": (None, "text"),
#                             "language": (None, "zh"),
#                         },
#                     )
#                 if response.status_code == 200:
#                     return response.text.strip()
#                 else:
#                     print(f"[Transcription] API error: {response.status_code}")
#                     return None
#         except Exception as e:
#             print(f"[Transcription] Error: {str(e)}")
#             return None


class BaiduTranscriptionProvider:
    """使用百度语音识别 API 进行语音转文字"""
    
    def __init__(self, api_key: str, secret_key: str):
        """
        初始化百度语音识别
        
        :param api_key: 百度 API Key
        :param secret_key: 百度 Secret Key
        """
        self.api_key = api_key
        self.secret_key = secret_key
        self.token = None
        self.token_expire = 0
        self.base_url = "https://vop.baidu.com/server_api"
    
    async def _get_token(self) -> bool:
        """获取访问令牌"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://aip.baidubce.com/oauth/2.0/token",
                    params={
                        "grant_type": "client_credentials",
                        "client_id": self.api_key,
                        "client_secret": self.secret_key,
                    },
                )
            if response.status_code == 200:
                result = response.json()
                self.token = result.get("access_token")
                self.token_expire = time.time() + (result.get("expires_in", 3600) - 60)
                return True
            else:
                print(f"[Baidu STT] 获取 token 失败: {response.status_code}")
                return False
        except Exception as e:
            print(f"[Baidu STT] 获取 token 异常: {str(e)}")
            return False

    def _convert_to_pcm(self, file_path: Path) -> Optional[bytes]:
        """使用 pydub 将音频文件转换为 pcm 格式（百度 API 要求）"""
        try:
            from pydub import AudioSegment

            # 使用 pydub 加载音频文件（支持 webm, wav, mp3 等格式）
            audio = AudioSegment.from_file(str(file_path))

            # 转换为单声道，16000Hz，16位（百度 API 要求）
            audio = audio.set_channels(1).set_frame_rate(16000).set_sample_width(2)

            # 返回 raw PCM 数据
            return audio.raw_data

        except ImportError:
            print("[Baidu STT] 请安装 pydub: pip install pydub")
            return None
        except Exception as e:
            print(f"[Baidu STT] 音频转换异常: {str(e)}")
            return None
    
    async def transcribe(self, file_path: Path) -> Optional[str]:
        """将音频文件转换为文字"""
        try:
            # 检查并刷新 token
            if not self.token or time.time() >= self.token_expire:
                if not await self._get_token():
                    return None
            
            # 使用 ffmpeg 将音频转换为 pcm 格式（百度 API 要求）
            audio_bytes = self._convert_to_pcm(file_path)
            if audio_bytes is None:
                print("[Baidu STT] 音频格式转换失败")
                return None
            
            # 音频数据进行 base64 编码
            audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.base_url,
                    headers={"Content-Type": "application/json"},
                    json={
                        "format": "pcm",  # 使用 pcm 格式
                        "rate": 16000,
                        "channel": 1,
                        "cuid": "openharness",
                        "token": self.token,
                        "speech": audio_base64,
                        "len": len(audio_bytes),
                        "lan": "zh",
                    },
                )
            
            if response.status_code == 200:
                result = response.json()
                if result.get("err_no") == 0:
                    return result.get("result", [""])[0]
                else:
                    print(f"[Baidu STT] 识别失败: {result.get('err_msg', '未知错误')}")
                    return None
            else:
                print(f"[Baidu STT] API 错误: {response.status_code}")
                return None
        except Exception as e:
            print(f"[Baidu STT] 异常: {str(e)}")
            return None