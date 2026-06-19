/* ===== B站视频混剪脚本生成器 —— 前端逻辑 ===== */

// 轮询定时器
let pollTimer = null;
// 是否为预配置模式
let isPreconfigured = false;

// ------------------------------------------------------------------ //
//  初始化
// ------------------------------------------------------------------ //
document.addEventListener("DOMContentLoaded", () => {
    loadConfig();
    document.getElementById("btnToggleSettings").addEventListener("click", toggleSettings);
    document.getElementById("btnSaveConfig").addEventListener("click", saveConfig);
    document.getElementById("btnGenerate").addEventListener("click", startGenerate);
    document.getElementById("btnAdminLogin").addEventListener("click", adminLogin);
    document.getElementById("btnTestAi").addEventListener("click", testAiConnection);
});

// ------------------------------------------------------------------ //
//  设置面板
// ------------------------------------------------------------------ //
function toggleSettings() {
    const panel = document.getElementById("settingsPanel");
    panel.style.display = panel.style.display === "none" ? "block" : "none";
}

async function loadConfig() {
    try {
        const resp = await fetch("/api/config");
        const data = await resp.json();

        isPreconfigured = data.preconfigured;

        // 填充表单
        document.getElementById("aiBaseUrl").value = data.ai_base_url || "https://api.openai.com/v1";
        document.getElementById("aiModel").value = data.ai_model || "gpt-4o";
        document.getElementById("aiVisionModel").value = data.ai_vision_model || "";

        if (data.configured) {
            document.getElementById("statusBadge").style.display = "inline-block";
            document.getElementById("configStatus").textContent = "✓ 已配置";
        } else {
            document.getElementById("configStatus").textContent = "⚠ 未配置 API Key";
        }

        // 预配置模式处理
        if (data.preconfigured) {
            // 隐藏配置表单，显示预配置提示
            document.getElementById("settingsContent").style.display = "none";
            document.getElementById("preconfiguredNotice").style.display = "block";

            // 如果有管理员密码，显示登录区域
            if (data.has_admin_password) {
                document.getElementById("adminLoginArea").style.display = "block";
            }
        } else {
            // 非预配置模式：未配置时自动展开设置
            if (!data.configured) {
                document.getElementById("settingsPanel").style.display = "block";
            }
        }
    } catch (e) {
        console.error("加载配置失败:", e);
    }
}

async function adminLogin() {
    const password = document.getElementById("adminPassword").value.trim();
    if (!password) {
        alert("请输入管理员密码");
        return;
    }

    try {
        const resp = await fetch("/api/admin/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ password: password }),
        });
        const data = await resp.json();

        if (data.ok) {
            // 登录成功，显示配置表单
            document.getElementById("settingsContent").style.display = "block";
            document.getElementById("preconfiguredNotice").style.display = "none";
            document.getElementById("configStatus").textContent = "✓ 管理员已登录";
        } else {
            alert(data.error || "登录失败");
        }
    } catch (e) {
        alert("请求失败: " + e.message);
    }
}

async function saveConfig() {
    const data = {
        ai_api_key: document.getElementById("aiApiKey").value.trim(),
        ai_base_url: document.getElementById("aiBaseUrl").value.trim() || "https://api.openai.com/v1",
        ai_model: document.getElementById("aiModel").value.trim() || "gpt-4o",
        ai_vision_model: document.getElementById("aiVisionModel").value.trim(),
        bili_sessdata: document.getElementById("biliSessdata").value.trim(),
    };

    try {
        const resp = await fetch("/api/config", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        });
        const result = await resp.json();

        if (result.ok) {
            document.getElementById("configStatus").textContent = "✓ 配置已保存";
            document.getElementById("statusBadge").style.display = "inline-block";
            setTimeout(() => {
                document.getElementById("settingsPanel").style.display = "none";
            }, 1000);
        } else if (result.admin_required) {
            alert("需要管理员密码才能修改配置");
        } else {
            alert(result.error || "保存失败");
        }
    } catch (e) {
        document.getElementById("configStatus").textContent = "✗ 保存失败";
    }
}

