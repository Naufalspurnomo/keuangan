const MAX_DATA_URL_CHARACTERS = 196_608
const MAX_IMAGE_BYTES = 144 * 1024
const MAX_SOURCE_IMAGE_BYTES = 15 * 1024 * 1024
const MAX_IMAGE_DIMENSION = 1_600
const MAX_SOURCE_PIXELS = 40_000_000

function readAsDataUrl(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('Gambar Project gagal dibaca.'))
    reader.onload = () => typeof reader.result === 'string'
      ? resolve(reader.result)
      : reject(new Error('Gambar Project gagal dibaca.'))
    reader.readAsDataURL(file)
  })
}

export async function compressProjectImage(file: File) {
  if (!['image/png', 'image/jpeg'].includes(file.type)) {
    throw new Error('Gambar Project harus PNG atau JPEG.')
  }
  if (file.size <= 0 || file.size > MAX_SOURCE_IMAGE_BYTES) {
    throw new Error('Ukuran gambar sumber harus di bawah 15 MB.')
  }

  const source = await readAsDataUrl(file)
  return new Promise<string>((resolve, reject) => {
    const image = new Image()
    image.onerror = () => reject(new Error('Gambar Project gagal diproses.'))
    image.onload = () => {
      try {
        const width = image.naturalWidth
        const height = image.naturalHeight
        if (width <= 0 || height <= 0 || width * height > MAX_SOURCE_PIXELS) {
          reject(new Error('Dimensi gambar terlalu besar untuk diproses.'))
          return
        }
        const scale = Math.min(1, MAX_IMAGE_DIMENSION / Math.max(width, height))
        const canvas = document.createElement('canvas')
        canvas.width = Math.max(1, Math.round(width * scale))
        canvas.height = Math.max(1, Math.round(height * scale))
        const context = canvas.getContext('2d')
        if (!context) {
          reject(new Error('Gambar Project gagal diproses.'))
          return
        }
        context.drawImage(image, 0, 0, canvas.width, canvas.height)
        let data = canvas.toDataURL('image/jpeg', 0.86)
        if (data.length > MAX_DATA_URL_CHARACTERS) data = canvas.toDataURL('image/jpeg', 0.68)
        const approximateBytes = Math.ceil((data.split(',')[1]?.length ?? 0) * 0.75)
        if (data.length > MAX_DATA_URL_CHARACTERS || approximateBytes > MAX_IMAGE_BYTES
            || !/^data:image\/jpeg;base64,[A-Za-z0-9+/=]+$/.test(data)) {
          reject(new Error('Gambar terlalu besar setelah dikompresi. Gunakan gambar yang lebih sederhana.'))
          return
        }
        resolve(data)
      } catch {
        reject(new Error('Gambar Project gagal diproses.'))
      }
    }
    image.src = source
  })
}
