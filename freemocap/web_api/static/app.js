/* FreeMoCap Web Companion – frontend logic */
'use strict';

const API = '';  // same origin; update to 'http://<server-ip>:8000' if needed
const PROCESS_API = `${API}/api/process`;

// ── Toast notification ───────────────────────────────────────────────────────
let _toastTimer = null;
function toast(msg, duration = 3000) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => el.classList.remove('show'), duration);
}

// ── Badge helper ─────────────────────────────────────────────────────────────
function statusBadge(status) {
  const cls = `badge-${status || 'pending'}`;
  return `<span class="status-badge ${cls}">${status || 'pending'}</span>`;
}

// ── Upload ────────────────────────────────────────────────────────────────────
async function uploadVideos() {
  const input = document.getElementById('video-input');
  const btn   = document.getElementById('upload-btn');
  const wrap  = document.getElementById('upload-progress-wrap');
  const bar   = document.getElementById('upload-progress-bar');

  if (!input.files || input.files.length === 0) {
    toast('⚠️ Please select at least one video file.');
    return;
  }

  const formData = new FormData();
  for (const file of input.files) {
    formData.append('files', file);
  }

  btn.disabled = true;
  wrap.classList.add('visible');
  bar.style.width = '10%';

  try {
    const resp = await fetch(`${API}/api/recordings/upload`, {
      method: 'POST',
      body: formData,
    });

    bar.style.width = '90%';

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || 'Upload failed');
    }

    const data = await resp.json();
    bar.style.width = '100%';
    toast(`✅ Uploaded! Recording ID: ${data.recording_id}`);
    input.value = '';
    setTimeout(() => {
      wrap.classList.remove('visible');
      bar.style.width = '0%';
    }, 1000);
    loadRecordings();
  } catch (err) {
    toast(`❌ ${err.message}`);
    bar.style.width = '0%';
    wrap.classList.remove('visible');
  } finally {
    btn.disabled = false;
  }
}

// ── List recordings ───────────────────────────────────────────────────────────
async function loadRecordings() {
  const list = document.getElementById('recordings-list');
  list.innerHTML = '<li style="color:var(--muted);font-size:0.9rem;">Loading…</li>';

  try {
    const resp = await fetch(`${API}/api/recordings`);
    if (!resp.ok) throw new Error(resp.statusText);
    const recordings = await resp.json();

    if (recordings.length === 0) {
      list.innerHTML = '<li style="color:var(--muted);font-size:0.9rem;">No recordings yet. Upload some videos above.</li>';
      return;
    }

    list.innerHTML = recordings.map(rec => `
      <li>
        <span class="rec-name" title="${rec.id}">${rec.name}</span>
        <div class="rec-actions">
          <button class="secondary" style="font-size:0.8rem;padding:0.3rem 0.7rem;"
                  onclick="checkStatus('${rec.id}', this)">📋 Status</button>
          <button style="font-size:0.8rem;padding:0.3rem 0.7rem;"
                  onclick="startProcessing('${rec.id}', this)">▶️ Process</button>
        </div>
      </li>
    `).join('');
  } catch (err) {
    list.innerHTML = `<li style="color:#ff7f7f;">Error loading recordings: ${err.message}</li>`;
  }
}

// ── Status check ──────────────────────────────────────────────────────────────
async function checkStatus(recordingId, btn) {
  btn.disabled = true;
  try {
    const resp = await fetch(`${PROCESS_API}/${encodeURIComponent(recordingId)}`);
    if (!resp.ok) throw new Error(resp.statusText);
    const data = await resp.json();

    const badge = statusBadge(data.status);
    const errMsg = data.error ? ` — ${data.error}` : '';
    toast(`${data.recording_id}: ${data.status}${errMsg}`, 5000);

    // Inject badge next to button
    const existing = btn.parentElement.querySelector('.status-badge');
    if (existing) existing.remove();
    btn.insertAdjacentHTML('afterend', badge);
  } catch (err) {
    toast(`❌ ${err.message}`);
  } finally {
    btn.disabled = false;
  }
}

// ── Polling registry – one interval per recording ─────────────────────────────
const _pollIntervals = {};

function _stopPolling(recordingId) {
  if (_pollIntervals[recordingId] != null) {
    clearInterval(_pollIntervals[recordingId]);
    delete _pollIntervals[recordingId];
  }
}

// Stop all polls on page unload to avoid memory leaks
window.addEventListener('beforeunload', () => {
  Object.keys(_pollIntervals).forEach(_stopPolling);
});

// ── Start processing ──────────────────────────────────────────────────────────
async function startProcessing(recordingId, btn) {
  if (!confirm(`Start processing recording:\n${recordingId}?\n\nThis may take several minutes.`)) return;

  btn.disabled = true;
  _stopPolling(recordingId);  // cancel any previous poll for this recording

  try {
    const resp = await fetch(
      `${PROCESS_API}/${encodeURIComponent(recordingId)}`,
      { method: 'POST' }
    );
    const data = await resp.json();

    if (!resp.ok) {
      throw new Error(data.detail || resp.statusText);
    }

    toast(`🚀 Processing started for ${recordingId}`, 4000);

    // Poll status every 5 s
    _pollIntervals[recordingId] = setInterval(async () => {
      try {
        const statusResponse = await fetch(`${PROCESS_API}/${encodeURIComponent(recordingId)}`);
        const statusData = await statusResponse.json();
        if (statusData.status === 'complete' || statusData.status === 'failed') {
          _stopPolling(recordingId);
          btn.disabled = false;
          const msg = statusData.status === 'complete'
            ? `✅ Processing complete for ${recordingId}`
            : `❌ Processing failed for ${recordingId}: ${statusData.error}`;
          toast(msg, 6000);
        }
      } catch (_) { /* ignore transient errors */ }
    }, 5000);

  } catch (err) {
    toast(`❌ ${err.message}`);
    btn.disabled = false;
  }
}
