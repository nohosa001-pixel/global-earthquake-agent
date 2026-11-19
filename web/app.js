// Global Earthquake Agent Web Client
let map;
let earthquakeMarkers = [];
let zoneLayers = [];
let bValueChart = null;
let strainChart = null;
let currentZoneId = "japan_trench";

// Critical Infrastructure Markers
const ASSETS = [
    { name: "TSMC 팹 단지", lat: 24.78, lon: 120.99, type: "fab", desc: "글로벌 파운드리 60%+" },
    { name: "소니 구마모토 팹", lat: 32.88, lon: 130.85, type: "fab", desc: "CMOS 센서 50%" },
    { name: "르네사스 나카 팹", lat: 36.42, lon: 140.53, type: "fab", desc: "차량용 MCU 팹" },
    { name: "에스콘디다 구리광산 (칠레)", lat: -24.27, lon: -69.07, type: "mine", desc: "세계 1위 구리 광산" },
    { name: "그라스버그 광산 (인니)", lat: -4.05, lon: 137.11, type: "mine", desc: "세계 2위 구리/금광" }
];

document.addEventListener("DOMContentLoaded", () => {
    initMap();
    initCharts();
    initTabs();
    loadAllData();

    document.getElementById("btnRefresh").addEventListener("click", loadAllData);
});

// 1. Initialize Map
function initMap() {
    map = L.map("map", {
        center: [20, 140],
        zoom: 3,
        minZoom: 2,
        maxZoom: 10
    });

    // Dark Map Tiles (CartoDB DarkMatter)
    L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
        attribution: '&copy; OpenStreetMap, &copy; CARTO, &copy; USGS Seismology',
        subdomains: 'abcd',
        maxZoom: 19
    }).addTo(map);

    // Add Assets Markers
    ASSETS.forEach(asset => {
        const iconHtml = asset.type === "fab" ? "🏭" : "⛏️";
        const customIcon = L.divIcon({
            html: `<div style="font-size: 16px; text-shadow: 0 0 5px #00e5ff;">${iconHtml}</div>`,
            className: "asset-marker",
            iconSize: [20, 20],
            iconAnchor: [10, 10]
        });

        L.marker([asset.lat, asset.lon], { icon: customIcon })
            .addTo(map)
            .bindPopup(`<strong>${asset.name}</strong><br>${asset.desc}`);
    });
}

// 2. Initialize Charts
function initCharts() {
    const ctxB = document.getElementById("bValueChart").getContext("2d");
    bValueChart = new Chart(ctxB, {
        type: "line",
        data: {
            labels: [],
            datasets: [
                {
                    label: "Aki MLE b-Value",
                    data: [],
                    borderColor: "#00e5ff",
                    backgroundColor: "rgba(0, 229, 255, 0.15)",
                    borderWidth: 2,
                    tension: 0.3,
                    fill: true,
                    pointRadius: 2
                },
                {
                    label: "안정 상태 기준선 (b=1.0)",
                    data: [],
                    borderColor: "rgba(255, 255, 255, 0.4)",
                    borderWidth: 1,
                    borderDash: [5, 5],
                    pointRadius: 0
                },
                {
                    label: "임계 응력 경계 (b=0.75)",
                    data: [],
                    borderColor: "rgba(239, 68, 68, 0.8)",
                    borderWidth: 1,
                    borderDash: [3, 3],
                    pointRadius: 0
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { labels: { color: "#94a3b8", font: { size: 10 } } }
            },
            scales: {
                x: { ticks: { color: "#64748b", font: { size: 9 }, maxTicksLimit: 6 }, grid: { color: "rgba(255,255,255,0.05)" } },
                y: { min: 0.4, max: 1.5, ticks: { color: "#64748b", font: { size: 10 } }, grid: { color: "rgba(255,255,255,0.05)" } }
            }
        }
    });

    const ctxS = document.getElementById("strainChart").getContext("2d");
    strainChart = new Chart(ctxS, {
        type: "line",
        data: {
            labels: [],
            datasets: [
                {
                    label: "Benioff Strain (Cumulative √E)",
                    data: [],
                    borderColor: "#f59e0b",
                    backgroundColor: "rgba(245, 158, 11, 0.15)",
                    borderWidth: 2,
                    tension: 0.2,
                    fill: true,
                    pointRadius: 2
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { labels: { color: "#94a3b8", font: { size: 10 } } }
            },
            scales: {
                x: { ticks: { color: "#64748b", font: { size: 9 }, maxTicksLimit: 6 }, grid: { color: "rgba(255,255,255,0.05)" } },
                y: { ticks: { color: "#64748b", font: { size: 10 } }, grid: { color: "rgba(255,255,255,0.05)" } }
            }
        }
    });
}

// 3. Tab Switching
function initTabs() {
    const btns = document.querySelectorAll(".tab-btn");
    btns.forEach(btn => {
        btn.addEventListener("click", () => {
            btns.forEach(b => b.classList.remove("active"));
            document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));

            btn.classList.add("active");
            const targetId = btn.getAttribute("data-tab");
            document.getElementById(targetId).classList.add("active");
        });
    });
}

