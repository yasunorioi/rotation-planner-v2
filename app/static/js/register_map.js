/**
 * 地図から圃場を登録 — 筆ポリゴン(農水省)をクリック→小フォームで新規ほ場作成。
 *
 * <script id="register-map-data" type="application/json"> に {center, zoom} を埋め込む前提。
 * 筆は /fields/fude から取得、作成は /fields/register-from-fude へ POST(JSON応答)。
 */
(function () {
  const meta = JSON.parse(document.getElementById('register-map-data').textContent);
  const map = L.map('map').setView(meta.center, meta.zoom);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 19,
  }).addTo(map);

  const fudeToggle = document.getElementById('fude-toggle');
  const fudeInfo = document.getElementById('fude-info');
  const panel = document.getElementById('register-panel');
  const fCode = document.getElementById('f-code');
  const fName = document.getElementById('f-name');
  const fDistrict = document.getElementById('f-district');
  const fArea = document.getElementById('f-area');
  const createBtn = document.getElementById('create-btn');
  const formMsg = document.getElementById('form-msg');
  const createdList = document.getElementById('created-list');

  const STYLE_FUDE = { color: '#e07a00', weight: 1, fillColor: '#ffae42', fillOpacity: 0.15 };
  const STYLE_SELECTED = { color: '#3388ff', weight: 2, fillColor: '#3388ff', fillOpacity: 0.3 };
  const STYLE_DONE = { color: '#2d6a4f', weight: 2, fillColor: '#40916c', fillOpacity: 0.4 };

  let fudeLayer = null;
  let selected = null;              // {layer, feature, area}
  const registered = new WeakSet(); // 登録済みの L.polygon
  const setInfo = (m) => { fudeInfo.textContent = m; };

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
      data = await (await fetch(url, { credentials: 'same-origin' })).json();
    } catch (e) { setInfo('筆ポリゴンの取得に失敗しました'); return; }
    if (!data.available) {
      setInfo('筆ポリゴンデータ未配置。農水省 open.fude.maff.go.jp で規約同意→DL→ data/fude_cache/ に配置してください');
      fudeToggle.checked = false;
      return;
    }
    fudeLayer = L.layerGroup().addTo(map);
    data.polygons.forEach((p) => {
      const poly = L.polygon(p.coordinates, STYLE_FUDE);
      poly.on('click', () => selectParcel(poly, p));
      fudeLayer.addLayer(poly);
    });
    setInfo(`筆ポリゴン ${data.count} 件（クリックで選択）`);
  }

  function selectParcel(layer, p) {
    if (selected && selected.layer && !registered.has(selected.layer)) {
      selected.layer.setStyle(STYLE_FUDE);
    }
    selected = { layer, feature: layer.toGeoJSON(), area: p.area_ha };
    layer.setStyle(STYLE_SELECTED);
    fArea.value = p.area_ha ? p.area_ha.toFixed(2) : '';
    formMsg.textContent = '';
    panel.classList.add('open');
    fCode.focus();
  }

  createBtn.addEventListener('click', async () => {
    if (!selected) { formMsg.textContent = '先に地図で筆を選んでください'; return; }
    if (!fCode.value.trim()) { formMsg.textContent = 'ほ場コードは必須です'; fCode.focus(); return; }
    const body = new URLSearchParams();
    body.set('field_code', fCode.value.trim());
    body.set('name', fName.value.trim());
    body.set('district', fDistrict.value.trim());
    body.set('area_ha', fArea.value || '0');
    body.set('geojson', JSON.stringify(selected.feature));
    createBtn.disabled = true;
    let data;
    try {
      const res = await fetch('/fields/register-from-fude',
        { method: 'POST', credentials: 'same-origin', body });
      data = await res.json();
    } catch (e) { formMsg.textContent = '通信に失敗しました'; createBtn.disabled = false; return; }
    createBtn.disabled = false;
    if (!data.ok) { formMsg.textContent = data.error || '作成に失敗しました'; return; }
    // 成功: その筆を緑で固定しラベル付与
    const layer = selected.layer;
    registered.add(layer);
    layer.off('click');
    layer.setStyle(STYLE_DONE);
    layer.bindTooltip(data.field_code, { permanent: true, direction: 'center', className: 'fude-label' });
    const li = document.createElement('li');
    li.textContent = `${data.field_code} を登録しました`;
    createdList.appendChild(li);
    // クリアして次の筆へ
    selected = null;
    fCode.value = ''; fName.value = ''; fArea.value = '';
    panel.classList.remove('open');
  });

  fudeToggle.addEventListener('change', loadFude);
  map.on('moveend', () => { if (fudeToggle.checked) loadFude(); });
  loadFude();  // トグルは既定 ON
})();
