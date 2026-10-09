// Input bar — designed to live INSIDE the SCENARIO panel at its bottom.
//
// 整改方案 §A5 / §S2 / §S5-C —
// 底部纯输入栏 + 智能建议 chips（行内紧凑布局，3 个 chip + 🔄 换一批）。
//   - "scenario"   → 多域请求，进入问诊 → workflow
//   - "specialist" → 与单个 specialist 的独立多轮对话
//
// 智能建议来源：/api/suggestions（LLM-driven，按 session 阶段给 3 条）。
// 初次访问 → 3 个引导（pre_intake）；
// 完成问诊 → 3 个追问（post_intake）。
//
// 支持插入图片和语音（语音功能预留）。

import { useState, useRef } from "react";
import { useHomeSuggestions } from "../hooks/useHomeSuggestions";

interface SpeechConfig {
  provider: 'browser' | 'baidu';
}

interface ImageAttachment {
  id: string;
  url: string;
  name: string;
  size: number;
  file: File;
  ocrText?: string;
  ocrStatus?: "idle" | "processing" | "done" | "error";
}

interface Props {
  onSend: (query: string, images?: ImageAttachment[]) => void;
  disabled?: boolean;
  placeholder?: string;
  /** "scenario" → 多域请求 | "specialist" → 独立对话 */
  mode?: "scenario" | "specialist";
  /** mode === "specialist" 时显示的智能体名。 */
  agentName?: string;
  /** S5-C — 当前 session_id（驱动智能建议 stage 变化） */
  activeSessionId?: string | null;
  /** 输入框变体: hero（大尺寸）| footer（标准尺寸） */
  variant?: "hero" | "footer";
  /** 场景模式 */
  scenarioMode?: "coordinator" | "classic";
  /** 场景模式改变回调 */
  onScenarioModeChange?: (mode: "coordinator" | "classic") => void;
}

