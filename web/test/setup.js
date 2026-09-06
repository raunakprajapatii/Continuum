// jsdom gaps the simulation hook tests need stubbed:
//   - HTMLMediaElement.play/pause throw "not implemented" in jsdom
//   - URL.createObjectURL / revokeObjectURL are undefined in jsdom
//   - the Audio constructor registers instances so tests can fire
//     onended / ontimeupdate deterministically
//   - React 19's act() only wraps updates when IS_REACT_ACT_ENVIRONMENT is set

globalThis.IS_REACT_ACT_ENVIRONMENT = true

Object.defineProperty(window.HTMLMediaElement.prototype, 'play', {
  configurable: true,
  value() {
    this.paused = false
    this.ended = false
    return Promise.resolve()
  },
})
Object.defineProperty(window.HTMLMediaElement.prototype, 'pause', {
  configurable: true,
  value() {
    this.paused = true
  },
})

let objectUrlSeq = 0
if (typeof window.URL.createObjectURL !== 'function') {
  window.URL.createObjectURL = () => `blob:continuum-mock-${++objectUrlSeq}`
  window.URL.revokeObjectURL = () => {}
}

// Every Audio element created during a test is registered here so tests can
// drive playback events. window.__audioPlayShouldFail simulates an autoplay
// block (play() rejecting) for the NEEDS_GESTURE path.
const instances = []
window.__audioInstances = instances
window.__audioPlayShouldFail = false
window.Audio = class MockAudio {
  constructor(url) {
    this.url = url
    this.volume = 1
    this.paused = true
    this.ended = false
    this.currentTime = 0
    this.duration = NaN
    this.onended = null
    this.ontimeupdate = null
    instances.push(this)
  }

  play() {
    if (window.__audioPlayShouldFail) {
      this.paused = true
      return Promise.reject(new Error('NotAllowedError: play() failed because the user did not interact with the document first'))
    }
    this.paused = false
    this.ended = false
    return Promise.resolve()
  }

  pause() {
    this.paused = true
  }
}