(() => {
  const $ = (id) => document.getElementById(id);
  const state = {
    config: null,
    job: null,
    cursor: 0,
    polling: false,
    points: [],
    latest: null,
    statuses: new Map(),
    toastTimer: null,
  };

  const statusLabels = {
    idle: "آماده",
    running: "در حال اجرا",
    stopping: "در حال توقف",
    completed: "تکمیل شد",
    partial: "نتیجهٔ ناقص",
    failed: "خطا",
    interrupted: "متوقف شد",
  };

  function formatNumber(value, decimals = 2) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
    return new Intl.NumberFormat("en-US", {
      minimumFractionDigits: 0,
      maximumFractionDigits: decimals,
    }).format(Number(value));
  }

  function speedUnit() {
    return $("speedUnit").value || "Mbps";
  }

  function latencyUnit() {
    return $("latencyUnit").value || "ms";
  }

  function speedValue(mbps) {
    const unit = speedUnit();
    const metadata = state.config?.speedUnits?.find((item) => item.value === unit);
    return Number(mbps) * (metadata?.factor ?? 1);
  }

  function formatSpeed(mbps) {
    if (mbps === null || mbps === undefined || !Number.isFinite(Number(mbps))) return "—";
    return formatNumber(speedValue(mbps));
  }

  function latencyValue(milliseconds) {
    const unit = latencyUnit();
    const metadata = state.config?.latencyUnits?.find((item) => item.value === unit);
    return Number(milliseconds) * (metadata?.factor ?? 1);
  }

  function formatLatency(milliseconds) {
    if (milliseconds === null || milliseconds === undefined || !Number.isFinite(Number(milliseconds))) return "—";
    return formatNumber(latencyValue(milliseconds));
  }

  function showToast(message) {
    $("toastText").textContent = message;
    $("toast").classList.add("visible");
    window.clearTimeout(state.toastTimer);
    state.toastTimer = window.setTimeout(() => $("toast").classList.remove("visible"), 4500);
  }

  function setStatus(status, message) {
    const badge = $("statusBadge");
    badge.className = `status-badge status-${status || "idle"}`;
    $("statusText").textContent = statusLabels[status] || statusLabels.idle;
    if (message) $("heroSubtitle").textContent = message;
    const active = status === "running" || status === "stopping";
    ["repeatCount", "executionMode", "demoMode", "disconnectExisting", "speedTimeout", "connectionTimeout"].forEach((id) => {
      $(id).disabled = active;
    });
    $("startButton").disabled = active || (!$("demoMode").checked && state.config && !state.config.expressVpnCliAvailable);
    $("stopButton").disabled = !active || status === "stopping";
    $("connectionHint").textContent = status === "running"
      ? "تست در حال اجراست"
      : status === "stopping"
        ? "توقف ایمن در جریان است"
        : !$("demoMode").checked && state.config && !state.config.expressVpnCliAvailable
          ? "نیاز به ExpressVPN CLI"
          : $("demoMode").checked
            ? "حالت آزمایشی فعال است"
            : "آماده برای تست واقعی";
    $("progressMessage").textContent = message || "برای شروع، تنظیمات تست را انتخاب کنید.";
    $("demoFlag").classList.toggle("visible", Boolean(state.job?.report?.demo || (status === "running" && $("demoMode").checked)));
  }

  function updateProgress(current, total) {
    const done = Math.max(0, Number(current) || 0);
    const max = Math.max(0, Number(total) || 0);
    $("progressCount").textContent = `${formatNumber(done, 0)} از ${formatNumber(max, 0)}`;
    $("testsValue").textContent = `${formatNumber(done, 0)} / ${formatNumber(max, 0)}`;
    $("progressBar").style.width = max ? `${Math.max(0, Math.min(100, (done / max) * 100))}%` : "0%";
  }

  function renderMetrics(measurement) {
    if (!measurement) return;
    $("downloadValue").textContent = formatSpeed(measurement.download_mbps);
    $("uploadValue").textContent = formatSpeed(measurement.upload_mbps);
    $("latencyValue").textContent = formatLatency(measurement.latency_ms);
    $("downloadUnit").textContent = speedUnit();
    $("uploadUnit").textContent = speedUnit();
    $("latencyUnitLabel").textContent = latencyUnit();
    $("serverName").textContent = measurement.server_location || measurement.server || "سرور Speedtest";
    $("serverPing").textContent = `${formatLatency(measurement.latency_ms)} ${latencyUnit()}`;
    $("gaugeValue").textContent = formatSpeed(measurement.download_mbps);
    $("gaugeUnit").textContent = speedUnit();

    const raw = Math.max(0, Number(measurement.download_mbps) || 0);
    const ratio = Math.max(0, Math.min(1, Math.log10(raw + 1) / Math.log10(1001)));
    $("gaugeNeedle").style.transform = `rotate(${-90 + ratio * 180}deg)`;
    $("gaugeArc").style.strokeDashoffset = String(270 * (1 - ratio));
  }

  function renderBaseline(baseline) {
    if (!baseline) return;
    $("baselineDownload").textContent = formatSpeed(baseline.DownloadMbps);
    $("baselineUpload").textContent = `${formatSpeed(baseline.UploadMbps)} ${speedUnit()}`;
    $("baselineLatency").textContent = `${formatLatency(baseline.LatencyMs)} ${latencyUnit()}`;
    $("baselineUnit").textContent = speedUnit();
    $("baselineNote").textContent = `${baseline.SuccessfulTests ?? 0} اندازه‌گیری موفق · ${baseline.FailedTests ?? 0} خطا`;
  }

  function setLocationStatus(name, status, region = "") {
    state.statuses.set(name, { status, region });
    renderLocations();
  }

  function renderLocations(stats = state.job?.report?.stats || [], errors = state.job?.report?.errors || []) {
    const locations = state.config?.locations || [];
    const statsByName = new Map(stats.map((item) => [item.LocationName, item]));
    const errorsByName = new Map(errors.filter((item) => item.Location).map((item) => [item.Location, item]));
    $("locationCount").textContent = `${formatNumber(locations.length, 0)} مکان`;

    if (!locations.length) {
      $("resultsBody").innerHTML = '<tr class="empty-row"><td colspan="6">فایل مکان‌ها خالی است.</td></tr>';
      return;
    }

    const rows = locations.map((location) => {
      const name = [location.country, location.city].filter(Boolean).join(", ");
      const result = statsByName.get(name);
      const error = errorsByName.get(name);
      const transient = state.statuses.get(name);
      let status = "در صف";
      let statusClass = "";
      if (result) {
        status = "تکمیل شد";
        statusClass = "done";
      } else if (error) {
        status = "خطا";
        statusClass = "error";
      } else if (transient?.status === "running") {
        status = "در حال تست";
        statusClass = "running";
      } else if (transient?.status === "error") {
        status = "خطا";
        statusClass = "error";
      }
      const down = result ? `${formatSpeed(result.DownloadMbps)} ${speedUnit()}` : "—";
      const up = result ? `${formatSpeed(result.UploadMbps)} ${speedUnit()}` : "—";
      const ping = result ? `${formatLatency(result.LatencyMs)} ${latencyUnit()}` : "—";
      const count = result ? `${result.SuccessfulTests}/${(result.SuccessfulTests || 0) + (result.FailedTests || 0)}` : "—";
      const region = result?.Region || transient?.region || location.region || "";
      return `<tr>
        <td><div class="table-location"><span class="location-pin">⌖</span><span><span class="location-name">${escapeHtml(name)}</span><span class="location-region">${escapeHtml(region)}</span></span></div></td>
        <td><span class="row-status ${statusClass}"><i></i>${status}</span></td>
        <td dir="ltr">${down}</td><td dir="ltr">${up}</td><td dir="ltr">${ping}</td><td dir="ltr">${count}</td>
      </tr>`;
    });
    $("resultsBody").innerHTML = rows.join("");
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (char) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[char]);
  }

  function renderReport(report) {
    if (!report) return;
    renderBaseline(report.baseline);
    renderLocations(report.stats || [], report.errors || []);
    $("resultsStatus").textContent = statusLabels[report.status] || "در حال اجرا";
    $("demoFlag").classList.toggle("visible", Boolean(report.demo));
    $("reportLink").classList.remove("disabled");
    $("reportLink").setAttribute("aria-disabled", "false");
    $("reportLink").href = "/api/report";
  }

  function drawChart() {
    const canvas = $("speedChart");
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const ratio = window.devicePixelRatio || 1;
    const width = Math.floor(rect.width * ratio);
    const height = Math.floor(rect.height * ratio);
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    const context = canvas.getContext("2d");
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    const w = rect.width;
    const h = rect.height;
    context.clearRect(0, 0, w, h);

    const left = 34;
    const right = 8;
    const top = 12;
    const bottom = 16;
    const plotWidth = Math.max(1, w - left - right);
    const plotHeight = Math.max(1, h - top - bottom);
    const values = state.points.map((point) => speedValue(point.download_mbps));
    const peak = Math.max(1, ...values);
    const ceiling = Math.max(peak * 1.2, 1);
    const lines = 4;
    context.font = '8px "Segoe UI", Tahoma, sans-serif';
    context.textAlign = "left";
    context.textBaseline = "middle";

    for (let index = 0; index <= lines; index += 1) {
      const y = top + (plotHeight * index) / lines;
      context.beginPath();
      context.strokeStyle = "rgba(144, 166, 207, .10)";
      context.lineWidth = 1;
      context.setLineDash(index === lines ? [] : [3, 5]);
      context.moveTo(left, y);
      context.lineTo(w - right, y);
      context.stroke();
      context.setLineDash([]);
      const label = formatNumber(ceiling * (1 - index / lines), 0);
      context.fillStyle = "#71809b";
      context.fillText(label, 0, y);
    }

    if (values.length < 1) return;
    const points = values.map((value, index) => ({
      x: left + (values.length === 1 ? plotWidth * 0.5 : (plotWidth * index) / (values.length - 1)),
      y: top + plotHeight - (Math.min(value, ceiling) / ceiling) * plotHeight,
    }));
    const gradient = context.createLinearGradient(0, top, 0, h - bottom);
    gradient.addColorStop(0, "rgba(100, 227, 206, .22)");
    gradient.addColorStop(1, "rgba(100, 227, 206, 0)");
    context.beginPath();
    context.moveTo(points[0].x, h - bottom);
    points.forEach((point) => context.lineTo(point.x, point.y));
    context.lineTo(points[points.length - 1].x, h - bottom);
    context.closePath();
    context.fillStyle = gradient;
    context.fill();

    context.beginPath();
    points.forEach((point, index) => {
      if (index === 0) context.moveTo(point.x, point.y);
      else context.lineTo(point.x, point.y);
    });
    context.strokeStyle = "#64e3ce";
    context.lineWidth = 2;
    context.lineJoin = "round";
    context.lineCap = "round";
    context.shadowColor = "rgba(100, 227, 206, .36)";
    context.shadowBlur = 8;
    context.stroke();
    context.shadowBlur = 0;
    const last = points[points.length - 1];
    context.beginPath();
    context.arc(last.x, last.y, 3, 0, Math.PI * 2);
    context.fillStyle = "#a8fff3";
    context.fill();
    context.strokeStyle = "rgba(100, 227, 206, .28)";
    context.lineWidth = 5;
    context.stroke();
  }

  function addChartPoint(measurement) {
    state.points.push(measurement);
    if (state.points.length > 48) state.points.shift();
    $("chartEmpty").classList.add("hidden");
    $("chartLatest").textContent = new Date().toLocaleTimeString("fa-IR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    drawChart();
  }

  function addActivity(message, timestamp) {
    const list = $("activityLog");
    const placeholder = list.querySelector(".activity-placeholder");
    if (placeholder) placeholder.remove();
    const item = document.createElement("li");
    const time = document.createElement("span");
    time.className = "activity-time";
    time.textContent = timestamp
      ? new Date(timestamp).toLocaleTimeString("fa-IR", { hour: "2-digit", minute: "2-digit" })
      : new Date().toLocaleTimeString("fa-IR", { hour: "2-digit", minute: "2-digit" });
    const dot = document.createElement("span");
    dot.className = "activity-dot";
    const text = document.createElement("span");
    text.textContent = message;
    item.append(time, dot, text);
    list.prepend(item);
    while (list.children.length > 5) list.lastElementChild.remove();
  }

  function handleEvent(event) {
    if (event.message) {
      $("progressMessage").textContent = event.message;
      if (event.type === "log" || event.type === "job_started" || event.type === "location_start" || event.type === "location_complete" || event.type === "location_failed" || event.type === "location_skipped" || event.type === "job_finished") {
        addActivity(event.message, event.at);
      }
    }
    if (event.type === "phase") {
      updateProgress(event.current ?? 0, event.total ?? 0);
      if (event.location) $("serverName").textContent = event.location;
      $("testModeCaption").textContent = event.phase === "baseline" ? "در حال سنجش اتصال پایه" : "در حال سنجش مسیر VPN";
    }
    if (event.type === "sample") {
      updateProgress(event.completed, event.total);
      if (event.measurement) {
        state.latest = event.measurement;
        renderMetrics(event.measurement);
        addChartPoint(event.measurement);
      }
      if (event.location) setLocationStatus(event.location, "running");
    }
    if (event.type === "baseline_complete") {
      renderBaseline(event.summary);
      $("testModeCaption").textContent = "اتصال پایه ثبت شد";
    }
    if (event.type === "location_start") {
      setLocationStatus(event.location, "running", event.region);
      $("serverName").textContent = event.location;
      $("resultsStatus").textContent = `در حال تست · ${event.location}`;
      updateProgress(0, event.total || Number($("repeatCount").value));
    }
    if (event.type === "location_complete") {
      setLocationStatus(event.location, "done", event.region);
      $("resultsStatus").textContent = "در حال مقایسه";
      const summary = event.summary;
      if (summary) {
        const current = state.job?.report || { stats: [], errors: [] };
        const stats = [...(current.stats || []).filter((item) => item.LocationName !== event.location), {
          LocationName: event.location,
          Region: event.region,
          TimeToConnect: "",
          DownloadMbps: summary.DownloadMbps,
          UploadMbps: summary.UploadMbps,
          LatencyMs: summary.LatencyMs,
          SuccessfulTests: summary.SuccessfulTests,
          FailedTests: summary.FailedTests,
        }];
        state.job.report = { ...current, stats };
        renderReport(state.job.report);
      }
    }
    if (event.type === "location_failed" || event.type === "location_skipped") {
      setLocationStatus(event.location, "error");
    }
    if (event.type === "stopping") {
      setStatus("stopping", event.message);
    }
    if (event.type === "job_finished") {
      setStatus(event.status, event.message);
      $("resultsStatus").textContent = statusLabels[event.status] || "پایان اجرا";
      $("lastUpdated").textContent = new Date().toLocaleTimeString("fa-IR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      if (event.status === "completed") $("progressBar").style.width = "100%";
    }
    if (event.type === "run_failed") showToast(event.message || "اجرای تست با خطا مواجه شد.");
  }

  function applyJob(job) {
    if (!job) return;
    state.job = job;
    setStatus(job.status, job.message);
    if (job.progress) updateProgress(job.progress.current, job.progress.total);
    if (job.currentLocation) $("serverName").textContent = job.currentLocation;
    if (job.report) renderReport(job.report);
    if (job.status === "idle") {
      $("heroTitle").textContent = "آمادهٔ اندازه‌گیری";
      $("testModeCaption").textContent = "آماده برای اندازه‌گیری";
    } else if (job.status === "running" || job.status === "stopping") {
      $("heroTitle").textContent = job.status === "stopping" ? "در حال توقف ایمن" : "تست در حال اجراست";
    } else {
      $("heroTitle").textContent = statusLabels[job.status] || "پایان تست";
    }
    if (job.output && job.report) {
      $("reportLink").classList.remove("disabled");
      $("reportLink").setAttribute("aria-disabled", "false");
    }
  }

  async function poll() {
    if (state.polling) return;
    state.polling = true;
    try {
      const response = await fetch(`/api/status?after=${state.cursor}`, { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "دریافت وضعیت ناموفق بود.");
      if (data.reset) {
        state.cursor = Math.max(0, data.events[0]?.id - 1 || data.cursor);
      }
      for (const event of data.events || []) {
        handleEvent(event);
        state.cursor = Math.max(state.cursor, event.id);
      }
      state.cursor = Math.max(state.cursor, data.cursor || 0);
      applyJob(data.job);
    } catch (error) {
      if (!state.config) showToast(error.message || "ارتباط با داشبورد برقرار نشد.");
    } finally {
      state.polling = false;
    }
  }

  async function loadConfig() {
    const response = await fetch("/api/config", { cache: "no-store" });
    const config = await response.json();
    if (!response.ok) throw new Error(config.error || "خواندن تنظیمات ناموفق بود.");
    state.config = config;
    $("speedUnit").innerHTML = config.speedUnits.map((unit) =>
      `<option value="${escapeHtml(unit.value)}">${escapeHtml(unit.label)}</option>`).join("");
    $("latencyUnit").innerHTML = config.latencyUnits.map((unit) =>
      `<option value="${escapeHtml(unit.value)}">${escapeHtml(unit.label)}</option>`).join("");
    $("engineText").textContent = `موتور Speedtest ${config.speedtest.version} داخل پروژه است؛ نصب CLI جداگانه لازم نیست`;
    $("vpnWarning").classList.toggle("hidden", config.expressVpnCliAvailable);
    renderLocations();
    setStatus("idle", "تست را شروع کنید تا عملکرد اتصال شما نمایش داده شود.");
  }

  function updateUnits() {
    $("downloadUnit").textContent = speedUnit();
    $("uploadUnit").textContent = speedUnit();
    $("gaugeUnit").textContent = speedUnit();
    $("baselineUnit").textContent = speedUnit();
    $("chartUnit").textContent = speedUnit();
    $("latencyUnitLabel").textContent = latencyUnit();
    if (state.latest) renderMetrics(state.latest);
    if (state.job?.report?.baseline) renderBaseline(state.job.report.baseline);
    renderLocations();
    drawChart();
  }

  function startNewRun() {
    const repeat = Number($("repeatCount").value);
    const payload = {
      repeat,
      serial: $("executionMode").value === "serial",
      demo: $("demoMode").checked,
      disconnectExisting: $("disconnectExisting").checked,
      displayUnit: speedUnit(),
      latencyUnit: latencyUnit(),
      speedtestTimeout: Number($("speedTimeout").value),
      connectionTimeout: Number($("connectionTimeout").value),
    };
    if (!Number.isInteger(repeat) || repeat < 1 || repeat > 32) {
      showToast("تعداد تکرار باید عددی بین ۱ تا ۳۲ باشد.");
      return;
    }
    state.points = [];
    state.latest = null;
    state.statuses.clear();
    $("chartEmpty").classList.remove("hidden");
    $("downloadValue").textContent = "—";
    $("uploadValue").textContent = "—";
    $("latencyValue").textContent = "—";
    $("gaugeValue").textContent = "—";
    $("gaugeNeedle").style.transform = "rotate(-90deg)";
    $("gaugeArc").style.strokeDashoffset = "270";
    $("baselineDownload").textContent = "—";
    $("baselineUpload").textContent = "—";
    $("baselineLatency").textContent = "—";
    $("baselineNote").textContent = "پس از تست پایه، نتیجه اینجا ذخیره می‌شود.";
    $("resultsBody").innerHTML = "";
    renderLocations();
    $("reportLink").classList.add("disabled");
    $("reportLink").setAttribute("aria-disabled", "true");
    $("resultsStatus").textContent = "در حال آماده‌سازی";
    $("heroTitle").textContent = "در حال آماده‌سازی";
    addActivity("درخواست اجرای تست ارسال شد.");

    fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then(async (response) => {
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || "شروع تست ناموفق بود.");
      state.job = body.job;
      await poll();
    }).catch((error) => {
      setStatus("failed", error.message);
      showToast(error.message || "شروع تست با خطا مواجه شد.");
    });
  }

  async function stopRun() {
    try {
      const response = await fetch("/api/stop", { method: "POST" });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || "امکان توقف وجود ندارد.");
      setStatus("stopping", "توقف ایمن درخواست شد.");
    } catch (error) {
      showToast(error.message || "توقف تست ناموفق بود.");
    }
  }

  function updateModeOptions() {
    const demo = $("demoMode").checked;
    $("realModeOptions").classList.toggle("hidden", demo);
    setStatus(state.job?.status || "idle", state.job?.message || "تست را شروع کنید تا عملکرد اتصال شما نمایش داده شود.");
  }

  $("startButton").addEventListener("click", startNewRun);
  $("stopButton").addEventListener("click", stopRun);
  $("speedUnit").addEventListener("change", updateUnits);
  $("latencyUnit").addEventListener("change", updateUnits);
  $("demoMode").addEventListener("change", updateModeOptions);
  window.addEventListener("resize", drawChart);
  $("reportLink").addEventListener("click", (event) => {
    if ($("reportLink").classList.contains("disabled")) event.preventDefault();
  });

  loadConfig().then(() => poll()).catch((error) => {
    showToast(error.message || "بارگذاری داشبورد ناموفق بود.");
    setStatus("failed", error.message);
  });
  window.setInterval(poll, 700);
})();