// ------------------------------------------------------------------ //
//  AI 连接测试
// ------------------------------------------------------------------ //
async function testAiConnection() {
    const btn = document.getElementById("btnTestAi");
    const resultDiv = document.getElementById("testAiResult");

    btn.disabled = true;
    btn.textContent = "⏳ 测试中...";
    resultDiv.style.display = "block";
    resultDiv.innerHTML = '<p style="color:#6b7280;">正在测试 AI 接口连接...</p>';

    try {
        const resp = await fetch("/api/test-ai", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({}),
        });
        const data = await resp.json();

        if (data.ok) {
            resultDiv.innerHTML = `
                <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:16px;">
                    <p style="color:#166534;font-weight:600;">✓ ${data.message}</p>
                    <p style="color:#166534;font-size:13px;margin-top:8px;">模型回复：${data.reply || '(空)'}</p>
                    <p style="color:#6b7280;font-size:12px;margin-top:8px;">
                        Base URL: ${data.base_url}<br>
                        文本模型: ${data.model}<br>
                        视觉模型: ${data.vision_model}
                    </p>
                </div>`;
        } else {
            resultDiv.innerHTML = `
                <div style="background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:16px;">
                    <p style="color:#991b1b;font-weight:600;">✗ AI 接口连接失败</p>
                    <p style="color:#991b1b;font-size:13px;margin-top:8px;white-space:pre-wrap;">${data.error || '未知错误'}</p>
                    <p style="color:#6b7280;font-size:12px;margin-top:8px;">
                        Base URL: ${data.base_url || '未配置'}<br>
                        模型: ${data.model || '未配置'}<br>
                        HTTP 状态码: ${data.status_code || 'N/A'}
                    </p>
                </div>`;
        }
    } catch (e) {
        resultDiv.innerHTML = `
            <div style="background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:16px;">
                <p style="color:#991b1b;font-weight:600;">✗ 请求失败</p>
                <p style="color:#991b1b;font-size:13px;">${e.message}</p>
            </div>`;
    }

    btn.disabled = false;
    btn.textContent = "🔌 测试 AI 连接";
}