// 4. Load All Data
async function loadAllData() {
    try {
        await Promise.all([
            fetchEarthquakes(),
            fetchZonesSummary(),
            fetchOracles()
        ]);
        // Load default zone detail
        fetchZoneDetail(currentZoneId);
    } catch (err) {
        console.error("Data load error:", err);
    }
}

// Fetch Earthquakes & Plot on Map
async function fetchEarthquakes() {
    const res = await fetch("/api/earthquakes/realtime");
    const data = await res.json();
    document.getElementById("globalEventsCount").innerText = `${data.count} Events (M2.5+)`;

    // Clear old markers
    earthquakeMarkers.forEach(m => map.removeLayer(m));
    earthquakeMarkers = [];

    data.events.forEach(evt => {
        const radius = Math.max(3, (evt.mag - 2) * 4);
        let color = "#3b82f6";
        if (evt.mag >= 6.5) color = "#ef4444";
        else if (evt.mag >= 5.0) color = "#f97316";
        else if (evt.mag >= 4.0) color = "#f59e0b";

        const circle = L.circleMarker([evt.lat, evt.lon], {
            radius: radius,
            color: color,
            fillColor: color,
            fillOpacity: 0.6,
            weight: 1
        }).bindPopup(`
            <strong>${evt.place}</strong><br>
            규모: <b style="color:${color}">M ${evt.mag}</b> | 깊이: ${evt.depth_km}km<br>
            시각: ${new Date(evt.time).toLocaleString()}
        `);

        circle.addTo(map);
        earthquakeMarkers.push(circle);
    });
}

// Fetch Zones Summary & Build Sidebar List
async function fetchZonesSummary() {
    const res = await fetch("/api/zones/summary");
    const data = await res.json();
    const container = document.getElementById("zoneListContainer");
    container.innerHTML = "";

    // Clear old zone bounding boxes
    zoneLayers.forEach(l => map.removeLayer(l));
    zoneLayers = [];

    data.zones.forEach(zone => {
        const item = document.createElement("div");
        item.className = `zone-item ${zone.zone_id === currentZoneId ? "active" : ""}`;
        item.onclick = () => {
            document.querySelectorAll(".zone-item").forEach(el => el.classList.remove("active"));
            item.classList.add("active");
            currentZoneId = zone.zone_id;
            fetchZoneDetail(zone.zone_id);
            map.flyTo(zone.center, 5);
        };

        let pillClass = "pill-normal";
        if (zone.risk_level === "WARNING") pillClass = "pill-warning";
        else if (zone.risk_level === "WATCH") pillClass = "pill-watch";
        else if (zone.risk_level === "ADVISORY") pillClass = "pill-advisory";

        item.innerHTML = `
            <div class="zone-item-header">
                <span class="zone-name">${zone.name}</span>
                <span class="pill-badge ${pillClass}">${zone.risk_level}</span>
            </div>
            <div class="zone-stats-mini">
                <span>b-val: <b>${zone.b_value_recent.toFixed(2)}</b> (Δ-${zone.b_drop_pct}%)</span>
                <span>M6.0+ 확률: <b>${zone.prob_m6_30d_pct}%</b></span>
            </div>
        `;
        container.appendChild(item);

        // Add bounding box on map
        const bbox = zone.bbox; // [min_lat, min_lon, max_lat, max_lon]
        const bounds = [[bbox[0], bbox[1]], [bbox[2], bbox[3]]];
        const rect = L.rectangle(bounds, {
            color: zone.risk_level === "WARNING" ? "#ef4444" : "#00e5ff",
            weight: 1,
            fillOpacity: 0.05,
            dashArray: "4, 4"
        }).addTo(map);
        rect.bindTooltip(zone.name);
        zoneLayers.push(rect);
    });
}

