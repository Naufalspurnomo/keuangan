(() => {
  'use strict'

  const $ = (id) => document.getElementById(id)
  const form = $('presensi-form')
  const employee = $('employee')
  const project = $('project')
  const action = $('action')
  const badge = $('action-badge')
  const notice = $('notice')
  const video = $('camera')
  const preview = $('selfie-preview')
  const placeholder = $('camera-placeholder')
  const openCameraButton = $('open-camera')
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
  let activeProject = null

  const escapeText = (value) => String(value ?? '')
  const actionLabel = () => action.value === 'check_out' ? 'Check-out' : 'Check-in'

  function showNotice(message, tone = 'error') {
    notice.hidden = false
    notice.className = `notice ${tone}`
    notice.textContent = message
  }

  function clearNotice() {
    notice.hidden = true
    notice.textContent = ''
  }

  function stopCamera() {
    if (stream) stream.getTracks().forEach((track) => track.stop())
    stream = null
    video.srcObject = null
  }

  function updateSubmit() {
    const ready = Boolean(employee.value && project.value && selfieBlob && position && !busy)
    submitButton.disabled = !ready
    submitButton.querySelector('span').textContent = busy ? 'Mengirim bukti…' : `Kirim ${actionLabel()}`
    submitButton.querySelector('small').textContent = ready ? 'Waktu final menggunakan waktu server' : 'Selfie dan lokasi wajib lengkap'
  }

  function resetProof() {
    stopCamera()
    if (preview.src) URL.revokeObjectURL(preview.src)
    selfieBlob = null
    selfieObservedAtMs = 0
    position = null
    locationObservedAtMs = 0
    video.hidden = true
    preview.hidden = true
    preview.removeAttribute('src')
    placeholder.hidden = false
    captureButton.disabled = true
    retakeButton.hidden = true
    openCameraButton.hidden = false
    cameraState.textContent = 'Belum siap'
    cameraState.className = 'state-pill'
    locationState.textContent = 'Belum siap'
    locationState.className = 'state-pill'
    locationCopy.textContent = 'Aktifkan GPS untuk melanjutkan'
    locationDetail.textContent = 'Koordinat dan akurasi GPS akan disimpan bersama selfie.'
    updateSubmit()
  }

  function setAction(nextAction) {
    action.value = nextAction
    const label = nextAction === 'check_out' ? 'CHECK-OUT' : 'CHECK-IN'
    badge.textContent = label
    badge.className = `action-badge ${nextAction === 'check_out' ? 'checkout' : ''}`
    updateSubmit()
  }

  async function loadBootstrap() {
    const response = await fetch('/absen/api/bootstrap.php', { credentials: 'same-origin', cache: 'no-store' })
    if (!response.ok) throw new Error('Formulir presensi belum tersedia.')
    const payload = await response.json()
    csrf = payload.csrf
    captureToken = payload.capture_token
    for (const row of payload.employees) {
      const option = document.createElement('option')
      option.value = row.id
      option.textContent = row.name
      employee.append(option)
    }
    for (const row of payload.projects) {
      const option = document.createElement('option')
      option.value = row.id
      option.textContent = `${row.name} · ${row.company}`
      project.append(option)
    }
    employee.disabled = false
    project.disabled = false
  }

  async function loadStatus(preserveNotice = false) {
    resetProof()
    activeProject = null
    setAction('check_in')
    project.disabled = !employee.value
    for (const option of project.options) option.disabled = false
    if (!employee.value) return
    if (!preserveNotice) clearNotice()
    try {
      const response = await fetch(`/absen/api/status.php?employee_id=${encodeURIComponent(employee.value)}`, { credentials: 'same-origin', cache: 'no-store' })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload?.error?.message || 'Status presensi belum tersedia.')
      setAction(payload.next_action)
      if (payload.active_project) {
        activeProject = payload.active_project
        project.value = payload.active_project.id
        project.disabled = true
        if (!preserveNotice) showNotice(`${payload.employee.name} sedang aktif di ${payload.active_project.name}. Lanjutkan Check-out pada proyek yang sama.`, 'info')
      }
    } catch (error) {
      project.disabled = true
      showNotice(error instanceof Error ? error.message : 'Status presensi belum tersedia.')
    }
  }

  async function openCamera() {
    clearNotice()
    resetProof()
    if (!navigator.mediaDevices?.getUserMedia) {
      showNotice('Browser ini tidak mendukung kamera langsung. Gunakan Chrome atau Safari terbaru.')
      return
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'user' }, width: { ideal: 1280 }, height: { ideal: 960 } }, audio: false })
      video.srcObject = stream
      video.hidden = false
      placeholder.hidden = true
      openCameraButton.hidden = true
      cameraState.textContent = 'Menyiapkan kamera'
      cameraState.className = 'state-pill working'
      await video.play()
      await new Promise((resolve, reject) => {
        const deadline = window.setTimeout(() => reject(new Error('Kamera belum menghasilkan gambar. Coba lagi.')), 5000)
        const ready = () => {
          if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA && video.videoWidth >= 320 && video.videoHeight >= 240) {
            window.clearTimeout(deadline)
            requestAnimationFrame(() => requestAnimationFrame(resolve))
          } else {
            requestAnimationFrame(ready)
          }
        }
        ready()
      })
      captureButton.disabled = false
      cameraState.textContent = 'Kamera aktif'
      cameraState.className = 'state-pill ready'
    } catch {
      showNotice('Izin kamera ditolak atau kamera tidak tersedia. Kamera wajib aktif untuk presensi.')
      resetProof()
    }
  }

  function getLocation() {
    return new Promise((resolve, reject) => {
      if (!navigator.geolocation) return reject(new Error('Perangkat tidak mendukung lokasi.'))
      navigator.geolocation.getCurrentPosition(resolve, () => reject(new Error('Lokasi presisi tidak dapat dibaca. Aktifkan GPS dan izin lokasi.')), {
        enableHighAccuracy: true,
        timeout: 15000,
        maximumAge: 0,
      })
    })
  }

  function frameBlob() {
    return new Promise((resolve, reject) => {
      const width = video.videoWidth || 960
      const height = video.videoHeight || 720
      const canvas = document.createElement('canvas')
      canvas.width = width
      canvas.height = height
      const context = canvas.getContext('2d')
      if (!context) return reject(new Error('Selfie tidak dapat diproses.'))
      context.translate(width, 0)
      context.scale(-1, 1)
      context.drawImage(video, 0, 0, width, height)
      canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error('Selfie tidak dapat diproses.')), 'image/jpeg', 0.86)
    })
  }

  async function captureProof() {
    if (!stream) return
    clearNotice()
    captureButton.disabled = true
    captureButton.textContent = 'Membaca kamera & GPS…'
    locationState.textContent = 'Mencari GPS'
    locationState.className = 'state-pill working'
    try {
      const [blob, observed] = await Promise.all([frameBlob(), getLocation()])
      selfieBlob = blob
      selfieObservedAtMs = Date.now()
      position = observed.coords
      locationObservedAtMs = Number(observed.timestamp) || Date.now()
      stopCamera()
      preview.src = URL.createObjectURL(blob)
      preview.hidden = false
      video.hidden = true
      placeholder.hidden = true
      retakeButton.hidden = false
      openCameraButton.hidden = true
      cameraState.textContent = 'Selfie siap'
      cameraState.className = 'state-pill ready'
      locationState.textContent = 'GPS siap'
      locationState.className = 'state-pill ready'
      locationCopy.textContent = `${position.latitude.toFixed(6)}, ${position.longitude.toFixed(6)}`
      locationDetail.textContent = `Akurasi ±${Math.round(position.accuracy)} m · lokasi akan tersimpan bersama selfie.`
    } catch (error) {
      showNotice(error instanceof Error ? error.message : 'Bukti presensi belum lengkap.')
      selfieBlob = null
      selfieObservedAtMs = 0
      position = null
      locationObservedAtMs = 0
      locationState.textContent = 'GPS gagal'
      locationState.className = 'state-pill error'
      captureButton.disabled = false
    } finally {
      captureButton.textContent = 'Ambil selfie & lokasi'
      updateSubmit()
    }
  }

  async function submitPresensi(event) {
    event.preventDefault()
    if (!selfieBlob || !position || !employee.value || !project.value || busy) return
    clearNotice()
    busy = true
    updateSubmit()
    const body = new FormData()
    body.set('csrf', csrf)
    body.set('capture_token', captureToken)
    body.set('employee_id', employee.value)
    body.set('project_id', project.value)
    body.set('action', action.value)
    body.set('latitude', String(position.latitude))
    body.set('longitude', String(position.longitude))
    body.set('accuracy_m', String(position.accuracy))
    body.set('location_observed_at_ms', String(locationObservedAtMs))
    body.set('selfie_observed_at_ms', String(selfieObservedAtMs))
    body.set('selfie', selfieBlob, 'selfie.jpg')
    try {
      const response = await fetch('/absen/api/submit.php', { method: 'POST', body, credentials: 'same-origin', cache: 'no-store' })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload?.error?.message || 'Presensi belum dapat dikirim.')
      csrf = payload.csrf
      captureToken = payload.capture_token
      showNotice(`${payload.record.employee_name} berhasil ${payload.record.action === 'check_in' ? 'Check-in' : 'Check-out'} di ${payload.record.project_name}. Lokasi tersimpan dengan akurasi ±${Math.round(payload.record.accuracy_m)} m.`, 'success')
      await loadStatus(true)
    } catch (error) {
      showNotice(error instanceof Error ? error.message : 'Presensi belum dapat dikirim.')
    } finally {
      busy = false
      updateSubmit()
    }
  }

  employee.addEventListener('change', loadStatus)
  project.addEventListener('change', () => { resetProof(); clearNotice() })
  openCameraButton.addEventListener('click', openCamera)
  captureButton.addEventListener('click', captureProof)
  retakeButton.addEventListener('click', openCamera)
  form.addEventListener('submit', submitPresensi)
  window.addEventListener('pagehide', stopCamera)

  loadBootstrap().catch((error) => showNotice(error instanceof Error ? error.message : 'Formulir presensi belum tersedia.'))
})()
