/**
 * Leaflet 島 — ほ場ポリゴンの描画 / 編集 / 削除
 *
 * HTML 側で <script id="field-map-data" type="application/json"> に
 * 初期データ {center, zoom, geojson} を埋め込む前提。
 * <form id="polygon-form"> 内の <input name="geojson"> に GeoJSON を流し込んで POST。
 */
(function () {
  const meta = JSON.parse(document.getElementById('field-map-data').textContent);

  const map = L.map('map').setView(meta.center, meta.zoom);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 19,
  }).addTo(map);

  const drawnItems = new L.FeatureGroup().addTo(map);

  if (meta.geojson) {
    L.geoJSON(meta.geojson).eachLayer((l) => drawnItems.addLayer(l));
    if (drawnItems.getLayers().length) {
      map.fitBounds(drawnItems.getBounds(), { maxZoom: 17 });
    }
  }

  const drawControl = new L.Control.Draw({
    edit: { featureGroup: drawnItems, remove: true },
    draw: {
      polygon: { showArea: true, allowIntersection: false },
      polyline: false,
      rectangle: false,
      circle: false,
      marker: false,
      circlemarker: false,
    },
  });
  map.addControl(drawControl);

  map.on(L.Draw.Event.CREATED, (e) => {
    drawnItems.clearLayers();
    drawnItems.addLayer(e.layer);
  });

  const form = document.getElementById('polygon-form');
  const input = document.getElementById('geojson-input');
  form.addEventListener('submit', () => {
    const layers = drawnItems.getLayers();
    input.value = layers.length ? JSON.stringify(layers[0].toGeoJSON()) : '';
  });

  document.getElementById('clear-btn').addEventListener('click', () => {
    if (confirm('描画を全部消しますか？ （保存ボタンを押すまで DB は更新されません）')) {
      drawnItems.clearLayers();
    }
  });

  // --- 筆ポリゴン (農水省 open.fude.maff.go.jp) レイヤー ---
  // トグル ON で現在ビュー(bbox)の筆ポリゴンを表示し、クリックでその筆を
  // このほ場のポリゴンとして採用する（＝手描きの代わり）。
  const fudeToggle = document.getElementById('fude-toggle');
  if (fudeToggle) {
    const fudeInfo = document.getElementById('fude-info');
    let fudeLayer = null;
    const setInfo = (msg) => { if (fudeInfo) fudeInfo.textContent = msg; };

    async function loadFude() {
      if (fudeLayer) { map.removeLayer(fudeLayer); fudeLayer = null; }
      if (!fudeToggle.checked) { setInfo(''); return; }
      if (map.getZoom() < 14) { setInfo('ズーム14以上に拡大すると筆ポリゴンを表示します'); return; }
      const b = map.getBounds();
      const url = `/fields/fude?min_lat=${b.getSouth()}&min_lng=${b.getWest()}`
                + `&max_lat=${b.getNorth()}&max_lng=${b.getEast()}`;
      setInfo('筆ポリゴン読み込み中…');
      let data;
      try {
        const res = await fetch(url, { credentials: 'same-origin' });
        data = await res.json();
      } catch (e) { setInfo('筆ポリゴンの取得に失敗しました'); return; }
      if (!data.available) {
        setInfo('筆ポリゴンデータ未配置。農水省 open.fude.maff.go.jp で規約同意→DL→ data/fude_cache/ に配置してください');
        fudeToggle.checked = false;
        return;
      }
      fudeLayer = L.layerGroup().addTo(map);
      data.polygons.forEach((p) => {
        const poly = L.polygon(p.coordinates, {
          color: '#e07a00', weight: 1, fillColor: '#ffae42', fillOpacity: 0.15,
        });
        poly.on('click', () => {
          drawnItems.clearLayers();
          drawnItems.addLayer(L.polygon(p.coordinates, { color: '#3388ff' }));
          const a = p.area_ha ? p.area_ha.toFixed(2) + 'ha' : '面積不明';
          setInfo(`筆を採用しました (${a})。「保存」で確定します。`);
        });
        fudeLayer.addLayer(poly);
      });
      setInfo(`筆ポリゴン ${data.count} 件表示（クリックで採用）`);
    }

    fudeToggle.addEventListener('change', loadFude);
    map.on('moveend', () => { if (fudeToggle.checked) loadFude(); });
  }
})();
