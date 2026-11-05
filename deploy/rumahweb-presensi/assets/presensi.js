(() => {
  'use strict'
  const $ = (id) => document.getElementById(id)
  const loginCard = $('login-card')
  const loginForm = $('login-form')
  const loginNotice = $('login-notice')
  const loginButton = $('login-button')
  const presensiCard = $('presensi-card')
  const form = $('presensi-form')
  const project = $('project')
  const action = $('action')
  const badge = $('action-badge')
  const notice = $('notice')
  const video = $('camera')
  const preview = $('selfie-preview')
  const placeholder = $('camera-placeholder')
  const openCameraButton = $('open-camera')
  const cameraRequirements = $('camera-requirements')
  const captureButton = $('capture-selfie')
  const retakeButton = $('retake-selfie')
  const cameraState = $('camera-state')
  const locationState = $('location-state')
  const locationCopy = $('location-copy')
  const locationDetail = $('location-detail')
  const submitButton = $('submit-presensi')

  let csrf = ''
  let captureToken = ''
  let stream = null
  let selfieBlob = null
  let selfieObservedAtMs = 0
  let position = null
  let locationObservedAtMs = 0
  let busy = false
  let cameraBusy = false
  let statusBusy = false
  let activeProject = null
  let submissionId = null
  let hasActiveProjects = false
  let authenticated = false

  function newSubmissionId() {
    const bytes = crypto.getRandomValues(new Uint8Array(16))
    return `sub-${[...bytes].map((byte) => byte.toString(16).padStart(2, '0')).join('')}`
  }
  function show(element, message, tone = 'error', retry = null) {
    element.hidden = false
    element.className = `notice ${tone}`
    element.textContent = message
    if (retry) {
      const button = document.createElement('button')
      button.type = 'button'; button.className = 'notice-action'; button.textContent = 'Coba lagi'
      button.addEventListener('click', retry, { once: true }); element.append(button)
    }
  }
  function clear(element) { element.hidden = true; element.textContent = '' }
  function stopCamera() { if (stream) stream.getTracks().forEach((track) => track.stop()); stream = null; video.srcObject = null }
  function showLogin(message = '') {
    authenticated = false; stopCamera(); presensiCard.hidden = true; loginCard.hidden = false
    if (message) show(loginNotice, message); else clear(loginNotice)
    $('employee-pin').value = ''
  }
  function updateCameraAvailability() {
    const ready = Boolean(authenticated && project.value && !cameraBusy && !statusBusy && !busy)
    openCameraButton.disabled = !ready
    cameraRequirements.textContent = ready ? 'Kamera siap diaktifkan.' : 'Pilih proyek terlebih dahulu.'
  }
  const actionLabel = () => action.value === 'check_out' ? 'Check-out' : 'Check-in'
  function updateSubmit() {
    const ready = Boolean(authenticated && project.value && selfieBlob && position && !busy)
    submitButton.disabled = !ready
    submitButton.querySelector('span').textContent = busy ? 'Mengirim bukti…' : `Kirim ${actionLabel()}`
    submitButton.querySelector('small').textContent = ready ? 'Waktu final menggunakan waktu server' : 'Selfie dan lokasi wajib lengkap'
  }
  function resetProof() {
    stopCamera()
    if (preview.src) URL.revokeObjectURL(preview.src)
    selfieBlob = null; selfieObservedAtMs = 0; position = null; locationObservedAtMs = 0
    video.hidden = true; preview.hidden = true; preview.removeAttribute('src'); placeholder.hidden = false
    captureButton.disabled = true; retakeButton.hidden = true; openCameraButton.hidden = false
    cameraState.textContent = 'Belum siap'; cameraState.className = 'state-pill'
    locationState.textContent = 'Belum siap'; locationState.className = 'state-pill'
    locationCopy.textContent = 'Aktifkan GPS untuk melanjutkan'
    locationDetail.textContent = 'Koordinat dan akurasi tersimpan bersama selfie.'
    updateCameraAvailability(); updateSubmit()
  }
  function setAction(nextAction) {
    action.value = nextAction
    badge.textContent = nextAction === 'check_out' ? 'CHECK-OUT' : 'CHECK-IN'
    badge.className = `action-badge ${nextAction === 'check_out' ? 'checkout' : ''}`
    updateSubmit()
  }
  async function requestJson(url, options = {}) {
    const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store', ...options })
    let payload = null
    try { payload = await response.json() } catch { payload = null }
    if (!response.ok) {
      const error = new Error(payload?.error?.message || 'Permintaan belum dapat diproses.')
      error.status = response.status; error.authoritative = response.status < 500
      throw error
    }
    return payload
  }
  function populateProjects(rows) {
    project.replaceChildren(new Option('Pilih proyek', ''))
    for (const row of rows) project.append(new Option(`${row.name} · ${row.company}`, row.id))
    hasActiveProjects = rows.length > 0
    if (!hasActiveProjects) project.options[0].textContent = 'Tidak ada proyek aktif'
  }
  async function loadBootstrap() {
    const payload = await requestJson('/absen/api/bootstrap.php')
    csrf = payload.csrf
    if (!payload.authenticated) { showLogin(); return }
    authenticated = true; captureToken = payload.capture_token
    $('employee-greeting').textContent = `Halo, ${payload.employee.name}`
    populateProjects(payload.projects || [])
    loginCard.hidden = true; presensiCard.hidden = false; project.disabled = !hasActiveProjects
    await loadStatus()
  }
  async function login(event) {
    event.preventDefault()
    if (busy) return
    clear(loginNotice); busy = true; loginButton.disabled = true
    const body = new URLSearchParams({ csrf, code: $('employee-code').value.trim(), pin: $('employee-pin').value })
    try {
      await requestJson('/absen/api/login.php', { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' }, body })
      await loadBootstrap()
    } catch (error) { show(loginNotice, error instanceof Error ? error.message : 'Kode pegawai atau PIN tidak valid.') }
    finally { busy = false; loginButton.disabled = false; updateCameraAvailability(); updateSubmit() }
  }
  async function logout() {
    if (busy) return
    busy = true
    const body = new URLSearchParams({ csrf })
    try { await requestJson('/absen/api/logout.php', { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' }, body }) }
    catch { /* Local screen still closes; server expiry remains bounded. */ }
    finally { busy = false; csrf = ''; captureToken = ''; await loadBootstrap().catch(() => showLogin('Sesi berakhir. Muat ulang halaman.')) }
  }
  async function fetchStatus(exactSubmissionId = null, exactAction = '', exactProject = '') {
    const query = exactSubmissionId ? `?submission_id=${encodeURIComponent(exactSubmissionId)}&submission_action=${encodeURIComponent(exactAction)}&submission_project=${encodeURIComponent(exactProject)}` : ''
    return requestJson(`/absen/api/status.php${query}`)
  }
  async function loadStatus(preserveNotice = false) {
    if (!authenticated) return
    if (!preserveNotice) submissionId = null
    resetProof(); activeProject = null; setAction('check_in'); project.value = ''
    for (const option of [...project.options]) { if (option.dataset.historical === 'true') option.remove(); else option.disabled = false }
    statusBusy = true; project.disabled = true; updateCameraAvailability(); if (!preserveNotice) clear(notice)
    try {
      const payload = await fetchStatus()
      setAction(payload.next_action)
      if (payload.active_project) {
        activeProject = payload.active_project
        if (![...project.options].some((option) => option.value === activeProject.id)) {
          const historical = new Option(`${activeProject.name} · proyek ditutup`, activeProject.id)
          historical.dataset.historical = 'true'; project.append(historical)
        }
        project.value = activeProject.id
        if (!preserveNotice) show(notice, `Anda sedang aktif di ${activeProject.name}. Lanjutkan Check-out pada proyek yang sama.`, 'info')
      } else if (!hasActiveProjects) show(notice, 'Tidak ada proyek aktif untuk Check-in baru.', 'info')
    } catch (error) {
      if (error?.status === 401) { showLogin('Sesi berakhir. Silakan masuk lagi.'); return }
      show(notice, error instanceof Error ? error.message : 'Status presensi belum tersedia.', 'error', () => loadStatus())
    } finally {
      statusBusy = false
      project.disabled = !authenticated || Boolean(activeProject) || !hasActiveProjects
      updateCameraAvailability()
    }
  }
  async function openCamera() {
    if (cameraBusy || !authenticated || !project.value) return
    submissionId = null; clear(notice); cameraBusy = true; resetProof(); updateCameraAvailability()
    if (!navigator.mediaDevices?.getUserMedia) { cameraBusy = false; updateCameraAvailability(); show(notice, 'Browser ini tidak mendukung kamera langsung.'); return }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'user' }, width: { ideal: 1280 }, height: { ideal: 960 } }, audio: false })
      video.srcObject = stream; video.hidden = false; placeholder.hidden = true; openCameraButton.hidden = true
      cameraState.textContent = 'Menyiapkan kamera'; cameraState.className = 'state-pill working'; await video.play()
      await new Promise((resolve, reject) => {
        const deadline = window.setTimeout(() => reject(new Error('Kamera belum menghasilkan gambar.')), 5000)
        const ready = () => video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA && video.videoWidth >= 320 && video.videoHeight >= 240
          ? (window.clearTimeout(deadline), requestAnimationFrame(() => requestAnimationFrame(resolve))) : requestAnimationFrame(ready)
        ready()
      })
      captureButton.disabled = false; cameraState.textContent = 'Kamera aktif'; cameraState.className = 'state-pill ready'
    } catch { show(notice, 'Kamera belum dapat digunakan. Izinkan Kamera lalu coba lagi.'); resetProof() }
    finally { cameraBusy = false; updateCameraAvailability() }
  }
  function getLocation() {
    return new Promise((resolve, reject) => {
      if (!navigator.geolocation) return reject(new Error('Perangkat tidak mendukung lokasi.'))
      navigator.geolocation.getCurrentPosition(resolve, () => reject(new Error('Lokasi belum dapat dibaca. Izinkan Lokasi, aktifkan GPS, lalu coba lagi.')), { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 })
    })
  }
  function frameBlob() {
    return new Promise((resolve, reject) => {
      const canvas = document.createElement('canvas'); canvas.width = video.videoWidth || 960; canvas.height = video.videoHeight || 720
      const context = canvas.getContext('2d'); if (!context) return reject(new Error('Selfie tidak dapat diproses.'))
      context.translate(canvas.width, 0); context.scale(-1, 1); context.drawImage(video, 0, 0, canvas.width, canvas.height)
      canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error('Selfie tidak dapat diproses.')), 'image/jpeg', 0.86)
    })
  }
  async function captureProof() {
    if (!stream) return
    clear(notice); captureButton.disabled = true; captureButton.textContent = 'Membaca kamera & GPS…'; locationState.textContent = 'Mencari GPS'; locationState.className = 'state-pill working'
    try {
      const [blob, observed] = await Promise.all([frameBlob(), getLocation()])
      selfieBlob = blob; selfieObservedAtMs = Date.now(); position = observed.coords; locationObservedAtMs = Number(observed.timestamp) || Date.now(); stopCamera()
      preview.src = URL.createObjectURL(blob); preview.hidden = false; video.hidden = true; placeholder.hidden = true; retakeButton.hidden = false; openCameraButton.hidden = true
      cameraState.textContent = 'Selfie siap'; cameraState.className = 'state-pill ready'; locationState.textContent = 'GPS siap'; locationState.className = 'state-pill ready'
      locationCopy.textContent = `${position.latitude.toFixed(6)}, ${position.longitude.toFixed(6)}`; locationDetail.textContent = `Akurasi ±${Math.round(position.accuracy)} m.`
    } catch (error) { show(notice, error instanceof Error ? error.message : 'Bukti belum lengkap.'); selfieBlob = null; position = null; locationState.textContent = 'GPS gagal'; locationState.className = 'state-pill error'; captureButton.disabled = false }
    finally { captureButton.textContent = 'Ambil selfie & lokasi'; updateSubmit() }
  }
  async function submitPresensi(event) {
    event.preventDefault()
    if (!authenticated || !selfieBlob || !position || !project.value || busy || statusBusy) return
    const submitted = { projectId: project.value, action: action.value, submissionId: submissionId || newSubmissionId() }
    submissionId = submitted.submissionId; clear(notice); busy = true; project.disabled = true; updateCameraAvailability(); updateSubmit()
    const body = new FormData()
    body.set('csrf', csrf); body.set('capture_token', captureToken); body.set('submission_id', submitted.submissionId); body.set('project_id', submitted.projectId); body.set('action', submitted.action)
    body.set('latitude', String(position.latitude)); body.set('longitude', String(position.longitude)); body.set('accuracy_m', String(position.accuracy)); body.set('location_observed_at_ms', String(locationObservedAtMs)); body.set('selfie_observed_at_ms', String(selfieObservedAtMs)); body.set('selfie', selfieBlob, 'selfie.jpg')
    try {
      const payload = await requestJson('/absen/api/submit.php', { method: 'POST', body })
      csrf = payload.csrf; captureToken = payload.capture_token; submissionId = null
      show(notice, `Berhasil ${payload.record.action === 'check_in' ? 'Check-in' : 'Check-out'} di ${payload.record.project_name}.`, 'success'); await loadStatus(true)
    } catch (error) {
      if (error?.status === 401) { showLogin('Sesi berakhir. Silakan masuk lagi.'); return }
      try {
        const state = await fetchStatus(submitted.submissionId, submitted.action, submitted.projectId)
        if (state.submission_received && state.recovery?.csrf && state.recovery?.capture_token) {
          csrf = state.recovery.csrf; captureToken = state.recovery.capture_token; submissionId = null; await loadStatus(true); show(notice, 'Presensi sudah diterima server. Status disinkronkan.', 'success')
        } else { if (error?.authoritative) submissionId = null; await loadStatus(true); show(notice, error.message, 'error') }
      } catch { show(notice, error instanceof Error ? error.message : 'Presensi belum dapat dikirim.', 'error', () => submitButton.click()) }
    } finally { busy = false; project.disabled = Boolean(activeProject) || !hasActiveProjects; updateCameraAvailability(); updateSubmit() }
  }

  loginForm.addEventListener('submit', login)
  $('logout-button').addEventListener('click', logout)
  project.addEventListener('change', () => { submissionId = null; resetProof(); clear(notice) })
  openCameraButton.addEventListener('click', openCamera); captureButton.addEventListener('click', captureProof); retakeButton.addEventListener('click', openCamera)
  form.addEventListener('submit', submitPresensi); window.addEventListener('pagehide', stopCamera)
  loadBootstrap().catch(() => showLogin('Formulir presensi belum tersedia.'))
})()
