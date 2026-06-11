async function jsonFetch(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || payload.error || response.statusText);
  }
  return payload;
}

const searchForm = document.querySelector("#search-form");
if (searchForm) {
  searchForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = document.querySelector("#search-status");
    const results = document.querySelector("#results");
    status.textContent = "搜索中...";
    results.innerHTML = "";
    const params = new URLSearchParams(new FormData(searchForm));
    try {
      const payload = await jsonFetch(`/api/search?${params.toString()}`);
      status.textContent = `${payload.results.length} 个结果`;
      results.innerHTML = payload.results
        .map(
          (item) => `
            <article class="result-card">
              <a class="cover-stage" href="/album/${escapeAttr(item.album_id)}">
                <img src="${escapeAttr(item.cover_url || "")}" alt="${escapeAttr(item.title)} 封面" loading="lazy">
                <span class="cover-badges">${(item.tags || []).slice(0, 2).map((tag) => `<b>${escapeHtml(tag)}</b>`).join("")}</span>
              </a>
              <div class="result-body">
                <a href="/album/${escapeAttr(item.album_id)}">${escapeHtml(item.title)}</a>
                ${item.author ? `<p class="result-author">${escapeHtml(item.author)}</p>` : `<p class="muted">JM${escapeHtml(item.album_id)}</p>`}
                <div class="tag-row">${(item.tags || []).slice(0, 6).map((tag) => `<button type="button" data-search-tag="${escapeAttr(tag)}">${escapeHtml(tag)}</button>`).join("")}</div>
                <div class="actions">
                  <button type="button" data-download-album="${escapeAttr(item.album_id)}">下载</button>
                  <button type="button" data-subscribe="${escapeAttr(item.album_id)}">订阅</button>
                </div>
              </div>
            </article>
          `
        )
        .join("");
    } catch (error) {
      status.textContent = "";
      results.innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`;
    }
  });
}

document.querySelector("[data-select-all]")?.addEventListener("click", () => {
  document.querySelectorAll("input[name='photo_ids']").forEach((input) => {
    input.checked = true;
  });
});

document.addEventListener("click", async (event) => {
  const tagButton = event.target.closest("[data-search-tag]");
  if (tagButton && searchForm) {
    searchForm.querySelector("[name='query']").value = tagButton.dataset.searchTag;
    searchForm.querySelector("[name='type']").value = "tag";
    searchForm.requestSubmit();
    return;
  }

  const downloadButton = event.target.closest("[data-download-album]");
  if (downloadButton) {
    downloadButton.disabled = true;
    downloadButton.textContent = "已加入队列";
    try {
      const task = await createDownload(downloadButton.dataset.downloadAlbum, []);
      const status = document.querySelector("#search-status");
      if (status) {
        status.innerHTML = `任务已创建：<a href="/tasks">${escapeHtml(task.id)}</a>${renderTaskStatus(task)}`;
        watchTask(task.id, status);
      }
    } catch (error) {
      downloadButton.disabled = false;
      downloadButton.textContent = "下载";
      showStatus(error.message, true);
    }
    return;
  }

  const subscribeButton = event.target.closest("[data-subscribe]");
  if (subscribeButton) {
    await subscribeAlbum(subscribeButton.dataset.subscribe);
    return;
  }

  const unsubscribeButton = event.target.closest("[data-unsubscribe]");
  if (unsubscribeButton) {
    await unsubscribeAlbum(unsubscribeButton.dataset.unsubscribe);
    return;
  }

  const retryButton = event.target.closest("[data-retry-task]");
  if (retryButton) {
    await retryTask(retryButton);
    return;
  }

  const deleteButton = event.target.closest("[data-delete-task]");
  if (deleteButton) {
    await deleteTask(deleteButton);
  }
});

document.querySelector("[data-select-none]")?.addEventListener("click", () => {
  document.querySelectorAll("input[name='photo_ids']").forEach((input) => {
    input.checked = false;
  });
});

document.querySelector("#download-selected")?.addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const status = document.querySelector("#download-status");
  const selected = [...document.querySelectorAll("input[name='photo_ids']:checked")].map((input) => input.value);
  status.textContent = "创建任务...";
  button.disabled = true;
  try {
    const task = await createDownload(button.dataset.albumId, selected);
    status.innerHTML = `任务已创建：<a href="/tasks">${escapeHtml(task.id)}</a>`;
    watchTask(task.id, status);
  } catch (error) {
    status.innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
  } finally {
    button.disabled = false;
  }
});

const albumPanel = document.querySelector("#album-panel");
if (albumPanel) {
  loadAlbumDetail(albumPanel.dataset.albumId);
}

document.querySelectorAll(".task-row[data-task-id]").forEach((row) => {
  if (!["completed", "partial", "failed"].includes(row.dataset.taskStatus || "")) {
    watchTaskRow(row);
  }
});

document.querySelector("#check-subscriptions")?.addEventListener("click", async () => {
  const status = document.querySelector("#subscription-status");
  status.textContent = "已开始检查订阅更新...";
  try {
    await jsonFetch("/api/subscriptions/check", { method: "POST" });
  } catch (error) {
    status.innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
  }
});

document.querySelector("#test-settings")?.addEventListener("click", async () => {
  const status = document.querySelector("#settings-status");
  status.textContent = "测试中...";
  try {
    const payload = await jsonFetch("/api/settings/test", { method: "POST" });
    status.textContent = payload.ok ? "连接成功" : payload.error;
  } catch (error) {
    status.textContent = error.message;
    status.className = "error";
  }
});

function watchTask(taskId, target) {
  const source = new EventSource(`/api/downloads/${taskId}/events`);
  source.onmessage = (event) => {
    const task = JSON.parse(event.data);
    target.innerHTML = renderTaskStatus(task);
    if (task.status === "completed" || task.status === "partial" || task.status === "failed") {
      source.close();
    }
  };
  source.onerror = () => source.close();
}

function watchTaskRow(row) {
  const source = new EventSource(`/api/downloads/${encodeURIComponent(row.dataset.taskId)}/events`);
  source.onmessage = (event) => {
    const task = JSON.parse(event.data);
    updateTaskRow(row, task);
    if (task.status === "completed" || task.status === "partial" || task.status === "failed") {
      source.close();
    }
  };
  source.onerror = () => source.close();
}

function updateTaskRow(row, task) {
  row.dataset.taskStatus = task.status;
  const badge = row.querySelector("[data-task-status-badge]");
  if (badge) {
    badge.className = `badge ${task.status}`;
    badge.textContent = task.status;
  }
  const text = row.querySelector("[data-task-progress-text]");
  if (text) text.textContent = task.progress || "";
  const current = Number(task.progress_current || 0);
  const total = Number(task.progress_total || 0);
  const percent = progressPercent(current, total);
  const fill = row.querySelector("[data-task-progress-fill]");
  if (fill) fill.style.width = `${percent}%`;
  const percentText = row.querySelector("[data-task-progress-percent]");
  if (percentText) percentText.textContent = `${percent}%`;
  const count = row.querySelector("[data-task-progress-count]");
  if (count) count.textContent = total > 0 ? `${current}/${total}` : "等待开始";
  const failedIds = task.failed_photo_ids || [];
  const retry = row.querySelector("[data-task-retry]");
  if (retry) retry.hidden = failedIds.length === 0;
  const failedCount = row.querySelector("[data-task-failed-count]");
  if (failedCount) failedCount.textContent = `${failedIds.length} 章待重试`;
}

async function createDownload(albumId, photoIds) {
  return jsonFetch("/api/downloads", {
    method: "POST",
    body: JSON.stringify({ album_id: albumId, photo_ids: photoIds }),
  });
}

async function retryTask(button) {
  const taskId = button.dataset.retryTask;
  button.disabled = true;
  button.textContent = "已加入队列";
  try {
    const task = await jsonFetch(`/api/downloads/${encodeURIComponent(taskId)}/retry`, { method: "POST" });
    button.textContent = `重试任务：${task.id.slice(0, 8)}`;
    showStatus(`重试任务已创建：${task.id}`);
  } catch (error) {
    button.disabled = false;
    button.textContent = "重试失败章节";
    showStatus(error.message, true);
  }
}

async function deleteTask(button) {
  const taskId = button.dataset.deleteTask;
  button.disabled = true;
  button.textContent = "删除中...";
  try {
    await jsonFetch(`/api/downloads/${encodeURIComponent(taskId)}`, { method: "DELETE" });
    button.closest(".task-row")?.remove();
    showStatus("任务已删除，本地缓存已清理");
  } catch (error) {
    button.disabled = false;
    button.textContent = "删除任务并清理缓存";
    showStatus(error.message, true);
  }
}

function renderTaskStatus(task) {
  const current = Number(task.progress_current || 0);
  const total = Number(task.progress_total || 0);
  const label = total > 0 ? `${current}/${total}` : "等待开始";
  const percent = progressPercent(current, total);
  return `
    <span class="task-status-line">${escapeHtml(task.status)}: ${escapeHtml(task.progress)}</span>
    <span class="task-progress" data-task-progress>
      <span class="task-progress-track" aria-label="下载进度">
        <span class="task-progress-fill" style="width: ${escapeAttr(percent)}%"></span>
      </span>
      <span class="task-progress-percent">${escapeHtml(percent)}%</span>
      <span class="muted">${escapeHtml(label)}</span>
    </span>
  `;
}

function progressPercent(current, total) {
  if (!total || total <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((current / total) * 100)));
}

async function loadAlbumDetail(albumId) {
  const status = document.querySelector("#download-status");
  const downloadButton = document.querySelector("#download-selected");
  try {
    const album = await jsonFetch(`/api/albums/${encodeURIComponent(albumId)}`);
    document.title = `${album.title} - JM Downloader`;
    document.querySelector("#album-title").textContent = album.title;
    document.querySelector("#album-meta").textContent = `JM${album.album_id} · ${album.author || "-"} · ${album.page_count || 0} 页`;
    const cover = document.querySelector("#album-cover");
    cover.src = album.cover_url || "";
    cover.alt = `${album.title} 封面`;
    document.querySelector("#album-description").textContent = album.description || "";
    setMetadata("authors", album.authors);
    setMetadata("tags", album.tags);
    setMetadata("works", album.works);
    setMetadata("actors", album.actors);
    setMetadata("pub_date", album.pub_date || "-");
    setMetadata("update_date", album.update_date || "-");
    document.querySelector("#chapter-form").innerHTML = (album.chapters || [])
      .map(
        (chapter) => `
          <label class="chapter-row">
            <input type="checkbox" name="photo_ids" value="${escapeAttr(chapter.photo_id)}" checked>
            <span class="chapter-index">${escapeHtml(chapter.index)}</span>
            <span>${escapeHtml(chapter.title)}</span>
            <span class="muted">JM${escapeHtml(chapter.photo_id)}</span>
          </label>
        `
      )
      .join("");
    downloadButton.disabled = false;
  } catch (error) {
    if (status) status.innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
  }
}

function setMetadata(field, value) {
  const target = document.querySelector(`[data-field="${field}"]`);
  if (!target) return;
  if (Array.isArray(value)) {
    target.textContent = value.length ? value.join(", ") : "-";
  } else {
    target.textContent = value || "-";
  }
}

async function subscribeAlbum(albumId) {
  const status = document.querySelector("#subscription-status") || document.querySelector("#search-status");
  if (status) status.textContent = "订阅中...";
  try {
    await jsonFetch("/api/subscriptions", {
      method: "POST",
      body: JSON.stringify({ album_id: albumId }),
    });
    if (status) status.textContent = "已订阅";
  } catch (error) {
    if (status) status.innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
  }
}

function showStatus(message, isError = false) {
  const status = document.querySelector("#search-status") || document.querySelector("#download-status");
  if (!status) return;
  status.innerHTML = isError ? `<span class="error">${escapeHtml(message)}</span>` : escapeHtml(message);
}

async function unsubscribeAlbum(albumId) {
  const status = document.querySelector("#subscription-status");
  if (status) status.textContent = "取消订阅中...";
  try {
    await jsonFetch(`/api/subscriptions/${encodeURIComponent(albumId)}`, { method: "DELETE" });
    document.querySelector(`[data-album-id="${CSS.escape(albumId)}"]`)?.remove();
    if (status) status.textContent = "已取消订阅";
  } catch (error) {
    if (status) status.innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}