export function InputBar({
  onSend,
  disabled,
  placeholder,
  mode = "scenario",
  agentName,
  activeSessionId = null,
  variant = "footer",
  scenarioMode = "classic",
  onScenarioModeChange,
}: Props) {
  const [text, setText] = useState("");
  const [images, setImages] = useState<ImageAttachment[]>([]);
  const [isRecording, setIsRecording] = useState(false);
  const [speechConfig, setSpeechConfig] = useState<SpeechConfig>({ provider: 'browser' });
  const [speechStatus, setSpeechStatus] = useState<string>(""); // 语音状态显示
  const fileInputRef = useRef<HTMLInputElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const recognitionRef = useRef<webkitSpeechRecognition | SpeechRecognition | null>(null);

  const suggestions = useHomeSuggestions(
    mode === "scenario" ? activeSessionId : null,
  );

  const defaultPlaceholder =
    mode === "specialist"
      ? `向 ${agentName ?? "智能体"} 提问（多轮对话，按 Enter 发送）...`
      : "输入临床问题，例如：5 岁儿童发烧 38.5°C 持续 6 小时...";

  function generateId(): string {
    return Math.random().toString(36).substring(2, 11);
  }

  function handleImageUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files;
    if (!files) return;

    const MAX_SIZE = 10 * 1024 * 1024;
    const newImages: ImageAttachment[] = [];
    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      if (!file.type.startsWith("image/")) continue;

      if (file.size > MAX_SIZE) {
        alert(`图片 ${file.name} 超过大小限制（最大 10MB）`);
        continue;
      }

      const url = URL.createObjectURL(file);
      newImages.push({
        id: generateId(),
        url,
        name: file.name,
        size: file.size,
        file,
        ocrStatus: "idle",
      });
    }

    setImages((prev) => [...prev, ...newImages]);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  }

  async function runOCR(id: string) {
    const image = images.find((img) => img.id === id);
    if (!image) return;

    setImages((prev) =>
      prev.map((img) =>
        img.id === id ? { ...img, ocrStatus: "processing" } : img
      )
    );

    try {
      const reader = new FileReader();
      reader.onloadend = async () => {
        const base64Data = reader.result as string;
        const imageData = base64Data.split(",")[1];
        const mediaType = image.file.type;

        const ocrResponse = await fetch("/api/ocr", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            image_data: imageData,
            media_type: mediaType,
          }),
        });

        const result = await ocrResponse.json();
        if (result.success) {
          setImages((prev) =>
            prev.map((img) =>
              img.id === id
                ? { ...img, ocrStatus: "done", ocrText: result.text }
                : img
            )
          );
        } else {
          throw new Error(result.text || "OCR failed");
        }
      };
      reader.readAsDataURL(image.file);
    } catch (error) {
      console.error("OCR failed:", error);
      setImages((prev) =>
        prev.map((img) =>
          img.id === id ? { ...img, ocrStatus: "error", ocrText: undefined } : img
        )
      );
      alert("OCR 处理失败，请检查后端配置。");
    }
  }

  function removeImage(id: string) {
    setImages((prev) => {
      const image = prev.find((img) => img.id === id);
      if (image) {
        URL.revokeObjectURL(image.url);
      }
      return prev.filter((img) => img.id !== id);
    });
  }

  function initBrowserRecognition() {
    if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
      const SpeechRecognition = (window as any).webkitSpeechRecognition || (window as any).SpeechRecognition;
      recognitionRef.current = new SpeechRecognition();
      recognitionRef.current.continuous = false;
      recognitionRef.current.interimResults = true;
      recognitionRef.current.lang = 'zh-CN';
      recognitionRef.current.maxAlternatives = 1;
      
      recognitionRef.current.onresult = (event: any) => {
        //alert("收到语音回调了！结果数: " + event.results.length);
        //console.log('语音识别事件触发:', event);
        
        if (!event.results || event.results.length === 0) {
          console.error('语音识别结果为空');
          return;
        }
        
        let transcript = '';
        let isFinal = false;
        
        // 遍历所有结果，支持流式输出
        for (let i = 0; i < event.results.length; i++) {
          const result = event.results[i];
          console.log('识别结果', i, ':', result);
          
          if (result[0] && result[0].transcript) {
            transcript += result[0].transcript;
          }
          
          if (result.isFinal) {
            isFinal = true;
          }
        }
        
        console.log('识别结果:', transcript, '| 最终:', isFinal);
        
        // 实时更新显示（流式输出）
        if (transcript && transcript.trim() !== '') {
          setText(transcript);
          setSpeechStatus('识别中...');
        }
        
        // 如果是最终结果，停止录音状态
        if (isFinal) {
          console.log('语音识别完成');
          setSpeechStatus('识别完成');
          setTimeout(() => setSpeechStatus(''), 2000);
          setIsRecording(false);
        }
      };
      
      recognitionRef.current.onerror = (event: any) => {
        // 核心：直接弹窗把最原始的错误码打出来
        //alert("【语音报错】错误类型: " + event.error + " | 详细事件: " + JSON.stringify(event));

        //console.error('语音识别错误:', event.error);
        let errorMsg = '语音识别失败';
        if (event.error === 'not-allowed') {
          errorMsg = '麦克风权限被拒绝，请在浏览器设置中允许麦克风访问';
        } else if (event.error === 'no-speech') {
          errorMsg = '未检测到语音输入';
        } else if (event.error === 'aborted') {
          errorMsg = '语音识别已取消';
        } else {
          errorMsg = '语音识别失败: ' + event.error;
        }
        alert(errorMsg);
        setSpeechStatus('');
        setIsRecording(false);
      };
      
      recognitionRef.current.onend = () => {
        setIsRecording(false);
      };
      
      // 添加语音识别事件监听
      recognitionRef.current.onsoundstart = () => {
        console.log('检测到声音');
        setSpeechStatus('正在听...');
      };
      
      recognitionRef.current.onspeechstart = () => {
        console.log('检测到语音开始');
        setSpeechStatus('识别中...');
      };
      
      recognitionRef.current.onspeechend = () => {
        console.log('语音结束');
        setSpeechStatus('处理中...');
      };
    }
  }
  
  function checkBrowserSpeechSupport(): boolean {
    return 'webkitSpeechRecognition' in window || 'SpeechRecognition' in window;
  }

  async function toggleVoiceRecording() {
    if (isRecording) {
      if (speechConfig.provider === 'browser') {
        recognitionRef.current?.stop();
      } else {
        mediaRecorderRef.current?.stop();
      }
      setIsRecording(false);
      return;
    }

    if (speechConfig.provider === 'browser') {
      // 检测浏览器是否支持语音识别
      if (!checkBrowserSpeechSupport()) {
        alert('当前浏览器不支持语音识别\n\n建议：\n1. 使用 Chrome 或 Safari 浏览器\n2. 或切换到 🔊G/🔊O 模式');
        return;
      }
      
      if (!recognitionRef.current) {
        initBrowserRecognition();
      }
      
      try {
        recognitionRef.current?.start();
        setIsRecording(true);
      } catch (error) {
        console.error('浏览器语音识别失败:', error);
        alert('浏览器语音识别不可用，请切换到 API 模式');
      }
    } else {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const recorder = new MediaRecorder(stream);
        mediaRecorderRef.current = recorder;
        audioChunksRef.current = [];

        recorder.ondataavailable = (event) => {
          if (event.data.size > 0) {
            audioChunksRef.current.push(event.data);
          }
        };

        recorder.onstop = async () => {
          const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
          const reader = new FileReader();
          
          reader.onloadend = async () => {
            const base64Data = reader.result as string;
            const audioData = base64Data.split(',')[1];
            
            try {
              const response = await fetch('/api/speech-to-text', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  audio_data: audioData,
                  media_type: 'audio/webm',
                  provider: speechConfig.provider
                }),
              });
              
              const result = await response.json();
              if (result.success) {
                setText(result.text);
              } else {
                alert('语音识别失败: ' + result.message);
              }
            } catch (error) {
              console.error('语音转录失败:', error);
              alert('语音转录失败');
            }
            
            stream.getTracks().forEach(track => track.stop());
          };
          
          reader.readAsDataURL(audioBlob);
        };

        recorder.start();
        setIsRecording(true);
      } catch (error) {
        console.error('无法访问麦克风:', error);
        alert('无法访问麦克风，请检查浏览器权限设置。');
      }
    }
  }

  function submit() {
    const q = text.trim();
    if (!q && images.length === 0) return;
    if (disabled) return;
    onSend(q, images.length > 0 ? images : undefined);
    setText("");
    images.forEach((img) => URL.revokeObjectURL(img.url));
    setImages([]);
  }

  function pickSuggestion(query: string) {
    if (disabled) return;
    onSend(query);
  }

  function onKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(2) + " MB";
  };

  return (
    <div style={{
      padding: "10px 14px",
      borderTop: "1px solid var(--border)",
      background: "var(--bg-soft)",
      flexShrink: 0,
    }}>
      {/* S5-C — 智能建议 chips（行内紧凑，与输入框同一容器） */}
      {mode === "scenario" && suggestions.suggestions.length > 0 && (
        <div style={{
          display: "flex", gap: 6, marginBottom: 6, flexWrap: "wrap", alignItems: "center",
        }}>
          <span style={{ fontSize: 11, color: "var(--text-faint)" }}>💡</span>
          {suggestions.suggestions.map((s, idx) => (
            <button
              key={idx}
              onClick={() => pickSuggestion(s.query)}
              disabled={disabled}
              title={s.query}
              style={{
                padding: "3px 9px", fontSize: 11,
                border: "1px solid var(--accent)",
                background: "var(--accent-soft)", color: "var(--accent-dim)",
                borderRadius: 14, cursor: disabled ? "not-allowed" : "pointer",
                display: "inline-flex", alignItems: "center", gap: 4,
                opacity: disabled ? 0.5 : 1,
              }}
            >
              <span>{s.icon}</span>
              <span>{s.label}</span>
            </button>
          ))}
          <button
            onClick={() => suggestions.refresh()}
            disabled={disabled || suggestions.loading}
            title="换一批建议"
            style={{
              padding: "2px 8px", fontSize: 10,
              background: "transparent", border: "1px solid var(--border-soft)",
              color: "var(--text-faint)", borderRadius: 12,
              cursor: suggestions.loading ? "wait" : "pointer",
              marginLeft: "auto",
            }}
          >
            {suggestions.loading ? "⟳" : "🔄"}
          </button>
        </div>
      )}

      {/* 图片预览区域 */}
      {images.length > 0 && (
        <div style={{
          display: "flex", gap: 8, marginBottom: 8, overflowX: "auto",
          padding: 4,
        }}>
          {images.map((img) => (
            <div
              key={img.id}
              style={{
                position: "relative",
                width: 80,
                flexShrink: 0,
                borderRadius: 8,
                overflow: "hidden",
                border: "1px solid var(--border)",
                background: "var(--bg)",
              }}
            >
              <img
                src={img.url}
                alt={img.name}
                style={{ width: "100%", height: 60, objectFit: "cover" }}
              />
              <div style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: 4,
                background: "var(--bg-soft)",
                borderTop: "1px solid var(--border-soft)",
              }}>
                <div style={{
                  flex: 1,
                  fontSize: 9,
                  color: "var(--text-dim)",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}>
                  {img.name}
                </div>
                <button
                  onClick={() => removeImage(img.id)}
                  style={{
                    width: 16,
                    height: 16,
                    background: "transparent",
                    color: "var(--text-faint)",
                    border: "none",
                    borderRadius: "50%",
                    fontSize: 10,
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  ×
                </button>
              </div>
              <div style={{
                display: "flex",
                gap: 2,
                padding: 2,
                background: "var(--bg)",
                borderTop: "1px solid var(--border-soft)",
              }}>
                <button
                  onClick={() => runOCR(img.id)}
                  disabled={img.ocrStatus === "processing" || disabled}
                  title={img.ocrStatus === "done" ? "重新识别" : "OCR识别"}
                  style={{
                    flex: 1,
                    padding: 2,
                    fontSize: 8,
                    background: img.ocrStatus === "done"
                      ? "var(--accent-soft)"
                      : img.ocrStatus === "processing"
                      ? "var(--bg-active)"
                      : "transparent",
                    color: img.ocrStatus === "done"
                      ? "var(--accent-dim)"
                      : img.ocrStatus === "processing"
                      ? "var(--text-faint)"
                      : "var(--text-dim)",
                    border: "1px solid var(--border-soft)",
                    borderRadius: 4,
                    cursor: disabled || img.ocrStatus === "processing"
                      ? "not-allowed"
                      : "pointer",
                  }}
                >
                  {img.ocrStatus === "processing" ? "识别中..." : img.ocrStatus === "done" ? "✓识别" : "📝OCR"}
                </button>
              </div>
              {img.ocrText && (
                <div style={{
                  padding: 4,
                  background: "var(--accent-soft)",
                  borderTop: "1px solid var(--accent)",
                  maxHeight: 80,
                  overflowY: "auto",
                }}>
                  <div style={{
                    fontSize: 9,
                    fontWeight: 600,
                    color: "var(--accent-dim)",
                    marginBottom: 2,
                  }}>
                    OCR 结果:
                  </div>
                  <div style={{
                    fontSize: 9,
                    color: "var(--text)",
                    lineHeight: 1.4,
                  }}>
                    {img.ocrText.length > 150
                      ? img.ocrText.substring(0, 150) + "..."
                      : img.ocrText}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <div style={{
        display: "flex",
        alignItems: "flex-end",
        gap: 6,
        background: "var(--bg)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-md)",
        padding: 6,
        boxShadow: disabled ? "none" : "0 1px 2px var(--accent-glow)",
        transition: "border-color 0.12s, box-shadow 0.12s",
      }}>
        {/* 工具栏按钮 */}
        <div style={{
          display: "flex",
          alignItems: "center",
          gap: 2,
          paddingRight: 4,
          borderRight: "1px solid var(--border-soft)",
        }}>
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={disabled}
            title="插入图片"
            className="icon-btn"
            style={{
              padding: "6px",
              fontSize: 16,
              color: "var(--text-dim)",
              background: "transparent",
              border: "none",
              borderRadius: "var(--radius-sm)",
              cursor: disabled ? "not-allowed" : "pointer",
            }}
          >
            📷
          </button>

<button
  onClick={() => {
    // 使用 baidu 语音识别
    const providers: ('browser' | 'baidu')[] = ['browser', 'baidu'];
    const currentProvider = (speechConfig?.provider === 'browser') ? 'browser' : 'baidu';
    const currentIndex = providers.indexOf(currentProvider);
    const nextProvider = providers[(currentIndex + 1) % providers.length];
    setSpeechConfig({ provider: nextProvider as any });
  }}
  disabled={disabled || isRecording}
  style={{
    display: "inline-block",
    width: "48px",          // 刚性宽度
    height: "24px",         // 刚性高度
    lineHeight: "22px",
    padding: "0",
    fontSize: "11px",
    fontWeight: "bold",
    background: "var(--bg-soft, #f5f5f5)",
    border: "1px solid var(--border-soft, #ddd)",
    borderRadius: "4px",
    color: "var(--accent, #0070f3)", // 用亮色，一眼就能看出来在不在
    textAlign: "center",
    cursor: disabled || isRecording ? "not-allowed" : "pointer",
  }}
>
  {/* 💡 扔掉所有喇叭 Emoji，改用最纯正的英文字母，100% 绕过广告过滤器 */}
  {speechConfig?.provider === 'browser' ? 'LIVE' : 'API'}
</button>



          <button
            onClick={toggleVoiceRecording}
            disabled={disabled}
            title={isRecording ? "停止录音" : "语音输入"}
            className="icon-btn"
            style={{
              padding: "6px",
              fontSize: 16,
              color: isRecording ? "var(--err)" : "var(--text-dim)",
              background: isRecording ? "var(--err-soft)" : "transparent",
              border: "none",
              borderRadius: "var(--radius-sm)",
              cursor: disabled ? "not-allowed" : "pointer",
              animation: isRecording ? "pulse 1s ease-in-out infinite" : "none",
            }}
          >
            🎤
          </button>
        </div>

        <span style={{
          color: "var(--accent)",
          fontSize: 14,
          padding: "4px 6px",
          alignSelf: "center",
          fontWeight: 700,
        }}>
          {mode === "specialist" ? "◈" : "▣"}
        </span>

        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKey}
          disabled={disabled}
          placeholder={placeholder ?? defaultPlaceholder}
          rows={1}
          style={{
            flex: 1,
            resize: "none",
            minHeight: 28,
            maxHeight: 120,
            border: "none",
            background: "transparent",
            padding: "4px 0",
            fontFamily: "inherit",
            fontSize: 13,
            lineHeight: 1.5,
          }}
        />

        <button
          className="primary"
          onClick={submit}
          disabled={disabled || (!text.trim() && images.length === 0)}
          style={{
            height: 34, padding: "0 18px",
            display: "flex", alignItems: "center", gap: 4,
            fontSize: 12,
            fontWeight: 600,
          }}
        >
          {disabled ? "⏵ 运行中…" : "▶ 发送"}
        </button>
        
        {/* 语音状态显示 */}
        {speechStatus && (
          <div style={{
            padding: "4px 8px",
            fontSize: 11,
            color: "var(--accent)",
            background: "var(--accent-soft)",
            borderRadius: 4,
          }}>
            🎤 {speechStatus}
          </div>
        )}
      </div>

      {/* 隐藏的文件输入 */}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        multiple
        onChange={handleImageUpload}
        style={{ display: "none" }}
      />

      <div style={{
        fontSize: 10, color: "var(--text-faint)",
        marginTop: 4, paddingLeft: 4,
        display: "flex", alignItems: "center", gap: 12,
      }}>
        <span>
          {mode === "specialist"
            ? "多轮对话 · Enter 发送 · Shift+Enter 换行"
            : "Enter 发送 · Shift+Enter 换行"}
        </span>
        <span>📷 支持图片上传</span>
        {isRecording && (
          <span style={{ color: "var(--err)", fontWeight: 600 }}>
            🎤 录音中...
          </span>
        )}
      </div>
    </div>
  );
}