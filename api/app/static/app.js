const READINGS_LIMIT = 500;
const DEFAULT_REFRESH_SECONDS = 60;

let nodes = [];
let selectedNodeId = null;
let refreshTimerId = null;
let refreshSeconds = DEFAULT_REFRESH_SECONDS;

const nodeListEl = document.getElementById("node-list");
const titleEl = document.getElementById("selected-node-title");
const tableEl = document.getElementById("readings-table");
const chartsEl = document.getElementById("charts");
const statusEl = document.getElementById("status-banner");
const intervalSelectEl = document.getElementById("refresh-interval");
const intervalCustomEl = document.getElementById("refresh-custom");

function showStatus(message, isError = false) {
  if (!message) {
    statusEl.hidden = true;
    statusEl.textContent = "";
    return;
  }
  statusEl.hidden = false;
  statusEl.textContent = message;
  statusEl.classList.toggle("error", isError);
}

async function fetchJson(path) {
  const res = await fetch(path);
  if (!res.ok) {
    throw new Error(`${path} -> HTTP ${res.status}`);
  }
  return res.json();
}

async function fetchNodes() {
  try {
    const data = await fetchJson("/nodes");
    showStatus(null);
    return data;
  } catch (err) {
    showStatus(`Failed to reach API: ${err.message}`, true);
    return [];
  }
}

async function fetchReadings(nodeId, limit = READINGS_LIMIT) {
  return fetchJson(`/nodes/${encodeURIComponent(nodeId)}/readings?limit=${limit}`);
}

function renderNodeList() {
  nodeListEl.innerHTML = "";

  if (nodes.length === 0) {
    showStatus("No nodes have reported yet.");
    titleEl.textContent = "Select a node";
    tableEl.querySelector("thead tr").innerHTML = "";
    tableEl.querySelector("tbody").innerHTML = "";
    chartsEl.innerHTML = "";
    return;
  }

  for (const node of nodes) {
    const li = document.createElement("li");
    li.textContent = node.label || node.node_id;
    li.classList.toggle("selected", node.node_id === selectedNodeId);

    const meta = document.createElement("span");
    meta.className = "node-meta";
    meta.textContent = `${node.node_id} · last seen ${node.last_seen}`;
    li.appendChild(meta);

    li.addEventListener("click", () => selectNode(node.node_id));
    nodeListEl.appendChild(li);
  }
}

function detectFields(items) {
  const numericFields = new Set();
  const otherFields = new Set();

  for (const item of items) {
    for (const [key, value] of Object.entries(item.data || {})) {
      if (typeof value === "number") {
        numericFields.add(key);
      } else {
        otherFields.add(key);
      }
    }
  }

  return { numericFields: [...numericFields], otherFields: [...otherFields] };
}

function renderReadingsTable(items, numericFields, otherFields) {
  const headRow = tableEl.querySelector("thead tr");
  const body = tableEl.querySelector("tbody");
  headRow.innerHTML = "";
  body.innerHTML = "";

  const columns = ["reading_ts", ...numericFields, ...otherFields];
  for (const col of columns) {
    const th = document.createElement("th");
    th.textContent = col;
    headRow.appendChild(th);
  }

  for (const item of [...items].reverse()) {
    const tr = document.createElement("tr");
    for (const col of columns) {
      const td = document.createElement("td");
      td.textContent = col === "reading_ts" ? item.reading_ts : (item.data ?? {})[col] ?? "";
      tr.appendChild(td);
    }
    body.appendChild(tr);
  }
}

function drawLineChart(canvas, points, label) {
  const ctx = canvas.getContext("2d");
  const width = canvas.clientWidth || canvas.width;
  const height = canvas.clientHeight || canvas.height;
  canvas.width = width;
  canvas.height = height;
  ctx.clearRect(0, 0, width, height);

  if (points.length === 0) return;

  const padding = 30;
  const values = points.map((p) => p.y);
  let minY = Math.min(...values);
  let maxY = Math.max(...values);
  if (minY === maxY) {
    minY -= 1;
    maxY += 1;
  }

  const xFor = (i) =>
    points.length === 1
      ? width / 2
      : padding + (i / (points.length - 1)) * (width - 2 * padding);
  const yFor = (v) =>
    height - padding - ((v - minY) / (maxY - minY)) * (height - 2 * padding);

  ctx.strokeStyle = "#dde1e6";
  ctx.fillStyle = "#6b7280";
  ctx.font = "11px system-ui, sans-serif";
  ctx.beginPath();
  ctx.moveTo(padding, padding);
  ctx.lineTo(padding, height - padding);
  ctx.lineTo(width - padding, height - padding);
  ctx.stroke();
  ctx.fillText(maxY.toFixed(2), 2, padding + 4);
  ctx.fillText(minY.toFixed(2), 2, height - padding);

  ctx.strokeStyle = "#2563eb";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  points.forEach((p, i) => {
    const x = xFor(i);
    const y = yFor(p.y);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function renderCharts(items, numericFields) {
  chartsEl.innerHTML = "";

  for (const field of numericFields) {
    const points = items
      .filter((item) => typeof (item.data ?? {})[field] === "number")
      .map((item) => ({ x: item.reading_ts, y: item.data[field] }));

    const block = document.createElement("div");
    block.className = "chart-block";

    const heading = document.createElement("h3");
    heading.textContent = field;
    block.appendChild(heading);

    const canvas = document.createElement("canvas");
    block.appendChild(canvas);

    chartsEl.appendChild(block);
    drawLineChart(canvas, points, field);
  }
}

async function loadReadingsForSelectedNode() {
  if (!selectedNodeId) return;

  try {
    const page = await fetchReadings(selectedNodeId);
    showStatus(null);

    if (page.items.length === 0) {
      titleEl.textContent = selectedNodeId;
      tableEl.querySelector("thead tr").innerHTML = "";
      tableEl.querySelector("tbody").innerHTML = "";
      chartsEl.innerHTML = "";
      showStatus("This node has no readings yet.");
      return;
    }

    titleEl.textContent = page.has_more
      ? `${selectedNodeId} (showing ${page.items.length} of more available)`
      : selectedNodeId;

    const { numericFields, otherFields } = detectFields(page.items);
    renderReadingsTable(page.items, numericFields, otherFields);
    renderCharts(page.items, numericFields);
  } catch (err) {
    showStatus(`Failed to reach API: ${err.message}`, true);
  }
}

function selectNode(nodeId) {
  selectedNodeId = nodeId;
  renderNodeList();
  loadReadingsForSelectedNode();
}

function restartRefreshTimer() {
  if (refreshTimerId) {
    clearInterval(refreshTimerId);
    refreshTimerId = null;
  }
  if (refreshSeconds > 0) {
    refreshTimerId = setInterval(async () => {
      nodes = await fetchNodes();
      renderNodeList();
      await loadReadingsForSelectedNode();
    }, refreshSeconds * 1000);
  }
}

intervalSelectEl.addEventListener("change", () => {
  intervalCustomEl.value = "";
  refreshSeconds = Number(intervalSelectEl.value);
  restartRefreshTimer();
});

intervalCustomEl.addEventListener("change", () => {
  const value = Number(intervalCustomEl.value);
  if (value > 0) {
    refreshSeconds = value;
    restartRefreshTimer();
  }
});

async function init() {
  nodes = await fetchNodes();
  renderNodeList();
  if (nodes.length > 0) {
    selectNode(nodes[0].node_id);
  }
  restartRefreshTimer();
}

document.addEventListener("DOMContentLoaded", init);
