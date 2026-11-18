/* Web 智能巡检机器人仿真系统 - 前端逻辑（仅渲染与发指令，不含业务规则） */

const CELL = 32;

let mapData = null;
let stateData = null;
let seq = 0;

async function fetchJSON(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) throw new Error(`${url} -> ${res.status}`);
  return res.json();
}

async function init() {
  mapData = await fetchJSON("/map");
  bindButtons();
  await refreshState();
  setInterval(refreshState, 500);
}

function bindButtons() {
  document.querySelectorAll("button[data-cmd]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const body = { cmd: btn.dataset.cmd, param: {}, from: "user", seq: ++seq };
      if (btn.dataset.dir) body.param.dir = btn.dataset.dir;
      try {
        const res = await fetchJSON("/cmd", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        stateData = res.state;
        render();
      } catch (err) {
        console.error(err);
      }
    });
  });
}

async function refreshState() {
  try {
    stateData = await fetchJSON("/state");
    render();
  } catch (err) {
    console.error(err);
  }
}

function render() {
  draw();
  renderState();
}

function renderState() {
  if (!stateData) return;
  const robot = stateData.robot;
  const items = [
    ["状态", stateData.state],
    ["坐标", `(${robot.x}, ${robot.y})`],
    ["朝向", `${robot.heading}°`],
    ["电量", `${stateData.battery}%`],
    ["tick", stateData.tick],
  ];
  document.getElementById("state-list").innerHTML = items
    .map(([k, v]) => `<li><span>${k}</span><strong>${v}</strong></li>`)
    .join("");
  document.getElementById("log-line").textContent = stateData.log;
  renderAnomaly();
  renderPatrol();
}

function renderAnomaly() {
  const badge = document.getElementById("anomaly-badge");
  if (!badge) return;
  const sensors = stateData.sensors || {};
  const abnormal = sensors.anomaly_label === "anomaly";
  const prob = typeof sensors.anomaly_prob === "number"
    ? sensors.anomaly_prob.toFixed(2)
    : "0.00";
  badge.textContent = `异常检测：${abnormal ? "异常" : "正常"}（p=${prob}）`;
  badge.classList.toggle("alert", abnormal);
}

function renderPatrol() {
  const patrol = stateData.patrol
    || { rounds_completed: 0, left_start: false, records: [], points_total: 0, points_visited: 0, visited: [] };
  document.getElementById("patrol-rounds").textContent = patrol.rounds_completed;
  document.getElementById("points-visited").textContent = patrol.points_visited ?? 0;
  document.getElementById("points-total").textContent = patrol.points_total ?? 0;
  const autoBadge = document.getElementById("auto-badge");
  autoBadge.textContent = stateData.auto ? "自动巡检中" : "手动模式";
  autoBadge.classList.toggle("on", Boolean(stateData.auto));
  const status = document.getElementById("patrol-status");
  status.textContent = patrol.left_start ? "巡检中（已离开起点）" : "在起点";
  status.classList.toggle("away", patrol.left_start);

  const body = document.getElementById("records-body");
  if (!patrol.records.length) {
    body.innerHTML = '<tr class="empty-row"><td colspan="2">暂无巡检记录</td></tr>';
    return;
  }
  body.innerHTML = patrol.records
    .map((r) => `<tr><td>第 ${r.round} 轮</td><td>${formatTime(r.completed_at)}</td></tr>`)
    .join("");
}

function formatTime(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} `
    + `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function draw() {
  if (!mapData || !stateData) return;
  const canvas = document.getElementById("map-canvas");
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  const obstacles = new Set(mapData.obstacles.map(([x, y]) => `${x},${y}`));

  for (let y = 0; y < mapData.height; y++) {
    for (let x = 0; x < mapData.width; x++) {
      const px = x * CELL;
      const py = y * CELL;
      ctx.strokeStyle = "rgba(148, 163, 184, 0.25)";
      ctx.strokeRect(px, py, CELL, CELL);
      if (obstacles.has(`${x},${y}`)) {
        ctx.fillStyle = "#475569";
        ctx.fillRect(px + 2, py + 2, CELL - 4, CELL - 4);
      }
    }
  }

  drawStart(mapData.start);
  drawPatrolPoints();
  drawAutoPath();
  drawRobot(stateData.robot);
}

