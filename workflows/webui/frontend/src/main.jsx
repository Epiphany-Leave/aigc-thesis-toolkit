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
  Presentation,
  RefreshCcw,
  Save,
  ScrollText,
  Settings,
  Settings2,
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
  latest_log: "",
  review_progress: { active: false, done: 0, total: 0, percent: 0, label: "" },
  ppt: { progress: { active: false, done: 0, total: 0, percent: 0, label: "" }, outline: "", preview: "", plan: {}, sources: [], templates: [], output: false }
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
  const [dragActive, setDragActive] = useState(false);
  const [pptDragActive, setPptDragActive] = useState(false);
  const [pptTemplateDragActive, setPptTemplateDragActive] = useState(false);
  const [pptStyle, setPptStyle] = useState("infographic");
  const [pptRenderMode, setPptRenderMode] = useState("editable");
  const [pptSource, setPptSource] = useState("");
  const [pptTemplate, setPptTemplate] = useState("");
  const [configOpen, setConfigOpen] = useState(false);
  const previewRef = useRef(null);
  const fileInputRef = useRef(null);
  const folderInputRef = useRef(null);
  const styleFileRef = useRef(null);
  const pptInputRef = useRef(null);
  const pptTemplateInputRef = useRef(null);

  const progress = status.total ? Math.round((status.done / status.total) * 100) : 0;
  const reviewProgress = status.review_progress || initialStatus.review_progress;
  const pptState = status.ppt || initialStatus.ppt;
  const pptProgress = pptState.progress || initialStatus.ppt.progress;
  const currentName = status.current?.subsection_title || status.current?.title || "无";
  const runnerOutput = status.runner?.output || [];
  const displayProject = status.project && status.project !== "你的论文题目" ? status.project : "AIGC Thesis Toolkit";

  function dragHasFiles(event) {
    return Array.from(event.dataTransfer?.types || []).includes("Files");
  }

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
    function preventFileOpen(event) {
      if (!dragHasFiles(event)) return;
      event.preventDefault();
      if (event.type === "dragenter" || event.type === "dragover") {
        setDragActive(true);
      }
      if (event.type === "drop") {
        setDragActive(false);
        if (!event.defaultPrevented) {
          setNotice("请把文件拖入“资料导入”窗口。");
        }
      }
    }
    function handleWindowDragLeave(event) {
      if (event.clientX <= 0 || event.clientY <= 0 || event.clientX >= window.innerWidth || event.clientY >= window.innerHeight) {
        setDragActive(false);
      }
    }
    window.addEventListener("dragenter", preventFileOpen);
    window.addEventListener("dragover", preventFileOpen);
    window.addEventListener("drop", preventFileOpen);
    window.addEventListener("dragleave", handleWindowDragLeave);
    return () => {
      window.removeEventListener("dragenter", preventFileOpen);
      window.removeEventListener("dragover", preventFileOpen);
      window.removeEventListener("drop", preventFileOpen);
      window.removeEventListener("dragleave", handleWindowDragLeave);
    };
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

  const pptOutlineHtml = useMemo(
    () => renderMarkdown(pptState.outline, "暂无 PPT 大纲。导入论文源或使用已生成论文后，点击生成 PPT。"),
    [pptState.outline]
  );
  const pptPreviewHtml = useMemo(
    () => renderMarkdown(pptState.preview, "暂无 PPT 预览。生成后会显示每页要点、图解建议和讲稿提示。"),
    [pptState.preview]
  );

  function updateSetting(name, value) {
    setSettings((current) => ({ ...current, [name]: value }));
  }

  async function saveSettingsPayload(payload = settings) {
    const result = await postJson("/api/settings", payload);
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

  async function runPptGenerate(source = "") {
    setBusyAction("ppt");
    const result = await postJson("/api/ppt-generate", { style: pptStyle, source, template: pptTemplate, render_mode: pptRenderMode });
    setNotice(result.message || "PPT 生成已提交。");
    setBusyAction("");
    await refresh({ keepForms: true });
  }

  async function uploadPptEntries(entries) {
    const form = new FormData();
    for (const entry of entries) {
      form.append("files", entry.file, entry.file.name);
    }
    if (!entries.length) {
      setNotice("请先选择一个 md、docx、pdf 或 txt 论文文件。");
      return;
    }
    const response = await fetch("/api/ppt-upload", { method: "POST", body: form });
    const result = await response.json();
    setNotice(result.message || "PPT 论文源已导入。");
    if (result.source) setPptSource(result.source);
    if (pptInputRef.current) pptInputRef.current.value = "";
    await refresh({ keepForms: true });
  }

  async function uploadPptSource(event) {
    event.preventDefault();
    const entries = Array.from(pptInputRef.current?.files || []).map((file) => ({ file, path: file.name }));
    await uploadPptEntries(entries);
  }

  async function handlePptDrop(event) {
    event.preventDefault();
    event.stopPropagation();
    setPptDragActive(false);
    const files = Array.from(event.dataTransfer.files || []).map((file) => ({ file, path: file.name }));
    await uploadPptEntries(files);
  }

  async function uploadPptTemplateEntries(entries) {
    const form = new FormData();
    for (const entry of entries) {
      form.append("files", entry.file, entry.file.name);
    }
    if (!entries.length) {
      setNotice("请先选择一个 ppt 或 pptx 参考 PPT。");
      return;
    }
    const response = await fetch("/api/ppt-template-upload", { method: "POST", body: form });
    const result = await response.json();
    setNotice(result.message || "参考 PPT 已导入。");
    if (result.saved > 1) setPptTemplate("__all__");
    else if (result.template) setPptTemplate(result.template);
    if (pptTemplateInputRef.current) pptTemplateInputRef.current.value = "";
    await refresh({ keepForms: true });
  }

  async function uploadPptTemplate(event) {
    event.preventDefault();
    const entries = Array.from(pptTemplateInputRef.current?.files || []).map((file) => ({ file, path: file.name }));
    await uploadPptTemplateEntries(entries);
  }

  async function handlePptTemplateDrop(event) {
    event.preventDefault();
    event.stopPropagation();
    setPptTemplateDragActive(false);
    const files = Array.from(event.dataTransfer.files || []).map((file) => ({ file, path: file.name }));
    await uploadPptTemplateEntries(files);
  }

  async function uploadFileEntries(entries) {
    const form = new FormData();
    for (const entry of entries) {
      form.append("files", entry.file, entry.path || entry.file.webkitRelativePath || entry.file.name);
    }
    if (!entries.length) {
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

  async function uploadFiles(event) {
    event.preventDefault();
    const entries = [];
    for (const input of [fileInputRef.current, folderInputRef.current]) {
      for (const file of input?.files || []) {
        entries.push({ file, path: file.webkitRelativePath || file.name });
      }
    }
    await uploadFileEntries(entries);
  }

  function readEntryFile(entry, pathPrefix = "") {
    return new Promise((resolve) => {
      if (entry.isFile) {
        entry.file((file) => resolve([{ file, path: `${pathPrefix}${file.name}` }]), () => resolve([]));
        return;
      }
      if (!entry.isDirectory) {
        resolve([]);
        return;
      }
      const reader = entry.createReader();
      const children = [];
      const readBatch = () => {
        reader.readEntries(async (batch) => {
          if (!batch.length) {
            const nested = await Promise.all(children.map((child) => readEntryFile(child, `${pathPrefix}${entry.name}/`)));
            resolve(nested.flat());
            return;
          }
          children.push(...batch);
          readBatch();
        }, () => resolve([]));
      };
      readBatch();
    });
  }

  async function collectDroppedFiles(dataTransfer) {
    const itemEntries = [];
    for (const item of dataTransfer.items || []) {
      const entry = item.webkitGetAsEntry?.();
      if (entry) itemEntries.push(entry);
    }
    if (itemEntries.length) {
      const nested = await Promise.all(itemEntries.map((entry) => readEntryFile(entry)));
      return nested.flat();
    }
    return Array.from(dataTransfer.files || []).map((file) => ({ file, path: file.webkitRelativePath || file.name }));
  }

  async function handleDrop(event) {
    event.preventDefault();
    event.stopPropagation();
    setDragActive(false);
    const entries = await collectDroppedFiles(event.dataTransfer);
    await uploadFileEntries(entries);
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
            <p>{status.project && status.project !== "你的论文题目" ? status.project : "本地论文写作工作台"}</p>
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
        {reviewProgress.active && (
          <div className="progress-card review-progress">
            <div className="progress-top">
              <span>Review 修订进度</span>
              <strong>{reviewProgress.percent || 0}%</strong>
            </div>
            <div className="progress-bar"><span style={{ width: `${reviewProgress.percent || 0}%` }} /></div>
            <div className="progress-meta">{reviewProgress.done || 0}/{reviewProgress.total || 0} 检测分块</div>
            {reviewProgress.label && <div className="progress-meta">{reviewProgress.label}</div>}
          </div>
        )}

        <nav className="nav">
          <button className={activeTab === "ppt" ? "active" : ""} onClick={() => setActiveTab("ppt")}><Presentation size={18} />PPT 生成</button>
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
        <header className="topbar">
          <div>
            <strong>{displayProject}</strong>
            <span>资料、写作、Review 与导出工作台</span>
          </div>
          <div className="topbar-actions">
            <button className="ghost-btn" type="button" onClick={() => setConfigOpen(true)}>
              <Settings2 size={16} />配置中心
            </button>
            <span className={status.runner?.running ? "status-pill busy" : "status-pill"}>
              {status.runner?.running ? "运行中" : "空闲"}
            </span>
          </div>
        </header>

        {notice && <div className="notice"><CheckCircle2 size={18} />{notice}</div>}

        <section className="command-strip">
          <button className="primary" onClick={() => runAction("all")} disabled={status.runner?.running || busyAction}><Play size={17} />开始完整流程</button>
          <button onClick={() => runAction("generate")} disabled={status.runner?.running || busyAction}><RefreshCcw size={17} />继续生成</button>
          <button onClick={() => runAction("pause")} disabled={busyAction}><Pause size={17} />暂停</button>
          <button onClick={() => runAction("resume")} disabled={busyAction}><Play size={17} />继续</button>
          <button onClick={() => runAction("style")} disabled={status.runner?.running || busyAction}>自动规范</button>
          <button onClick={() => runAction("resources")} disabled={status.runner?.running || busyAction}>资料索引</button>
          <button onClick={() => runAction("references")} disabled={status.runner?.running || busyAction}>参考文献</button>
          <button onClick={() => runAction("outline")} disabled={status.runner?.running || busyAction}>重建大纲</button>
          <button onClick={() => runAction("plan")} disabled={status.runner?.running || busyAction}>写作计划</button>
          <button onClick={() => runAction("build")} disabled={status.runner?.running || busyAction}>构建 Word</button>
          <button onClick={() => runAction("review")} disabled={status.runner?.running || busyAction}>Review 并导出</button>
          <button className="danger" onClick={() => window.confirm("确认清空 user_data、生成章节、输出文件和日志？API 配置会保留。") && runAction("reset")} disabled={status.runner?.running || busyAction}>一键重置</button>
          <button className="danger" onClick={() => runAction("shutdown")}><Square size={15} />关闭 WebUI</button>
        </section>

        <section className={`dashboard ${activeTab === "ppt" ? "ppt-dashboard" : ""}`}>
          {activeTab !== "ppt" && <div className="left-column">
            <Panel title="资料导入" icon={<FolderUp size={18} />}>
              <form
                className="upload-layout"
                onSubmit={uploadFiles}
                onDragEnter={(event) => { if (dragHasFiles(event)) { event.preventDefault(); setDragActive(true); } }}
                onDragOver={(event) => { if (dragHasFiles(event)) { event.preventDefault(); setDragActive(true); } }}
                onDrop={handleDrop}
              >
                <div
                  className={`drop-zone ${dragActive ? "drag-active" : ""}`}
                  role="button"
                  tabIndex="0"
                  onClick={() => fileInputRef.current?.click()}
                  onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") fileInputRef.current?.click(); }}
                  onDragEnter={(event) => { if (dragHasFiles(event)) { event.preventDefault(); setDragActive(true); } }}
                  onDragOver={(event) => { if (dragHasFiles(event)) { event.preventDefault(); setDragActive(true); } }}
                  onDragLeave={(event) => { event.preventDefault(); setDragActive(false); }}
                  onDrop={handleDrop}
                >
                  <UploadCloud size={34} />
                  <strong>拖拽文件或文件夹到这里</strong>
                  <span>也可以用下方按钮选择。支持 Markdown/TXT/CSV/DOC/DOCX/XLSX/BibTeX/PDF/图片，系统会尽量抽取文本、OCR 或恢复可读字符串。</span>
                  <div className="drop-actions">
                    <button type="button" onClick={(event) => { event.stopPropagation(); fileInputRef.current?.click(); }}>选择文件</button>
                    <button type="button" onClick={(event) => { event.stopPropagation(); folderInputRef.current?.click(); }}>选择文件夹</button>
                  </div>
                </div>
                <div className="upload-inputs">
                  <input ref={fileInputRef} type="file" multiple />
                  <input ref={folderInputRef} type="file" webkitdirectory="true" directory="" multiple />
                </div>
                <div className="examples">
                  <span>任务书/开题报告 DOC/DOCX</span><span>学校规范 TXT/MD/PDF</span><span>参考文献 BibTeX</span><span>实验数据 CSV/XLSX</span><span>仿真结果表格</span><span>硬件参数说明 MD</span>
                </div>
                <p className="muted">可复制文本的 PDF、老版 DOC 和清晰图片会尝试自动抽取；扫描件、复杂原理图和工程文件仍建议配套上传参数说明、测试数据和图表含义。</p>
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
          </div>}

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
            {activeTab === "ppt" && (
              <Panel title="PPT 生成" icon={<Presentation size={18} />}>
                <div className="ppt-workspace">
                  <div className="ppt-controls">
                    <form
                      className={`drop-zone ppt-drop-zone ${pptDragActive ? "drag-active" : ""}`}
                      onSubmit={uploadPptSource}
                      onDragEnter={(event) => { if (dragHasFiles(event)) { event.preventDefault(); setPptDragActive(true); } }}
                      onDragOver={(event) => { if (dragHasFiles(event)) { event.preventDefault(); setPptDragActive(true); } }}
                      onDragLeave={(event) => { event.preventDefault(); setPptDragActive(false); }}
                      onDrop={handlePptDrop}
                    >
                      <UploadCloud size={30} />
                      <strong>导入外部论文源</strong>
                      <span>支持 md、docx、pdf、txt；也可以不导入，直接使用 output/thesis.md。</span>
                      <input ref={pptInputRef} type="file" accept=".md,.markdown,.docx,.pdf,.txt" multiple />
                      <button type="submit"><UploadCloud size={16} />上传论文源</button>
                    </form>
                    <form
                      className={`drop-zone ppt-drop-zone ${pptTemplateDragActive ? "drag-active" : ""}`}
                      onSubmit={uploadPptTemplate}
                      onDragEnter={(event) => { if (dragHasFiles(event)) { event.preventDefault(); setPptTemplateDragActive(true); } }}
                      onDragOver={(event) => { if (dragHasFiles(event)) { event.preventDefault(); setPptTemplateDragActive(true); } }}
                      onDragLeave={(event) => { event.preventDefault(); setPptTemplateDragActive(false); }}
                      onDrop={handlePptTemplateDrop}
                    >
                      <FileArchive size={30} />
                      <strong>导入参考 PPT</strong>
                      <span>支持多个 pptx；安装 LibreOffice 后可尝试 ppt。只分析布局、色彩和母版结构，不复用文字与图片内容。</span>
                      <input ref={pptTemplateInputRef} type="file" accept=".ppt,.pptx" multiple />
                      <button type="submit"><UploadCloud size={16} />上传参考 PPT</button>
                    </form>
                    <div className="ppt-option-grid">
                      <label>视觉预设
                        <select value={pptStyle} onChange={(event) => setPptStyle(event.target.value)}>
                          <option value="infographic">Infographic 信息图</option>
                          <option value="excalidraw">Excalidraw 手绘图解</option>
                          <option value="architecture">Architecture 架构图</option>
                        </select>
                      </label>
                      <label>PPT 渲染模式
                        <select value={pptRenderMode} onChange={(event) => setPptRenderMode(event.target.value)}>
                          <option value="editable">可编辑 PPT 元素</option>
                          <option value="image_slide">整页 AI 图片</option>
                        </select>
                      </label>
                      <label>已导入论文源
                        <select value={pptSource} onChange={(event) => setPptSource(event.target.value)}>
                          <option value="">使用 output/thesis.md</option>
                          {(pptState.sources || []).map((item) => (
                            <option key={item.path} value={item.path}>{item.name}</option>
                          ))}
                        </select>
                      </label>
                      <label>参考 PPT 设计
                        <select value={pptTemplate} onChange={(event) => setPptTemplate(event.target.value)}>
                          <option value="">使用默认设计</option>
                          {(pptState.templates || []).length > 1 && <option value="__all__">使用全部参考 PPT</option>}
                          {(pptState.templates || []).map((item) => (
                            <option key={item.path} value={item.path}>{item.name}</option>
                          ))}
                        </select>
                      </label>
                    </div>
                    <div className="split-actions">
                      <button className="primary" onClick={() => runPptGenerate(pptSource)} disabled={status.runner?.running || busyAction} type="button">
                        <Presentation size={16} />生成 PPT
                      </button>
                      <button onClick={() => runPptGenerate("")} disabled={status.runner?.running || busyAction} type="button">
                        使用已生成论文
                      </button>
                    </div>
                    <div className="progress-card ppt-progress-card">
                      <div className="progress-top">
                        <span>PPT 生成进度</span>
                        <strong>{pptProgress.percent || 0}%</strong>
                      </div>
                      <div className="progress-bar"><span style={{ width: `${pptProgress.percent || 0}%` }} /></div>
                      <div className="progress-meta">{pptProgress.done || 0}/{pptProgress.total || 0} 页 {pptProgress.label || ""}</div>
                    </div>
                    {pptState.output && (
                      <a className="download-card" href="/download/thesis_presentation.pptx">
                        <Download size={18} />
                        <strong>thesis_presentation.pptx</strong>
                        <span>下载答辩 PPT</span>
                      </a>
                    )}
                  </div>
                  <div className="ppt-preview-grid">
                    <div className="ppt-live-status">
                      <strong>当前生成</strong>
                      <span>{pptProgress.label || (pptProgress.active ? "正在生成页面计划" : "等待开始")}</span>
                    </div>
                    <div className="ppt-slide-list">
                      {((pptState.plan && pptState.plan.slides) || []).map((slide, index) => (
                        <div className={`ppt-slide-item ${index < (pptProgress.done || 0) ? "done" : ""}`} key={`${slide.title}-${index}`}>
                          <span>{index + 1}</span>
                          <strong>{slide.title}</strong>
                          <small>{(slide.bullets || []).slice(0, 2).join(" / ")}</small>
                        </div>
                      ))}
                      {(!pptState.plan || !pptState.plan.slides || pptState.plan.slides.length === 0) && (
                        <p className="muted">PPT 计划生成后，这里会实时显示每一页的标题和要点。</p>
                      )}
                    </div>
                    <article className="reader ppt-reader" dangerouslySetInnerHTML={{ __html: pptOutlineHtml }} />
                    <article className="reader ppt-reader" dangerouslySetInnerHTML={{ __html: pptPreviewHtml }} />
                  </div>
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
        {configOpen && (
          <ConfigDrawer
            settings={settings}
            setSettings={setSettings}
            onClose={() => setConfigOpen(false)}
            onSave={(payload) => saveSettingsPayload(payload)}
          />
        )}
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

function ConfigDrawer({ settings, setSettings, onClose, onSave }) {
  const [draft, setDraft] = useState(() => ({ ...settings }));

  function setField(name, value) {
    setDraft((current) => ({ ...current, [name]: value }));
  }

  async function submit() {
    setSettings(draft);
    await onSave(draft);
    onClose();
  }

  return (
    <div className="drawer-backdrop" onMouseDown={onClose}>
      <aside className="config-drawer" onMouseDown={(event) => event.stopPropagation()}>
        <div className="drawer-head">
          <div>
            <h2>配置中心</h2>
            <p>API、模型和质量优先运行参数集中在这里。</p>
          </div>
          <button className="icon-btn" type="button" onClick={onClose}>×</button>
        </div>

        <div className="drawer-section">
          <h3>论文项目</h3>
          <label>论文题目<input value={draft.title || ""} onChange={(event) => setField("title", event.target.value)} /></label>
        </div>

        <div className="drawer-section">
          <h3>生成 API</h3>
          <label>API Base<input value={draft.api_base || ""} onChange={(event) => setField("api_base", event.target.value)} /></label>
          <label>API Key<input type="password" value={draft.api_key || ""} onChange={(event) => setField("api_key", event.target.value)} /></label>
          <label>模型<input value={draft.model || ""} onChange={(event) => setField("model", event.target.value)} /></label>
        </div>

        <div className="drawer-section">
          <h3>PPT 图像 API</h3>
          <label>Image API Base<input value={draft.ppt_image_api_base || ""} placeholder="https://api.openai.com/v1" onChange={(event) => setField("ppt_image_api_base", event.target.value)} /></label>
          <label>Image API Key<input type="password" value={draft.ppt_image_api_key || ""} onChange={(event) => setField("ppt_image_api_key", event.target.value)} /></label>
          <label>Image Model<input value={draft.ppt_image_model || ""} placeholder="gpt-image-1" onChange={(event) => setField("ppt_image_model", event.target.value)} /></label>
          <label>Image Size<input value={draft.ppt_image_size || "1536x1024"} placeholder="1536x1024" onChange={(event) => setField("ppt_image_size", event.target.value)} /></label>
          <p className="drawer-note">仅在 PPT 渲染模式选择“整页 AI 图片”时使用。</p>
        </div>

        <div className="drawer-section">
          <h3>质量优先参数</h3>
          <label>生成粒度
            <select value={draft.granularity || "chapter"} onChange={(event) => setField("granularity", event.target.value)}>
              <option value="chapter">按章高质量生成</option>
              <option value="subsection">按小节稳定生成</option>
            </select>
          </label>
          <div className="drawer-grid">
            <label>请求超时<input value={draft.request_timeout_seconds ?? 600} onChange={(event) => setField("request_timeout_seconds", event.target.value)} /></label>
            <label>间隔秒数<input value={draft.sleep_seconds ?? 3} onChange={(event) => setField("sleep_seconds", event.target.value)} /></label>
            <label>本轮最多<input value={draft.max_sections_per_run ?? 0} onChange={(event) => setField("max_sections_per_run", event.target.value)} /></label>
          </div>
          <p className="drawer-note">0 表示完整流程会串行完成所有未生成单元；暂停按钮会在当前单元结束后生效。</p>
        </div>

        <button className="primary drawer-save" type="button" onClick={submit}>
          <Save size={16} />保存配置
        </button>
      </aside>
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