// ------------------------------------------------------------------ //
//  生成流程
// ------------------------------------------------------------------ //
async function startGenerate() {
    const url = document.getElementById("videoUrl").value.trim();
    if (!url) {
        alert("请输入 B站视频链接");
        return;
    }

    const btn = document.getElementById("btnGenerate");
    btn.disabled = true;
    btn.textContent = "⏳ 处理中...";

    // 显示进度卡片
    document.getElementById("progressCard").style.display = "block";
    document.getElementById("errorCard").style.display = "none";
    document.getElementById("resultCard").style.display = "none";
    updateProgress(0, "正在提交任务...", "pending");

    const payload = {
        url: url,
        script_topic: document.getElementById("scriptTopic").value.trim(),
        script_style: document.getElementById("scriptStyle").value.trim(),
        target_duration: document.getElementById("targetDuration").value,
        orientation: document.getElementById("orientation").value,
        extra_notes: document.getElementById("extraNotes").value.trim(),
    };

    try {
        const resp = await fetch("/api/generate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await resp.json();

        if (data.error) {
            showError(data.error);
            resetButton();
            return;
        }

        // 开始轮询状态
        pollStatus(data.task_id);
    } catch (e) {
        showError("请求失败: " + e.message);
        resetButton();
    }
}

function pollStatus(taskId) {
    pollTimer = setInterval(async () => {
        try {
            const resp = await fetch(`/api/status/${taskId}`);
            const data = await resp.json();

            if (data.error) {
                clearInterval(pollTimer);
                showError(data.error);
                resetButton();
                return;
            }

            updateProgress(data.progress || 0, data.message || "", data.status);

            if (data.status === "done") {
                clearInterval(pollTimer);
                showResult(data.result);
                resetButton();
            } else if (data.status === "error") {
                clearInterval(pollTimer);
                showError(data.message);
                resetButton();
            }
        } catch (e) {
            console.error("轮询失败:", e);
        }
    }, 1500);
}

function resetButton() {
    const btn = document.getElementById("btnGenerate");
    btn.disabled = false;
    btn.textContent = "🚀 生成混剪脚本";
}

// ------------------------------------------------------------------ //
//  进度更新
// ------------------------------------------------------------------ //
function updateProgress(progress, message, status) {
    document.getElementById("progressBar").style.width = progress + "%";
    document.getElementById("progressMessage").textContent = message;

    // 更新步骤状态
    const steps = document.querySelectorAll(".step");
    const stepOrder = ["downloading", "extracting", "analyzing", "generating"];
    const currentIdx = stepOrder.indexOf(status);

    steps.forEach((step, idx) => {
        step.classList.remove("active", "done");
        if (currentIdx === -1) return;
        if (idx < currentIdx) {
            step.classList.add("done");
        } else if (idx === currentIdx) {
            step.classList.add("active");
        }
    });

    // done 状态所有步骤完成
    if (status === "done") {
        steps.forEach(s => {
            s.classList.remove("active");
            s.classList.add("done");
        });
    }
}

// ------------------------------------------------------------------ //
//  结果展示
// ------------------------------------------------------------------ //
function showResult(result) {
    document.getElementById("resultCard").style.display = "block";

    // 下载链接
    const dlLink = document.getElementById("downloadLink");
    dlLink.href = `/download/${result.filename}`;

    // 视频信息
    const vi = result.video_info || {};
    document.getElementById("resultInfo").innerHTML = `
        <p>🎬 <strong>原视频：</strong>${vi.title || '未知'}</p>
        <p>🖼️ <strong>截取画面：</strong>${result.frame_count || 0} 帧（每隔0.5秒）</p>
        <p>📝 <strong>分镜数量：</strong>${result.script_data?.rows?.length || 0} 个镜头</p>
        <p>📄 <strong>文件名：</strong>${result.filename}</p>
    `;

    // 脚本预览
    renderScriptPreview(result.script_data);
}

function renderScriptPreview(scriptData) {
    if (!scriptData) return;

    const meta = `
        <h3>📋 脚本预览</h3>
        <div class="preview-meta">
            <div class="preview-meta-item"><strong>标题：</strong>${scriptData.title || ''}</div>
            <div class="preview-meta-item"><strong>时长：</strong>${scriptData.duration || ''}</div>
            <div class="preview-meta-item"><strong>方向：</strong>${scriptData.orientation || ''}</div>
        </div>
        <div class="preview-meta-item" style="margin-bottom:16px;">
            <strong>剪辑风格参考：</strong>${scriptData.style_reference || ''}
        </div>
    `;

    const rows = scriptData.rows || [];
    const tableRows = rows.map(r => `
        <tr>
            <td>${r.shot_number || ''}</td>
            <td>${r.post_production || ''}</td>
            <td>${r.visual_reference || ''}</td>
            <td>${r.subtitle_dialogue || ''}</td>
            <td>${r.notes || ''}</td>
        </tr>
    `).join("");

    const table = `
        <table class="preview-table">
            <thead>
                <tr>
                    <th>镜号</th>
                    <th>后期</th>
                    <th>画面参考</th>
                    <th>字幕/台词</th>
                    <th>备注</th>
                </tr>
            </thead>
            <tbody>${tableRows}</tbody>
        </table>
    `;

    document.getElementById("scriptPreview").innerHTML = meta + table;
}

// ------------------------------------------------------------------ //
//  错误展示
// ------------------------------------------------------------------ //
function showError(message) {
    document.getElementById("errorCard").style.display = "block";
    document.getElementById("errorMessage").textContent = message;
    document.getElementById("progressCard").style.display = "none";
}
