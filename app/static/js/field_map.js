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
})();