function drawStart(start) {
  if (!start) return;
  const canvas = document.getElementById("map-canvas");
  const ctx = canvas.getContext("2d");
  const px = start[0] * CELL;
  const py = start[1] * CELL;
  ctx.fillStyle = "rgba(34, 197, 94, 0.28)";
  ctx.fillRect(px + 2, py + 2, CELL - 4, CELL - 4);
  ctx.strokeStyle = "#22c55e";
  ctx.lineWidth = 2;
  ctx.strokeRect(px + 2, py + 2, CELL - 4, CELL - 4);
  ctx.fillStyle = "#22c55e";
  ctx.font = "10px 'Microsoft YaHei', sans-serif";
  ctx.textAlign = "center";
  ctx.fillText("起点", px + CELL / 2, py + CELL - 5);
}

function drawPatrolPoints() {
  const points = mapData.patrol_points || [];
  if (!points.length) return;
  const canvas = document.getElementById("map-canvas");
  const ctx = canvas.getContext("2d");
  const visited = new Set(
    ((stateData.patrol || {}).visited || []).map(([x, y]) => `${x},${y}`)
  );
  points.forEach(([x, y], index) => {
    const cx = x * CELL + CELL / 2;
    const cy = y * CELL + CELL / 2;
    const done = visited.has(`${x},${y}`);
    ctx.beginPath();
    ctx.arc(cx, cy, CELL / 3, 0, Math.PI * 2);
    ctx.fillStyle = done ? "rgba(34, 197, 94, 0.85)" : "rgba(245, 158, 11, 0.9)";
    ctx.fill();
    ctx.strokeStyle = done ? "#16a34a" : "#d97706";
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.fillStyle = "#0b1220";
    ctx.font = "bold 11px 'Microsoft YaHei', sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(done ? "✓" : String(index + 1), cx, cy + 1);
  });
  ctx.textBaseline = "alphabetic";
}

function drawAutoPath() {
  const path = stateData.path || [];
  if (!stateData.auto || !path.length) return;
  const canvas = document.getElementById("map-canvas");
  const ctx = canvas.getContext("2d");
  const remaining = path.slice(stateData.path_index || 0);
  ctx.save();
  ctx.strokeStyle = "rgba(56, 189, 248, 0.55)";
  ctx.lineWidth = 2;
  ctx.setLineDash([6, 4]);
  ctx.beginPath();
  ctx.moveTo(stateData.robot.x * CELL + CELL / 2, stateData.robot.y * CELL + CELL / 2);
  remaining.forEach(([x, y]) => ctx.lineTo(x * CELL + CELL / 2, y * CELL + CELL / 2));
  ctx.stroke();
  ctx.restore();
}

function drawRobot(robot) {
  const canvas = document.getElementById("map-canvas");
  const ctx = canvas.getContext("2d");
  const cx = robot.x * CELL + CELL / 2;
  const cy = robot.y * CELL + CELL / 2;

  const abnormal = (stateData.sensors || {}).anomaly_label === "anomaly";
  ctx.fillStyle = abnormal ? "#f87171" : "#38bdf8";
  ctx.fillRect(robot.x * CELL + 5, robot.y * CELL + 5, CELL - 10, CELL - 10);

  const rad = (robot.heading * Math.PI) / 180;
  ctx.strokeStyle = abnormal ? "#b91c1c" : "#0284c7";
  ctx.lineWidth = 3;
  ctx.beginPath();
  ctx.moveTo(cx, cy);
  ctx.lineTo(cx + Math.cos(rad) * (CELL / 2 - 2), cy + Math.sin(rad) * (CELL / 2 - 2));
  ctx.stroke();
}

init();
