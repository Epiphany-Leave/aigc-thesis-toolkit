import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  BookOpen,
  CheckCircle2,
  FileArchive,
  FileText,
  FolderUp,
  Download,
  Pause,
  Play,
  RefreshCcw,
  Save,
  ScrollText,
  Settings,
  Sparkles,
  Square,
  UploadCloud
} from "lucide-react";
import "./styles.css";

const initialStatus = {
  project: "AIGC Thesis Toolkit",
  done: 0,
  total: 0,
  current: null,
  sections: [],
  paused: false,
  output_docx: false,
  output_md: false,
  review_report: false,
  downloads: [],
  runner: { running: false, output: [] },
  config: {},
  style: "",
  user_files: { items: [], total: 0, total_size: 0, hidden: 0 },
  preview: "",
  outline: "",
  thesis_logs: [],
  latest_log: ""
};

function escapeHtml(value) {
  return String(value || "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  })[char]);
}

function renderMarkdown(text, emptyText) {
  if (!text || !text.trim()) return `<p class="muted">${emptyText}</p>`;
  let html = "";
  let inList = false;

  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) {
      if (inList) {
        html += "</ul>";
        inList = false;
      }
      continue;
    }
    if (line.startsWith("#")) {
      if (inList) {
        html += "</ul>";
        inList = false;
      }
      const level = Math.min((line.match(/^#+/) || [""])[0].length, 4);
      html += `<h${level}>${escapeHtml(line.slice(level).trim())}</h${level}>`;
    } else if (line.startsWith("- ") || line.startsWith("* ")) {
      if (!inList) {
        html += "<ul>";
        inList = true;
      }
      html += `<li>${escapeHtml(line.slice(2).trim())}</li>`;
    } else {
      if (inList) {
        html += "</ul>";
        inList = false;
      }
      html += `<p>${escapeHtml(line)}</p>`;
    }
  }
  if (inList) html += "</ul>";
  return html;
}

function formatBytes(bytes) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(index ? 1 : 0)} ${units[index]}`;
}

async function postJson(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  return response.json();
}

function App() {
  const [status, setStatus] = useState(initialStatus);
  const [settings, setSettings] = useState(initialStatus.config);
  const [styleText, setStyleText] = useState("");
  const [notice, setNotice] = useState("");
  const [busyAction, setBusyAction] = useState("");
  const [activeTab, setActiveTab] = useState("preview");
  const [autoPreview, setAutoPreview] = useState(true);
  const previewRef = useRef(null);
  const fileInputRef = useRef(null);
  const folderInputRef = useRef(null);
  const styleFileRef = useRef(null);

  const progress = status.total ? Math.round((status.done / status.total) * 100) : 0;
  const currentName = status.current?.subsection_title || status.current?.title || "无";
  const runnerOutput = status.runner?.output || [];

  async function refresh({ keepForms = true } = {}) {
    const response = await fetch("/api/status");
    const data = await response.json();
    setStatus(data);
    if (!keepForms) {
      setSettings(data.config || {});
      setStyleText(data.style || "");
    }
  }

  useEffect(() => {
    refresh({ keepForms: false });
    const timer = setInterval(() => refresh({ keepForms: true }), 5000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (autoPreview && previewRef.current) {
      previewRef.current.scrollTop = previewRef.current.scrollHeight;
    }
  }, [status.preview, activeTab, autoPreview]);

  const previewHtml = useMemo(
    () => renderMarkdown(status.preview, "暂无已生成正文。开始生成后会在这里实时出现。"),
    [status.preview]
  );
  const outlineHtml = useMemo(
    () => renderMarkdown(status.outline, "暂无大纲。点击“重建大纲”后会在这里显示。"),
    [status.outline]
  );

  function updateSetting(name, value) {
    setSettings((current) => ({ ...current, [name]: value }));
  }

  async function saveSettings(event) {
    event.preventDefault();
    const result = await postJson("/api/settings", settings);
    setNotice(result.message || "配置已保存。");
    await refresh({ keepForms: false });
  }

  async function saveStyle(event) {
    event.preventDefault();
    const result = await postJson("/api/style", { style: styleText });
    setNotice(result.message || "写作规范已保存。");
    await refresh({ keepForms: false });
  }

  async function runAction(cmd) {
    setBusyAction(cmd);
    const result = await postJson("/api/action", { cmd });
    setNotice(result.message || "操作已提交。");
    setBusyAction("");
    await refresh({ keepForms: true });
  }

  async function uploadFiles(event) {
    event.preventDefault();
    const form = new FormData();
    let count = 0;
    for (const input of [fileInputRef.current, folderInputRef.current]) {
      for (const file of input?.files || []) {
        form.append("files", file, file.webkitRelativePath || file.name);
        count += 1;
      }
    }
    if (!count) {
      setNotice("请先选择文件或文件夹。");
      return;
    }
    const response = await fetch("/api/upload", { method: "POST", body: form });
    const result = await response.json();
    setNotice(result.message || "上传完成。");
    fileInputRef.current.value = "";
    folderInputRef.current.value = "";
    await refresh({ keepForms: true });
  }

  async function uploadStyle(event) {
    event.preventDefault();
    const file = styleFileRef.current?.files?.[0];
    if (!file) {
      setNotice("请先选择写作规范文件。");
      return;
    }
    const form = new FormData();
    form.append("style_file", file, file.name);
    const response = await fetch("/api/style-upload", { method: "POST", body: form });
    const result = await response.json();
    setNotice(result.message || "写作规范已导入。");
    styleFileRef.current.value = "";
    await refresh({ keepForms: false });
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><Sparkles size={22} /></div>
          <div>
            <h1>AIGC Thesis Toolkit</h1>
            <p>{status.project || "本地论文工作台"}</p>
          </div>
        </div>

        <div className="progress-card">
          <div className="progress-top">
            <span>总体进度</span>
            <strong>{progress}%</strong>
          </div>
          <div className="progress-bar"><span style={{ width: `${progress}%` }} /></div>
          <div className="progress-meta">{status.done}/{status.total} 写作单元</div>
        </div>

        <nav className="nav">
          <button className={activeTab === "preview" ? "active" : ""} onClick={() => setActiveTab("preview")}><BookOpen size={18} />论文预览</button>
          <button className={activeTab === "outline" ? "active" : ""} onClick={() => setActiveTab("outline")}><ScrollText size={18} />大纲</button>
          <button className={activeTab === "plan" ? "active" : ""} onClick={() => setActiveTab("plan")}><Activity size={18} />写作计划</button>
          <button className={activeTab === "logs" ? "active" : ""} onClick={() => setActiveTab("logs")}><FileText size={18} />任务输出</button>
          <button className={activeTab === "files" ? "active" : ""} onClick={() => setActiveTab("files")}><Download size={18} />导出与日志</button>
        </nav>

        <div className="status-pills">
          <span className={status.runner?.running ? "pill running" : "pill"}>{status.runner?.running ? "运行中" : "空闲"}</span>
          <span className={status.paused ? "pill paused" : "pill"}>{status.paused ? "已暂停" : "未暂停"}</span>
          <span className="pill">{currentName}</span>
        </div>
      </aside>

      <main className="main">
        {notice && <div className="notice"><CheckCircle2 size={18} />{notice}</div>}

        <section className="command-strip">
          <button className="primary" onClick={() => runAction("all")} disabled={status.runner?.running || busyAction}><Play size={17} />开始完整流程</button>
          <button onClick={() => runAction("generate")} disabled={status.runner?.running || busyAction}><RefreshCcw size={17} />继续生成</button>
          <button onClick={() => runAction("pause")} disabled={busyAction}><Pause size={17} />暂停</button>
          <button onClick={() => runAction("resume")} disabled={busyAction}><Play size={17} />继续</button>
          <button onClick={() => runAction("style")} disabled={status.runner?.running || busyAction}>自动规范</button>
          <button onClick={() => runAction("resources")} disabled={status.runner?.running || busyAction}>资料索引</button>
          <button onClick={() => runAction("outline")} disabled={status.runner?.running || busyAction}>重建大纲</button>
          <button onClick={() => runAction("plan")} disabled={status.runner?.running || busyAction}>写作计划</button>
          <button onClick={() => runAction("build")} disabled={status.runner?.running || busyAction}>构建 Word</button>
          <button onClick={() => runAction("review")} disabled={status.runner?.running || busyAction}>论文 Review</button>
          <button className="danger" onClick={() => runAction("shutdown")}><Square size={15} />关闭 WebUI</button>
        </section>

        <section className="dashboard">
          <div className="left-column">
            <Panel title="项目配置" icon={<Settings size={18} />}>
              <form className="form-grid" onSubmit={saveSettings}>
                <label>论文题目<input value={settings.title || ""} onChange={(e) => updateSetting("title", e.target.value)} /></label>
                <label>API Base<input value={settings.api_base || ""} onChange={(e) => updateSetting("api_base", e.target.value)} /></label>
                <label>模型<input value={settings.model || ""} onChange={(e) => updateSetting("model", e.target.value)} /></label>
                <label>API Key<input type="password" value={settings.api_key || ""} onChange={(e) => updateSetting("api_key", e.target.value)} /></label>
                <label>生成粒度
                  <select value={settings.granularity || "chapter"} onChange={(e) => updateSetting("granularity", e.target.value)}>
                    <option value="chapter">按章高质量生成</option>
                    <option value="subsection">按小节省 token 生成</option>
                  </select>
                </label>
                <label>间隔秒数<input value={settings.sleep_seconds ?? 3} onChange={(e) => updateSetting("sleep_seconds", e.target.value)} /></label>
                <label>请求超时<input value={settings.request_timeout_seconds ?? 300} onChange={(e) => updateSetting("request_timeout_seconds", e.target.value)} /></label>
                <label>本轮最多<input value={settings.max_sections_per_run ?? 0} onChange={(e) => updateSetting("max_sections_per_run", e.target.value)} /></label>
                <div className="form-actions"><button className="primary"><Save size={16} />保存配置</button></div>
              </form>
            </Panel>

            <Panel title="资料导入" icon={<FolderUp size={18} />}>
              <form className="upload-layout" onSubmit={uploadFiles}>
                <div className="drop-zone">
                  <UploadCloud size={34} />
                  <strong>导入论文资料</strong>
                  <span>可同时选择零散文件和整个文件夹，完成后会提示导入结果。</span>
                </div>
                <div className="upload-inputs">
                  <label>选择文件<input ref={fileInputRef} type="file" multiple /></label>
                  <label>选择文件夹<input ref={folderInputRef} type="file" webkitdirectory="true" directory="" multiple /></label>
                </div>
                <div className="examples">
                  <span>开题报告</span><span>学校规范</span><span>参考论文</span><span>仿真数据</span><span>实验表格</span><span>原理图</span>
                </div>
                <button className="primary"><UploadCloud size={16} />上传资料</button>
              </form>
              <div className="file-summary">
                <FileArchive size={17} />已有 {status.user_files.total} 个文件，约 {formatBytes(status.user_files.total_size)}
              </div>
              <div className="mini-file-list">
                {(status.user_files.items || []).map((file) => <span key={file.path}>{file.path}</span>)}
                {status.user_files.hidden > 0 && <strong>还有 {status.user_files.hidden} 个文件未展开显示</strong>}
              </div>
            </Panel>

            <Panel title="写作规范" icon={<FileText size={18} />}>
              <form onSubmit={saveStyle}>
                <textarea className="style-editor" value={styleText} onChange={(e) => setStyleText(e.target.value)} />
                <div className="split-actions">
                  <button className="primary"><Save size={16} />保存规范</button>
                </div>
              </form>
              <form className="style-upload" onSubmit={uploadStyle}>
                <input ref={styleFileRef} type="file" />
                <button><UploadCloud size={16} />导入 style.md</button>
              </form>
            </Panel>
          </div>

          <div className="right-column">
            {activeTab === "preview" && (
              <Panel title="实时论文预览" icon={<BookOpen size={18} />} aside={
                <label className="toggle"><input type="checkbox" checked={autoPreview} onChange={(e) => setAutoPreview(e.target.checked)} />自动滚动</label>
              }>
                <article ref={previewRef} className="reader" dangerouslySetInnerHTML={{ __html: previewHtml }} />
              </Panel>
            )}
            {activeTab === "outline" && (
              <Panel title="论文大纲" icon={<ScrollText size={18} />}>
                <article className="reader outline-reader" dangerouslySetInnerHTML={{ __html: outlineHtml }} />
              </Panel>
            )}
            {activeTab === "plan" && (
              <Panel title="写作计划" icon={<Activity size={18} />}>
                <div className="plan-table">
                  {(status.sections || []).map((item) => (
                    <div className="plan-row" key={item.id}>
                      <span className={`state ${item.status || "pending"}`}>{item.status || "pending"}</span>
                      <strong>{item.chapter_title || item.title}</strong>
                      <span>{item.subsection_title || item.title}</span>
                      <code>{item.file}</code>
                    </div>
                  ))}
                  {(!status.sections || status.sections.length === 0) && <p className="muted">尚未生成写作计划。</p>}
                </div>
              </Panel>
            )}
            {activeTab === "logs" && (
              <Panel title="任务输出" icon={<FileText size={18} />}>
                <pre className="logs">{runnerOutput.length ? runnerOutput.join("\n") : "暂无输出"}</pre>
              </Panel>
            )}
            {activeTab === "files" && (
              <Panel title="导出与日志" icon={<Download size={18} />}>
                <div className="download-grid">
                  {(status.downloads || []).map((item) => (
                    <a className="download-card" href={item.url} key={item.url}>
                      <Download size={18} />
                      <strong>{item.name}</strong>
                      <span>{formatBytes(item.size)}</span>
                    </a>
                  ))}
                  {(!status.downloads || status.downloads.length === 0) && <p className="muted">暂无可导出文件。请先构建 Word 或运行 Review。</p>}
                </div>
                <div className="log-list">
                  <h3>论文日志</h3>
                  {(status.thesis_logs || []).map((item) => (
                    <span key={item.name}>{item.name} · {formatBytes(item.size)}</span>
                  ))}
                  {(!status.thesis_logs || status.thesis_logs.length === 0) && <p className="muted">暂无 thesis/logs 日志。</p>}
                </div>
                <pre className="logs compact">{status.latest_log || "暂无日志内容"}</pre>
              </Panel>
            )}
          </div>
        </section>
      </main>
    </div>
  );
}

function Panel({ title, icon, aside, children }) {
  return (
    <section className="panel">
      <div className="panel-heading">
        <h2>{icon}{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

createRoot(document.getElementById("root")).render(<App />);
