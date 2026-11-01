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
  let statusRequest = 0
  let activeProject = null
  let submissionId = null
  let hasActiveProjects = false

  function newSubmissionId() {
    const bytes = crypto.getRandomValues(new Uint8Array(16))
    return `sub-${[...bytes].map((byte) => byte.toString(16).padStart(2, '0')).join('')}`
  }

  function updateCameraAvailability() {
    const ready = Boolean(employee.value && project.value && !cameraBusy && !statusBusy && !busy)
    openCameraButton.disabled = !ready
    cameraRequirements.textContent = ready
      ? 'Kamera siap diaktifkan untuk pegawai dan proyek terpilih.'
      : 'Pilih pegawai dan proyek terlebih dahulu.'
  }

  const escapeText = (value) => String(value ?? '')
  const actionLabel = () => action.value === 'check_out' ? 'Check-out' : 'Check-in'

  function showNotice(message, tone = 'error', retry = null) {
    notice.hidden = false
    notice.className = `notice ${tone}`
    notice.textContent = message
    if (retry) {
      const button = document.createElement('button')
      button.type = 'button'
      button.className = 'notice-action'
      button.textContent = 'Coba lagi'
      button.addEventListener('click', retry, { once: true })
      notice.append(button)
    }
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
    updateCameraAvailability()
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
    hasActiveProjects = payload.projects.length > 0
    if (!hasActiveProjects) project.options[0].textContent = 'Tidak ada proyek aktif'
    employee.disabled = false
    project.disabled = !hasActiveProjects
  }

  async function fetchStatus(selectedEmployee, exactSubmissionId = null, exactAction = '', exactProject = '') {
    const submissionQuery = exactSubmissionId
      ? `&submission_id=${encodeURIComponent(exactSubmissionId)}&submission_action=${encodeURIComponent(exactAction)}&submission_project=${encodeURIComponent(exactProject)}`
      : ''
    const response = await fetch(`/absen/api/status.php?employee_id=${encodeURIComponent(selectedEmployee)}${submissionQuery}`, { credentials: 'same-origin', cache: 'no-store' })
    const payload = await response.json()
    if (!response.ok) throw new Error(payload?.error?.message || 'Status presensi belum tersedia.')
    return payload
  }

  async function loadStatus(preserveNotice = false) {
    if (!preserveNotice) submissionId = null
    resetProof()
    activeProject = null
    setAction('check_in')
    const selectedEmployee = employee.value
    const requestId = ++statusRequest
    let resolved = false
    project.value = ''
    for (const option of [...project.options]) {
      if (option.dataset.historical === 'true') option.remove()
      else option.disabled = false
    }
    if (!selectedEmployee) {
      statusBusy = false
      employee.disabled = false
      project.disabled = !hasActiveProjects
      updateCameraAvailability()
      return
    }
    statusBusy = true
    employee.disabled = true
    project.disabled = true
    updateCameraAvailability()
    if (!preserveNotice) clearNotice()
    try {
      const payload = await fetchStatus(selectedEmployee)
      if (requestId !== statusRequest || employee.value !== selectedEmployee) return
      resolved = true
      setAction(payload.next_action)
      if (payload.active_project) {
        activeProject = payload.active_project
        if (![...project.options].some((option) => option.value === payload.active_project.id)) {
          const historical = document.createElement('option')
          historical.value = payload.active_project.id
          historical.textContent = `${payload.active_project.name} · proyek ditutup`
          historical.dataset.historical = 'true'
          project.append(historical)
        }
        project.value = payload.active_project.id
        if (!preserveNotice) showNotice(`${payload.employee.name} sedang aktif di ${payload.active_project.name}. Lanjutkan Check-out pada proyek yang sama.`, 'info')
      } else if (!hasActiveProjects) {
        showNotice('Tidak ada proyek aktif untuk Check-in baru. Pilih pegawai lain hanya untuk memeriksa status.', 'info')
      }
    } catch (error) {
      if (requestId !== statusRequest || employee.value !== selectedEmployee) return
      showNotice(error instanceof Error ? error.message : 'Status presensi belum tersedia.', 'error', () => loadStatus())
    } finally {
      if (requestId === statusRequest && employee.value === selectedEmployee) {
        statusBusy = false
        employee.disabled = false
        project.disabled = !resolved || Boolean(activeProject) || !hasActiveProjects
        updateCameraAvailability()
      }
    }
  }

  async function openCamera() {
    if (cameraBusy || !employee.value || !project.value) return
    submissionId = null
    clearNotice()
    cameraBusy = true
    resetProof()
    updateCameraAvailability()
    if (!navigator.mediaDevices?.getUserMedia) {
      cameraBusy = false
      updateCameraAvailability()
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
      showNotice('Kamera belum dapat digunakan. Buka pengaturan situs pada ikon di bilah alamat, izinkan Kamera, lalu pilih Aktifkan kamera lagi.')
      resetProof()
    } finally {
      cameraBusy = false
      updateCameraAvailability()
    }
  }

  function getLocation() {
    return new Promise((resolve, reject) => {
      if (!navigator.geolocation) return reject(new Error('Perangkat tidak mendukung lokasi.'))
      navigator.geolocation.getCurrentPosition(resolve, () => reject(new Error('Lokasi belum dapat dibaca. Buka pengaturan situs pada ikon di bilah alamat, izinkan Lokasi, aktifkan GPS, lalu coba lagi.')), {
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
    if (!selfieBlob || !position || !employee.value || !project.value || busy || statusBusy) return
    const submitted = {
      employeeId: employee.value,
      projectId: project.value,
      action: action.value,
      submissionId: submissionId || newSubmissionId(),
    }
    submissionId = submitted.submissionId
    clearNotice()
    busy = true
    employee.disabled = true
    project.disabled = true
    updateCameraAvailability()
    updateSubmit()
    const body = new FormData()
    body.set('csrf', csrf)
    body.set('capture_token', captureToken)
    body.set('submission_id', submitted.submissionId)
    body.set('employee_id', submitted.employeeId)
    body.set('project_id', submitted.projectId)
    body.set('action', submitted.action)
    body.set('latitude', String(position.latitude))
    body.set('longitude', String(position.longitude))
    body.set('accuracy_m', String(position.accuracy))
    body.set('location_observed_at_ms', String(locationObservedAtMs))
    body.set('selfie_observed_at_ms', String(selfieObservedAtMs))
    body.set('selfie', selfieBlob, 'selfie.jpg')
    try {
      const response = await fetch('/absen/api/submit.php', { method: 'POST', body, credentials: 'same-origin', cache: 'no-store' })
      const payload = await response.json()
      if (!response.ok) {
        const failure = new Error(payload?.error?.message || 'Presensi belum dapat dikirim.')
        failure.authoritative = response.status < 500
        throw failure
      }
      csrf = payload.csrf
      captureToken = payload.capture_token
      submissionId = null
      showNotice(`${payload.record.employee_name} berhasil ${payload.record.action === 'check_in' ? 'Check-in' : 'Check-out'} di ${payload.record.project_name}. Lokasi tersimpan dengan akurasi ±${Math.round(payload.record.accuracy_m)} m.`, 'success')
      await loadStatus(true)
    } catch (error) {
      if (error?.authoritative) {
        try {
          const state = await fetchStatus(submitted.employeeId, submitted.submissionId, submitted.action, submitted.projectId)
          if (state.submission_received && state.recovery?.csrf && state.recovery?.capture_token) {
            csrf = state.recovery.csrf
            captureToken = state.recovery.capture_token
            submissionId = null
            await loadStatus(true)
            showNotice(`Presensi sudah diterima server sebagai ${submitted.action === 'check_in' ? 'Check-in' : 'Check-out'}. Status telah disinkronkan.`, 'success')
          } else {
            submissionId = null
            await loadStatus(true)
            showNotice(error.message, 'error')
          }
        } catch {
          showNotice(error.message, 'error', () => submitButton.click())
        }
      } else {
        try {
          const state = await fetchStatus(submitted.employeeId, submitted.submissionId, submitted.action, submitted.projectId)
          if (state.submission_received && state.recovery?.csrf && state.recovery?.capture_token) {
            csrf = state.recovery.csrf
            captureToken = state.recovery.capture_token
            submissionId = null
            await loadStatus(true)
            showNotice(`Presensi sudah diterima server sebagai ${submitted.action === 'check_in' ? 'Check-in' : 'Check-out'}. Status telah disinkronkan.`, 'success')
          } else {
            showNotice(error instanceof Error ? error.message : 'Presensi belum dapat dikirim.', 'error', () => submitButton.click())
          }
        } catch {
          showNotice('Koneksi terputus saat konfirmasi. Coba lagi untuk memeriksa status sebelum mengirim ulang.', 'error', () => submitButton.click())
        }
      }
    } finally {
      busy = false
      employee.disabled = false
      project.disabled = Boolean(activeProject) || !hasActiveProjects
      updateCameraAvailability()
      updateSubmit()
    }
  }

  employee.addEventListener('change', loadStatus)
  project.addEventListener('change', () => { submissionId = null; resetProof(); clearNotice() })
  openCameraButton.addEventListener('click', openCamera)
  captureButton.addEventListener('click', captureProof)
  retakeButton.addEventListener('click', openCamera)
  form.addEventListener('submit', submitPresensi)
  window.addEventListener('pagehide', stopCamera)

  loadBootstrap().catch((error) => showNotice(error instanceof Error ? error.message : 'Formulir presensi belum tersedia.'))
})()