// Fetch Detailed Zone Analysis (Charts & Physics Info)
async function fetchZoneDetail(zoneId) {
    try {
        const res = await fetch(`/api/zones/${zoneId}/detail`);
        const data = await res.json();
        const info = data.zone_info;
        const ana = data.analysis;

        document.getElementById("detailZoneName").innerText = info.name;
        const badge = document.getElementById("detailRiskBadge");
        badge.innerText = ana.risk_level;
        badge.className = `pill-badge pill-${ana.risk_level.toLowerCase()}`;

        document.getElementById("statRecentB").innerText = ana.b_value_recent.toFixed(2);
        document.getElementById("statHistB").innerText = ana.b_value_historical.toFixed(2);
        document.getElementById("statBDrop").innerText = `-${ana.b_drop_pct}%`;
        document.getElementById("statMc").innerText = `M ${ana.mc}`;

        document.getElementById("gaugeProbText").innerText = `${ana.prob_m6_30d_pct}%`;
        document.getElementById("gaugeProgressBar").style.width = `${ana.prob_m6_30d_pct}%`;

        // Update Indicators
        const indBox = document.getElementById("indicatorsBox");
        if (ana.indicators && ana.indicators.length > 0) {
            indBox.innerHTML = ana.indicators.map(i => `<div class="indicator-item">• ⚠️ ${i}</div>`).join("");
        } else {
            indBox.innerHTML = '<div class="indicator-item">• 정상적인 미소 지진 응력 해소 상태 유지</div>';
        }

        // Update Charts
        if (ana.timeseries && ana.timeseries.length > 0) {
            const labels = ana.timeseries.map(t => new Date(t.time).toLocaleDateString("ko-KR", { month: "short", day: "numeric" }));
            const bVals = ana.timeseries.map(t => t.b_value);
            const strains = ana.timeseries.map(t => t.cumulative_strain);

            bValueChart.data.labels = labels;
            bValueChart.data.datasets[0].data = bVals;
            bValueChart.data.datasets[1].data = new Array(labels.length).fill(1.0);
            bValueChart.data.datasets[2].data = new Array(labels.length).fill(0.75);
            bValueChart.update();

            strainChart.data.labels = labels;
            strainChart.data.datasets[0].data = strains;
            strainChart.update();
        }
    } catch (e) {
        console.error("Failed to load zone detail", e);
    }
}

// Fetch B2B Oracles
async function fetchOracles() {
    // 1. Cat Bond Oracle
    try {
        const resCat = await fetch("/api/oracle/catbonds");
        const dataCat = await resCat.json();
        const catList = document.getElementById("catbondList");
        if (dataCat.triggers && dataCat.triggers.length > 0) {
            catList.innerHTML = dataCat.triggers.map(t => `
                <div class="item-card" style="border-color: #ef4444;">
                    <div class="item-title text-danger">🚨 [TRIGGERED] ${t.contract_id}</div>
                    <div class="item-meta">지진: M${t.trigger_event.magnitude} (${t.trigger_event.place})</div>
                    <div class="item-action">자동 정산: ${t.action} (지급비율 ${t.payout_factor*100}%)</div>
                </div>
            `).join("");
        } else {
            catList.innerHTML = '<div class="oracle-empty">최근 60일간 트리거 조건(M6.5+ 천발 지진) 부합 사건 없음 (정상)</div>';
        }
    } catch (e) { console.error(e); }

    // 2. Supply Chain Sentinel
    try {
        const resSup = await fetch("/api/b2b/supply-chain");
        const dataSup = await resSup.json();
        const supList = document.getElementById("supplyChainList");
        supList.innerHTML = dataSup.assets.map(a => `
            <div class="item-card">
                <div class="item-title">${a.facility_name}</div>
                <div class="item-meta">상태: <b class="text-accent">${a.facility_status}</b> | 위험지수: ${a.local_risk_score*100}점</div>
                <div class="item-action">권고: ${a.actionable_recommendation}</div>
            </div>
        `).join("");
    } catch (e) { console.error(e); }

    // 3. Commodity Futures
    try {
        const resCom = await fetch("/api/b2b/commodity-hedge");
        const dataCom = await resCom.json();
        const comList = document.getElementById("commodityList");
        comList.innerHTML = dataCom.signals.map(s => `
            <div class="item-card">
                <div class="item-title">${s.commodity} - ${s.asset_name}</div>
                <div class="item-meta">선물 티커: <b>${s.futures_ticker}</b> | 신뢰도: ${s.signal_confidence}</div>
                <div class="item-action">포지션: ${s.quant_signal}</div>
            </div>
        `).join("");
    } catch (e) { console.error(e); }
}
