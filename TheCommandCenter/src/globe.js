import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { globePosition } from './geography.js'

export function createGlobe(container) {
  let renderer
  try {
    renderer = new THREE.WebGLRenderer({
      alpha: true,
      antialias: true,
      preserveDrawingBuffer: true,
    })
  } catch {
    container.classList.add('globe-fallback')
    container.textContent = '3D map unavailable: WebGL is not supported.'
    return { focus() {}, clear() {}, reset() {}, dispose() {} }
  }
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2))
  renderer.setClearColor(0x000000, 0)
  renderer.domElement.setAttribute(
    'aria-label',
    'Interactive Earth showing the selected IP location. Drag to rotate, scroll to zoom.',
  )
  renderer.domElement.setAttribute('role', 'img')
  container.append(renderer.domElement)
  const scene = new THREE.Scene()
  const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 100)
  camera.position.set(0, 0.2, 4.2)
  const controls = new OrbitControls(camera, renderer.domElement)
  controls.enablePan = false
  controls.enableZoom = true
  controls.minDistance = 2.5
  controls.maxDistance = 6
  controls.enableDamping = true
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches
  controls.autoRotate = false
  controls.autoRotateSpeed = 0.4
  const material = new THREE.MeshStandardMaterial({
    color: 0xffffff,
    roughness: 0.95,
    metalness: 0.12,
  })
  const geometry = new THREE.SphereGeometry(1, 64, 48)
  const earth = new THREE.Mesh(geometry, material)
  scene.add(earth)
  new THREE.TextureLoader().load(
    '/earth.jpg',
    (texture) => {
      texture.colorSpace = THREE.SRGBColorSpace
      material.map = texture
      material.needsUpdate = true
      container.dataset.texture = 'loaded'
    },
    undefined,
    () => {
      container.dataset.texture = 'failed'
    },
  )
  scene.add(new THREE.AmbientLight(0xc5e5de, 1.7))
  const light = new THREE.DirectionalLight(0xd8ffed, 3.4)
  light.position.set(-3, 3, 4)
  scene.add(light)
  const rim = new THREE.DirectionalLight(0x77efbd, 1.1)
  rim.position.set(3, -1, -2)
  scene.add(rim)
  const markerGeometry = new THREE.SphereGeometry(0.025, 16, 12)
  const markerMaterial = new THREE.MeshBasicMaterial({ color: 0xff7770 })
  const marker = new THREE.Mesh(markerGeometry, markerMaterial)
  const ringGeometry = new THREE.RingGeometry(0.04, 0.05, 40)
  const ring = new THREE.Mesh(ringGeometry, markerMaterial)
  marker.visible = ring.visible = false
  scene.add(marker, ring)
  let destination = null
  controls.addEventListener('start', () => { destination = null })
  const resize = new ResizeObserver(() => {
    const { width, height } = container.getBoundingClientRect()
    renderer.setSize(width, height)
    camera.aspect = width / Math.max(height, 1)
    camera.zoom = Math.min(camera.aspect, 1)
    camera.updateProjectionMatrix()
  })
  resize.observe(container)
  renderer.setAnimationLoop((time) => {
    if (document.hidden) return
    if (destination) {
      const direction = camera.position.clone().normalize()
      const rotation = new THREE.Quaternion().setFromUnitVectors(direction, destination)
      const step = new THREE.Quaternion().slerp(rotation, reducedMotion ? 1 : 0.1)
      camera.position.applyQuaternion(step)
      if (camera.position.clone().normalize().distanceTo(destination) < 0.001) destination = null
    }
    ring.scale.setScalar(reducedMotion ? 1 : 1 + 0.25 * Math.sin(time / 350))
    controls.update()
    renderer.render(scene, camera)
  })
  return {
    focus(latitude, longitude, risk) {
      destination = new THREE.Vector3(...globePosition(latitude, longitude))
      marker.position.copy(destination).multiplyScalar(1.025)
      ring.position.copy(destination).multiplyScalar(1.03)
      ring.lookAt(destination.clone().multiplyScalar(2))
      markerMaterial.color.set(risk >= 80 ? 0xff7770 : risk >= 60 ? 0xffbf69 : 0x79b8de)
      marker.visible = ring.visible = true
      container.dataset.latitude = String(latitude)
      container.dataset.longitude = String(longitude)
    },
    clear() {
      marker.visible = ring.visible = false
      destination = null
      delete container.dataset.latitude
      delete container.dataset.longitude
    },
    reset() {
      destination = new THREE.Vector3(0, 0.05, 1).normalize()
      camera.position.setLength(4.2)
    },
    dispose() {
      resize.disconnect()
      renderer.setAnimationLoop(null)
      controls.dispose()
      geometry.dispose()
      markerGeometry.dispose()
      ringGeometry.dispose()
      markerMaterial.dispose()
      material.map?.dispose()
      material.dispose()
      renderer.dispose()
    },
  }
}
